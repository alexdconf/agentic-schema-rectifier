from unittest.mock import Mock
from google.auth.exceptions import DefaultCredentialsError
from fastapi import FastAPI, BackgroundTasks, HTTPException
from contextlib import asynccontextmanager
from agent_api import graph
import uuid
import os

from google.cloud import firestore

FIRESTORE_PROJECT = os.environ.get("FIRESTORE_PROJECT")
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "pending_reviews")

def get_db_connection():  # TODO: put this and the one in nodes.py in a helper
    if os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("STORAGE_EMULATOR_HOST"):
        from google.auth.credentials import AnonymousCredentials
        return firestore.Client(project=FIRESTORE_PROJECT, credentials=AnonymousCredentials())
        
    try:
        db = firestore.Client(project=FIRESTORE_PROJECT)
    except DefaultCredentialsError as e:
        db = Mock()
        db.collection = Mock()
        db.collection().document = Mock()
        db.collection().document().set = Mock()
        db.collection().document().get = Mock()
        db.collection().document().update = Mock()
    return db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the database table for schema_staging on startup
    db = get_db_connection()
    db.collection(FIRESTORE_COLLECTION).document("schema_staging").set({
        "thread_id": "schema_staging",
        "status": "RUNNING",
        "result": {}
    })
    yield

app = FastAPI(lifespan=lifespan)

from langchain_core.messages import messages_to_dict

def serialize_state_for_firestore(state: dict) -> dict:
    if not isinstance(state, dict):
        return state
    serialized = state.copy()
    if "messages" in serialized and serialized["messages"]:
        try:
            serialized["messages"] = messages_to_dict(serialized["messages"])
        except Exception:
            pass
    if "status" in serialized and hasattr(serialized["status"], "value"):
        serialized["status"] = serialized["status"].value
    return serialized

def _generate_thread_id():
    return uuid.uuid4().hex

def run_schema_job(thread_id: str, state: dict, config: dict):
    db = get_db_connection()
    try:
        result = graph.invoke(input=state, config=config)
        
        # Check if the graph is paused/interrupted
        graph_state = graph.get_state(config)
        if len(graph_state.next) > 0:
            status = "PENDING_REVIEW"
        else:
            status = "COMPLETED"
            
        # Convert the result to a dict or string if needed
        # We assume result is dict-like here
        db.collection(FIRESTORE_COLLECTION).document(thread_id).update({
            "status": status,
            "result": serialize_state_for_firestore(result) # Firestore accepts dicts directly, no need for json.dumps
        })
    except Exception as e:
        db.collection(FIRESTORE_COLLECTION).document(thread_id).update({
            "status": "FAILED",
            "result": {"error": str(e)}
        })
    

from pydantic import BaseModel
from typing import List, Dict, Any

class TriggerRequest(BaseModel):
    state: dict
    config: dict = {}

@app.post("/rectify-schema/trigger")
async def process_schema(req: TriggerRequest, background_tasks: BackgroundTasks):
    thread_id = _generate_thread_id()
    
    config = {"configurable": {"thread_id": thread_id}}
    if req.config:
        config.update(req.config)
        if "configurable" not in config:
            config["configurable"] = {"thread_id": thread_id}
        else:
            config["configurable"]["thread_id"] = thread_id
    
    db = get_db_connection()
    db.collection(FIRESTORE_COLLECTION).document(thread_id).set({
        "thread_id": thread_id,
        "status": "RUNNING",
        "result": {}
    })
    background_tasks.add_task(run_schema_job, thread_id, req.state, config)
    return {"thread_id": thread_id, "message": "Job accepted and running in the background"}

@app.get("/{thread_id}/status")
async def get_status(thread_id: str):
    db = get_db_connection()
    doc = db.collection(FIRESTORE_COLLECTION).document(thread_id).get()
    if doc.exists:
        return doc.to_dict()
    raise HTTPException(status_code=404, detail="Job not found")

from pydantic import BaseModel
from typing import List, Dict, Any

class ResumeRequest(BaseModel):
    column_mappings: List[Dict[str, Any]]
    human_approved: bool

def resume_schema_job(thread_id: str, resume_req: ResumeRequest):
    db = get_db_connection()
    try:
        db.collection(FIRESTORE_COLLECTION).document(thread_id).update({
            "status": "RUNNING"
        })

        config = {"configurable": {"thread_id": thread_id}}
        
        # Inject the human approval data
        graph.update_state(
            config,
            {
                "column_mappings": resume_req.column_mappings,
                "human_approved": resume_req.human_approved
            },
        )
        
        # Resume the graph
        # TODO: fan out
        result = graph.invoke(None, config)
        
        # Check if the graph is paused/interrupted
        graph_state = graph.get_state(config)
        if len(graph_state.next) > 0:
            status = "PENDING_REVIEW"
        else:
            status = "COMPLETED"
            
        db.collection(FIRESTORE_COLLECTION).document(thread_id).update({
            "status": status,
            "result": serialize_state_for_firestore(result)
        })
    except Exception as e:
        db.collection(FIRESTORE_COLLECTION).document(thread_id).update({
            "status": "FAILED",
            "result": {"error": str(e)}
        })

@app.post("/{thread_id}/resume")
async def resume_job(thread_id: str, req: ResumeRequest, background_tasks: BackgroundTasks):
    db = get_db_connection()
    doc = db.collection(FIRESTORE_COLLECTION).document(thread_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
        
    background_tasks.add_task(resume_schema_job, thread_id, req)
    return {"thread_id": thread_id, "message": "Job resume accepted"}
