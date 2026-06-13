"""
MongoDB Atlas-backed user store + voice embedding vector search.

Two things live here:

1. A users.json-compatible interface (load_users / save_users / get_user /
   save_user) so this can be swapped in as a drop-in replacement for the
   flat-file store used elsewhere in the app, if the team decides to move
   off users.json. Each user document is keyed by phone number (_id).

2. Atlas Vector Search over the same collection's `voice_embedding` field,
   for speaker matching (find_best_match) — this is the "best use of
   MongoDB Atlas" piece. Run setup_mongo_index.py once to create the index.

Env vars:
    MONGODB_URI                — Atlas connection string (required)
    MONGODB_DB                 — database name (default: swarampay)
    MONGODB_USERS_COLLECTION   — collection name (default: users)
    MONGODB_VECTOR_INDEX       — Atlas Search index name (default: voice_vector_index)

Install: pip install pymongo
"""

import os
import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from pymongo import MongoClient
    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "swarampay")
MONGODB_USERS_COLLECTION = os.getenv("MONGODB_USERS_COLLECTION", "users")
MONGODB_VECTOR_INDEX = os.getenv("MONGODB_VECTOR_INDEX", "voice_vector_index")

# Embedding dimensionality per backend — used by setup_mongo_index.py and
# to sanity-check stored embeddings.
EMBEDDING_DIMS = {
    "speechbrain": 192,
    "resemblyzer": 256,
}


@lru_cache(maxsize=1)
def _get_client() -> "MongoClient":
    if not PYMONGO_AVAILABLE:
        raise ImportError("pymongo is not installed.\nRun: pip install pymongo")
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not set")
    return MongoClient(MONGODB_URI)


def _get_collection():
    return _get_client()[MONGODB_DB][MONGODB_USERS_COLLECTION]


# ─── users.json-compatible interface ──────────────────────────────────────

def load_users() -> dict:
    """
    Drop-in replacement for the JSON _load_users().
    Returns {phone_number: user_dict} for every user in the collection.
    """
    coll = _get_collection()
    users = {}
    for doc in coll.find():
        phone = doc.pop("_id")
        users[phone] = doc
    return users


def save_users(users: dict):
    """
    Drop-in replacement for the JSON _save_users().
    Upserts every user in `users` (keyed by phone number) into Mongo.
    """
    coll = _get_collection()
    for phone, data in users.items():
        doc = dict(data)
        doc["_id"] = phone
        coll.replace_one({"_id": phone}, doc, upsert=True)


def get_user(phone: str) -> Optional[dict]:
    """Drop-in replacement for users.get(phone) on the loaded JSON dict."""
    coll = _get_collection()
    doc = coll.find_one({"_id": phone})
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


def save_user(phone: str, data: dict):
    """Upsert a single user document."""
    coll = _get_collection()
    doc = dict(data)
    doc["_id"] = phone
    coll.replace_one({"_id": phone}, doc, upsert=True)


# ─── Voice embedding vector search ─────────────────────────────────────────

def atlas_threshold(raw_cosine_threshold: float) -> float:
    """
    Atlas Vector Search normalises cosine similarity to [0, 1] via
    (1 + cos) / 2. Convert a raw cosine threshold (e.g. SpeechBrainBackend's
    0.25) to the equivalent Atlas vectorSearchScore threshold.
    """
    return (1 + raw_cosine_threshold) / 2


def upsert_voice_profile(phone: str, embedding, backend: str):
    """
    Store/update a user's voice embedding for vector search.
    Writes into the same document used by load_users()/save_users(),
    so enrolling via Mongo doesn't create a separate collection.
    """
    coll = _get_collection()
    coll.update_one(
        {"_id": phone},
        {"$set": {
            "voice_embedding": list(embedding),
            "voice_enrolled": True,
            "voice_backend": backend,
        }},
        upsert=True,
    )


def find_best_match(embedding, backend: str, top_k: int = 1) -> list:
    """
    Run $vectorSearch over the users collection's voice_embedding field
    and return the top_k closest matches — i.e. "whose voice is this?"
    rather than "does this match the claimed phone number?".

    Args:
        embedding: live embedding (list or np.ndarray)
        backend:   "speechbrain" or "resemblyzer" — only matches users
                   enrolled with the same backend (embeddings from
                   different backends aren't comparable)
        top_k:     number of nearest neighbours to return

    Returns:
        List of dicts: [{"phone_number": ..., "score": atlas_score}, ...]
        score is the Atlas-normalised cosine similarity in [0, 1].
        Compare against atlas_threshold(raw_threshold), not the raw
        cosine threshold used by the local backends.
    """
    coll = _get_collection()

    pipeline = [
        {
            "$vectorSearch": {
                "index": MONGODB_VECTOR_INDEX,
                "path": "voice_embedding",
                "queryVector": list(embedding),
                "numCandidates": max(top_k * 10, 50),
                "limit": top_k,
                "filter": {"voice_backend": backend},
            }
        },
        {
            "$project": {
                "_id": 0,
                "phone_number": "$_id",
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    return list(coll.aggregate(pipeline))
