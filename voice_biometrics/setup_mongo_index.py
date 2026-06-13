#!/usr/bin/env python3
"""
One-time setup: create the Atlas Vector Search index on the users
collection's `voice_embedding` field.

Run after pointing MONGODB_URI at your Atlas cluster:

    python -m voice_biometrics.setup_mongo_index --backend speechbrain

Atlas takes ~1-2 minutes to finish building the index before
$vectorSearch queries (mongo_store.find_best_match) will return results.
"""

import argparse

from pymongo.errors import CollectionInvalid
from pymongo.operations import SearchIndexModel

from voice_biometrics.mongo_store import (
    _get_collection,
    MONGODB_VECTOR_INDEX,
    EMBEDDING_DIMS,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=list(EMBEDDING_DIMS), default="speechbrain",
                         help="Which backend's embedding dimensionality to index for")
    args = parser.parse_args()

    coll = _get_collection()
    dims = EMBEDDING_DIMS[args.backend]

    # Search indexes can only be created on existing collections.
    try:
        coll.database.create_collection(coll.name)
        print(f"Created empty collection {coll.full_name}")
    except CollectionInvalid:
        pass  # already exists

    index_model = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "voice_embedding",
                    "numDimensions": dims,
                    "similarity": "cosine",
                },
                {
                    "type": "filter",
                    "path": "voice_backend",
                },
            ]
        },
        name=MONGODB_VECTOR_INDEX,
        type="vectorSearch",
    )

    result = coll.create_search_index(model=index_model)
    print(f"Created vector search index '{result}' on {coll.full_name}")
    print(f"  numDimensions={dims} ({args.backend}), similarity=cosine")
    print("Note: Atlas may take 1-2 minutes to finish building the index.")


if __name__ == "__main__":
    main()
