import logging
import os
from google.cloud import firestore

logger = logging.getLogger(__name__)

# Firestore configuration
FIRESTORE_PROJECT = os.environ.get("FIRESTORE_PROJECT")
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "pending_reviews")

# Initialize lazily
_db = None

def get_db():
    global _db
    if _db is None:
        if os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("STORAGE_EMULATOR_HOST"):
            from google.auth.credentials import AnonymousCredentials
            _db = firestore.Client(project=FIRESTORE_PROJECT, credentials=AnonymousCredentials())
            return _db
        try:
            _db = firestore.Client(project=FIRESTORE_PROJECT)
        except Exception as e:
            logger.warning(f"Could not initialize Firestore client: {e}. Mocking DB for local dev.")
            from unittest.mock import Mock
            _db = Mock()
            # mock collection so it doesn't crash
            _db.collection.return_value.document.return_value.set = Mock()
            _db.collection.return_value.document.return_value.delete = Mock()
    return _db

def add_pending_review(thread_id: str, gcs_uri: str, column_mappings: list, invalid_mappings: list):
    db = get_db()
    doc_ref = db.collection(FIRESTORE_COLLECTION).document(thread_id)
    doc_ref.set({
        "thread_id": thread_id,
        "gcs_uri": gcs_uri,
        "column_mappings": column_mappings,
        "invalid_mappings": invalid_mappings,
        "status": "PENDING_REVIEW"
    })
    logger.info(f"Added pending review for thread {thread_id} to Firestore.")

def remove_pending_review(thread_id: str):
    db = get_db()
    doc_ref = db.collection(FIRESTORE_COLLECTION).document(thread_id)
    doc_ref.delete()
    logger.info(f"Removed pending review for thread {thread_id} from Firestore.")
