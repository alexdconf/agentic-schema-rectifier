from enum import Enum
from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel


class Status(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    RETRY_OUT = "retry_out"


def add_count(current: int | None, increment: int) -> int:
    if current is None:
        return increment
    return current + increment


def merge_column_mappings(current: list, new: list) -> list:
    if current is None:
        return new if new is not None else []
    if not new:
        return current

    mappings = {
        m.get("source_column"): m
        for m in current
        if isinstance(m, dict) and "source_column" in m
    }
    for m in new:
        if isinstance(m, dict) and "source_column" in m:
            mappings[m["source_column"]] = m
    return list(mappings.values())


class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    status: Status
    retry_count: Annotated[int, add_count]
    column_diff: list[str]
    column_mappings: Annotated[list, merge_column_mappings]  # for storing llm output
    invalid_mappings: list[str]  # in case the llm returns invalid mappings
    input_gcs_uri: str
    output_gcs_uri: str
    runtime_data_dictionary: dict
    thread_id: str
    human_approved: bool


# for parsing llm output
class MappingDetail(BaseModel):
    source_column: str
    destination_column: str

class ColumnDiffMapping(BaseModel):
    column_diff: list[MappingDetail]
