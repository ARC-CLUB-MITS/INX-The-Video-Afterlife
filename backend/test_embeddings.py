"""Lightweight structural tests for Step 5 without downloading the model."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_embedding_service_has_hash_verification():
    source = (ROOT / "services" / "embedding_service.py").read_text(encoding="utf-8")
    assert "sha256" in source
    assert "stale" in source
    assert "IndexFlatIP" in source


def test_routes_expose_index_and_search():
    source = (ROOT / "routes" / "video_routes.py").read_text(encoding="utf-8")
    assert '"/<youtube_video_id>/index"' in source
    assert '"/<youtube_video_id>/search"' in source
    ast.parse(source)


def test_schema_has_embedding_indexes():
    source = (ROOT / "schema.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS embedding_indexes" in source


if __name__ == "__main__":
    test_embedding_service_has_hash_verification()
    test_routes_expose_index_and_search()
    test_schema_has_embedding_indexes()
    print("Step 5 structural tests passed.")
