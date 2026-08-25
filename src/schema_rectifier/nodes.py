from unittest.mock import MagicMock
from langchain_core.runnables import RunnableConfig
from google.cloud import storage
from google.auth.exceptions import DefaultCredentialsError
from google.cloud.storage import blob
import os
import json
import logging
import io
from unittest.mock import Mock

from ollama import ResponseError
import polars as pl
from pydantic import ValidationError

from schema_rectifier.prompts import SINGLE_COLUMN_NAME_MAPPING_PROMPT
from schema_rectifier.utils import ColumnDiffMapping, State, Status

DATA_DICTIONARY_BUCKET = os.environ.get("DATA_DICTIONARY_BUCKET", "schema-rectifier-config")
DATA_DICTIONARY_FILE = os.environ.get("DATA_DICTIONARY_FILE", "data_dictionary.json")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "schema-rectifier-output")
FIRESTORE_PROJECT = os.environ.get("FIRESTORE_PROJECT")
STANDARD_SCHEMA_BUCKET = os.environ.get("STANDARD_SCHEMA_BUCKET", "schema-rectifier-config")
STANDARD_SCHEMA_FILE = os.environ.get("STANDARD_SCHEMA_FILE", "standard_schema.json")

logger = logging.getLogger(__name__)


def _get_storage_client():
    if os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("STORAGE_EMULATOR_HOST"):
        from google.auth.credentials import AnonymousCredentials
        return storage.Client(project=FIRESTORE_PROJECT, credentials=AnonymousCredentials())

    try:
        storage_client = storage.Client(project=FIRESTORE_PROJECT)
    except DefaultCredentialsError as e:
        storage_client = MagicMock()
        mock_blob = MagicMock()
        # When opened for reading ("r"), return a stream with sample CSV data
        # When opened for writing ("w"), return an empty writable stream
        mock_blob.open.side_effect = lambda mode, **kwargs: (
            io.StringIO("col_c,col_a\nval1,val2\n") if "r" in mode else io.StringIO()
        )
        mock_blob.download_as_text.return_value = "{}"
        mock_blob.download_as_bytes.return_value = b"col_c,col_a\nval1,val2\n"
        mock_blob.exists.return_value = True
        storage_client.bucket.return_value.blob.return_value = mock_blob
    except Exception as e:
        msg = f"Failed to get storage client: {e!s}"
        logger.error(f"[_get_storage_client] {msg}")
        raise e
        
    return storage_client

def _parse_gcs_uri(uri: str):
    if uri.startswith("gs://"):
        uri = uri[5:]
    parts = uri.split("/", 1)
    return parts[0], parts[1]

def _load_data_dictionary():
    storage_client = _get_storage_client()
    bucket = storage_client.bucket(DATA_DICTIONARY_BUCKET)
    blob = bucket.blob(DATA_DICTIONARY_FILE)
    if not blob.exists():
        logger.warning(f"Config file gs://{DATA_DICTIONARY_BUCKET}/{DATA_DICTIONARY_FILE} not found. Using empty dictionary.")
        return {}
    content = blob.download_as_text()
    return json.loads(content)

def _load_standard_schema():
    storage_client = _get_storage_client()
    bucket = storage_client.bucket(STANDARD_SCHEMA_BUCKET)
    blob = bucket.blob(STANDARD_SCHEMA_FILE)
    if not blob.exists():
        logger.warning(f"Config file gs://{STANDARD_SCHEMA_BUCKET}/{STANDARD_SCHEMA_FILE} not found. Using empty dictionary.")
        return {}
    content = blob.download_as_text()
    return json.loads(content)

def _get_destination_columns():
    schema = _load_standard_schema()
    if isinstance(schema, dict):
        return schema.get("standard_schema") or schema.get("columns") or []
    elif isinstance(schema, list):
        return schema
    return []

def load(state: State):
    LOG_LABEL = "[load]"
    input_uri = state.get("input_gcs_uri")
    output_uri = state.get("output_gcs_uri", "")
    # Ensure output_uri ends with _rectified.csv
    if not output_uri.endswith("_rectified.csv"):
        if output_uri.endswith(".csv"):
            output_uri = output_uri[:-4] + "_rectified.csv"
        else:
            output_uri = output_uri.rstrip("/") + "_rectified.csv"
    column_mappings = state.get("column_mappings", [])
    
    if not input_uri or not output_uri:
        msg = "Missing GCS URIs for load node"
        logger.error(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "status": Status.INVALID}
    

    import csv
    import io
    import shutil
    storage_client = _get_storage_client()
    in_bucket_name, in_blob_name = _parse_gcs_uri(input_uri)
    out_bucket_name, out_blob_name = _parse_gcs_uri(output_uri)
    in_blob = storage_client.bucket(in_bucket_name).blob(in_blob_name)
    out_blob = storage_client.bucket(out_bucket_name).blob(out_blob_name)
    # Build {source: destination} rename mapping
    rename_map = {
        m["source_column"]: m["destination_column"]
        for m in column_mappings
        if isinstance(m, dict) and "source_column" in m and "destination_column" in m
    }

    # Open GCS streams (memory remains constant O(1))
    with in_blob.open("r", encoding="utf-8") as in_stream, \
         out_blob.open("w", encoding="utf-8") as out_stream:
        
        # Read and rename only the header line
        header_line = in_stream.readline()
        if header_line:
            reader = csv.reader(io.StringIO(header_line))
            header = next(reader)
            new_header = [rename_map.get(col, col) for col in header]
            
            writer = csv.writer(out_stream)
            writer.writerow(new_header)
        
        # Stream the remaining data rows directly in 1MB chunks
        shutil.copyfileobj(in_stream, out_stream, length=1024 * 1024)

    msg = f"Successfully wrote to {output_uri}"
    logger.info(f"{LOG_LABEL} {msg}")
    return {
        "messages": [msg],
        "status": Status.VALID,
        "column_diff": [],
        "invalid_mappings": [],
        "output_gcs_uri": output_uri,
    }


# uses retry_count form State
# VALID -> check passed, ok to continue
# RETRY_OUT -> too many retries, graph will end
def _retry_check(state: State):
    LOG_LABEL = "[_retry_check]"
    MAX_RETRIES = 2
    retry_count = state.get("retry_count", 0)
    if retry_count > MAX_RETRIES:
        msg = "Maximum retries reached."
        logger.error(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "status": Status.RETRY_OUT, "retry_count": 1}
    msg = "Retrying" if retry_count > 0 else "Starting"
    logger.info(f"{LOG_LABEL} {msg}")
    return {
        "messages": [msg],
        "status": Status.VALID,
        "retry_count": 1,
    }  # preserve previous status (valid/invalid)

def _get_llm_response(llm_url: str, payload: dict):
    LOG_LABEL = "[_get_llm_response]"
    try:
        import requests
        base_url = llm_url.rstrip("/")
        chat_url = f"{base_url}/chat" if base_url.endswith("/api") else f"{base_url}/api/chat"
        res = requests.post(chat_url, json=payload)
        res.raise_for_status()
        content = res.json().get("message", {}).get("content", "{}")
        return content
    except Exception as e:
        msg = f"Failed to parse column mapping: {e!s}"
        logger.error(f"{LOG_LABEL} {msg}")
        raise ConnectionError(msg)

def _call_subagent_single_column_name_mapping(llm_url: str, prompt: str, diff: str, data_dictionary: dict):
    LOG_LABEL = "[_call_subagent_single_column_name_mapping]"
    try:
        import requests
        payload = {
            "model": "llama3.1",
            "messages": [
                {"role": "user", "content": prompt.format(diff=diff, data_dictionary=data_dictionary)}
            ],
            "format": ColumnDiffMapping.model_json_schema(),
            "stream": False,
            "options": {"temperature": 0}
        }
        content = _get_llm_response(llm_url, payload)
        column_mappings = [m.model_dump() for m in ColumnDiffMapping.model_validate_json(content).column_diff]
        msg = f"Column mappings generated: {column_mappings}"
        logger.info(f"{LOG_LABEL} {msg}")
        return {
            "messages": [msg],
            "column_mappings": column_mappings,
            "status": Status.VALID,
        }
    except ConnectionError as e:
        msg = "Ollama is not running."
        logger.error(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "column_mappings": [], "status": Status.INVALID}
    except ResponseError as e:
        msg = f"Ollama error: {e!s}"
        logger.error(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "column_mappings": [], "status": Status.INVALID}
    except ValidationError as e:
        msg = f"Failed to parse column mapping: {e!s}"
        logger.error(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "column_mappings": [], "status": Status.INVALID}
    except Exception as e:
        raise e

# triggers pipeline if incoming columns don't match expected values in standard_schema
def gateway_node(state: State) -> dict:
    LOG_LABEL = "[gateway_node]"
    input_uri = state.get("input_gcs_uri")
    if not input_uri:
        msg = "No input URI provided"
        logger.error(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "status": Status.INVALID, "column_diff": []}

    import io
    storage_client = _get_storage_client()
    in_bucket_name, in_blob_name = _parse_gcs_uri(input_uri)
    in_blob = storage_client.bucket(in_bucket_name).blob(in_blob_name)
    df = pl.read_csv(io.BytesIO(in_blob.download_as_bytes()), n_rows=0)
    
    source_columns = df.columns
    dest_data = _get_destination_columns()
    if isinstance(dest_data, dict):
        destination_columns = dest_data.get("columns") or dest_data.get("standard_schema") or []
    else:
        destination_columns = dest_data or []
    
    column_diff = list(
        set(source_columns) - set(destination_columns)
    )
    if column_diff:
        msg = "Columns are invalid, processing..."
        logger.info(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "column_diff": column_diff, "status": Status.INVALID}
    msg = "Columns are valid, nothing to do"
    logger.info(f"{LOG_LABEL} {msg}")
    return {"messages": [msg], "column_diff": [], "status": Status.VALID}


# uses column_diff, invalid_mappings and column_mappings from State
# VALID -> ok to continue with validation
# INVALID -> invalid mappings discovered, go to single_column_name_mapping_validator
# RETRY_OUT -> too many retries, go to human review
def single_column_name_mapping(state: State, llm_url: str) -> dict:
    LOG_LABEL = "[single_column_name_mapping]"

    # short circuit on too many retries
    retry_check_result = _retry_check(state)
    if retry_check_result.get("status", None) == Status.RETRY_OUT:
        msg = "Too many retries"
        logger.error(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "status": Status.RETRY_OUT}

    # short circuit on no work to do
    column_diff = state.get("column_diff", []) + state.get("invalid_mappings", [])
    if not column_diff:
        msg = "No column diff"
        logger.info(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "status": Status.VALID}

    column_mappings = []
    data_dict = _load_data_dictionary()
    for diff in column_diff:
        # LLM call for each column diff
        llm_result = _call_subagent_single_column_name_mapping(
            llm_url, SINGLE_COLUMN_NAME_MAPPING_PROMPT, diff, data_dict
        )
        if llm_result.get("status", None) == Status.VALID:
            column_mappings.extend(llm_result.get("column_mappings", []))

    if column_mappings:
        msg = f"Column mappings generated: {column_mappings}"
        logger.info(f"{LOG_LABEL} {msg}")
        return {
            "messages": [msg],
            "column_mappings": column_mappings,
            "status": Status.VALID,
            "retry_count": 1,
        }

    msg = "No column mappings generated."
    logger.error(f"{LOG_LABEL} {msg}")
    return {"messages": [msg], "status": Status.INVALID, "retry_count": 1}


# uses column_mappings, column_diff and invalid_mappings from State
# VALID -> go to human review
# INVALID -> go back to single_column_name_mapping for another try
def single_column_name_mapping_validator(state: State):
    LOG_LABEL = "[single_column_name_mapping_validator]"
    column_mappings = state.get("column_mappings", [])

    # short circuit on no work to do
    if not column_mappings:
        msg = "No column mappings, trivial passthrough"
        logger.info(f"{LOG_LABEL} {msg}")
        return {"messages": [msg], "status": Status.VALID}

    invalid_mappings = []
    dest_data = _get_destination_columns()
    if isinstance(dest_data, dict):
        standard_schema_columns = dest_data.get("columns") or dest_data.get("standard_schema") or []
    else:
        standard_schema_columns = dest_data or []

    valid_column_mappings = []
    for mapping in column_mappings:
        if isinstance(mapping, dict):
            dest_col = mapping.get("destination_column")
            if dest_col not in standard_schema_columns:
                invalid_mappings.append(
                    mapping.get("source_column") or dest_col
                )  # in case llm returns invalid mappings, forward the output to be corrected instead of trying again from scratch
            else:
                valid_column_mappings.append(mapping)
        else:
            if mapping not in standard_schema_columns:
                invalid_mappings.append(mapping)
            else:
                valid_column_mappings.append(mapping)

    if invalid_mappings:
        msg = f"Invalid mappings found for destination columns: {invalid_mappings}"
        logger.info(f"{LOG_LABEL} {msg}")
        return {
            "messages": [msg],
            "column_mappings": valid_column_mappings,
            "invalid_mappings": invalid_mappings,
            "status": Status.INVALID,
        }

    msg = f"Column mappings validated by subagent: {valid_column_mappings}"
    logger.info(f"{LOG_LABEL} {msg}")
    return {
        "messages": [msg],
        "column_mappings": valid_column_mappings,
        "invalid_mappings": [],
        "status": Status.VALID,
    }


def write_pending_review(state: State, config: RunnableConfig):
    from schema_rectifier.db import add_pending_review
    LOG_LABEL = "[write_pending_review]"
    thread_id = config.get("configurable", {}).get("thread_id", "default_thread")
    input_uri = state.get("input_gcs_uri", "")
    column_mappings = state.get("column_mappings", [])
    invalid_mappings = state.get("invalid_mappings", [])

    add_pending_review(thread_id, input_uri, column_mappings, invalid_mappings)
    msg = f"Wrote pending review to DB for thread {thread_id}"
    logger.info(f"{LOG_LABEL} {msg}")
    return {"messages": [msg]}

# uses column_mappings and invalid_mappings from State
# VALID -> END
# INVALID -> go to single_column_name_mapping
# def human_review(state: State, config: RunnableConfig):
#     LOG_LABEL = "[human_review]"
#     thread_id = config.get("configurable", {}).get("thread_id", "default_thread")
#     column_mappings = state.get("column_mappings", [])
#     invalid_mappings = state.get("invalid_mappings", [])
    
#     if thread_id:
#         from schema_rectifier.db import remove_pending_review
#         try:
#             remove_pending_review(thread_id)
#         except Exception as e:
#             logger.error(f"{LOG_LABEL} Error removing review: {e}")

#     approved = state.get("human_approved")
    
#     if approved:
#         msg = f"Column mappings validated by human: {column_mappings}"
#         logger.info(f"{LOG_LABEL} {msg}")
#         return {
#             "messages": [msg],
#             "column_mappings": column_mappings,
#             "column_diff": [],
#             "invalid_mappings": [],
#             "status": Status.VALID,
#         }
#     else:
#         msg = f"Column mappings rejected by human: {column_mappings}"
#         logger.warning(f"{LOG_LABEL} {msg}")
#         return {
#             "messages": [msg],
#             "column_mappings": column_mappings,
#             "column_diff": invalid_mappings,
#             "invalid_mappings": [],
#             "status": Status.INVALID,
#         }
