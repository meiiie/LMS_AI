"""Rebuild Qdrant sidecar collections from active shadow-vector rows.

Usage inside the backend container:
    python scripts/rebuild_qdrant_vector_index.py --batch-size 64

Postgres remains source of truth; this script only upserts Qdrant points.
"""

from __future__ import annotations

import argparse
import json

from app.services.qdrant_vector_index_service import rebuild_qdrant_index_for_active_spaces


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Wiii Qdrant vector sidecar indexes.")
    parser.add_argument(
        "--entity-type",
        action="append",
        choices=["semantic_memories", "knowledge_embeddings"],
        help="Entity type to rebuild. Repeat to rebuild both. Defaults to both.",
    )
    parser.add_argument("--batch-size", type=int, default=None, help="Qdrant upsert batch size.")
    args = parser.parse_args()

    results = rebuild_qdrant_index_for_active_spaces(
        entity_types=args.entity_type,
        batch_size=args.batch_size,
    )
    print(json.dumps([item.to_dict() for item in results], indent=2, ensure_ascii=False))
    return 0 if all(item.status in {"ok", "skipped"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
