import os
import streamlit as st
import pandas as pd
from google.cloud import firestore

FIRESTORE_PROJECT = os.environ.get("FIRESTORE_PROJECT")
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "pending_reviews")

# Initialize Firestore client
try:
    if os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("STORAGE_EMULATOR_HOST"):
        from google.auth.credentials import AnonymousCredentials
        db = firestore.Client(project=FIRESTORE_PROJECT, credentials=AnonymousCredentials())
    else:
        db = firestore.Client(project=FIRESTORE_PROJECT)
except Exception as e:
    st.error(f"Could not initialize Firestore client: {e}")
    st.stop()

st.title("Schema Rectification Queue")

# Fetch PENDING_REVIEW jobs from Firestore
# Note: In Firestore, you might need an index for this query depending on your setup.
docs = db.collection(FIRESTORE_COLLECTION).where(filter=firestore.FieldFilter("status", "==", "PENDING_REVIEW")).stream()

data = [doc.to_dict() for doc in docs]
df = pd.DataFrame(data)

import requests

AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://localhost:8000")

if not df.empty:
    # Use thread_id as the identifier
    thread_id = df.iloc[0].get('thread_id', 'Unknown ID')
    st.write(f"Reviewing Job: {thread_id}")
    
    # Extract column mappings from the nested result field
    result_data = df.iloc[0].get('result', {})
    if isinstance(result_data, float):
        result_data = {}
        
    mappings = result_data.get('column_mappings', [])
    if not mappings:
        st.info("No mappings found. Waiting for agent processing...")
        mappings = [{"source_column": "", "destination_column": ""}]
        
    # Render the LLM's mapping as an editable table
    edited_df = st.data_editor(mappings)
    
    if st.button("Approve & Trigger Downstream"):
        # We don't save to DB directly here; the agent_api will handle it 
        # when we resume the job so that they remain decoupled.
        try:
            if isinstance(edited_df, pd.DataFrame):
                payload_mappings = edited_df.to_dict(orient="records")
            else:
                payload_mappings = edited_df
            response = requests.post(
                f"{AGENT_API_URL}/{thread_id}/resume",
                json={
                    "column_mappings": payload_mappings,
                    "human_approved": True
                }
            )
            response.raise_for_status()
            st.success("Approved and triggered downstream!")
            st.rerun()
        except requests.exceptions.RequestException as e:
            st.error(f"Failed to trigger downstream: {e}")