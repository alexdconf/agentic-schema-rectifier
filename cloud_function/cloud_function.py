import logging
import os

import functions_framework
from cloudevents.http import CloudEvent


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")  # TODO: make this dynamic?
AGENT_API_URL = os.environ.get("AGENT_API_URL")

@functions_framework.cloud_event
def process_gcs_file(cloud_event: CloudEvent):
    """
    Triggered by a change to a Cloud Storage bucket.
    """
    data = cloud_event.data
    bucket = data["bucket"]
    name = data["name"]

    input_uri = f"gs://{bucket}/{name}"
    output_uri = f"gs://{OUTPUT_BUCKET}/{name}"
    
    logger.info(f"Processing file: {input_uri}")
    
    state_input = {
        "messages": [],
        "input_gcs_uri": input_uri,
        "output_gcs_uri": output_uri,
    }
    
    import requests
    logger.info("Invoking LangGraph pipeline via agent_api...")
    try:
        response = requests.post(
            f"{AGENT_API_URL}/rectify-schema/trigger", 
            json={"state": state_input, "config": {}}
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"Pipeline trigger finished: {result}")
    except Exception as e:
        logger.error(f"Failed to trigger pipeline: {e}")
