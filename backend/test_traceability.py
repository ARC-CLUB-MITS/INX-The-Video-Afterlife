"""Offline test for the Step 4 grounding contract."""

from services.llm_service import _validate

chunks = [
    {"chunk_index": 0, "start_time": 4.0, "end_time": 54.0, "text": "first source"},
    {"chunk_index": 1, "start_time": 47.0, "end_time": 91.0, "text": "second source"},
    {"chunk_index": 2, "start_time": 88.0, "end_time": 132.0, "text": "third source"},
]

result = {
    "topics": [{
        "title": "Neural networks",
        "description": "Supported topic",
        "evidence_chunk_indices": [1, 2],
    }],
    "concepts": [{
        "name": "Activation",
        "definition": "Supported concept",
        "evidence_chunk_indices": [1],
    }],
    "key_points": [{
        "point": "Supported point",
        "evidence_chunk_indices": [0],
    }],
    "structure": [{
        "title": "Introduction",
        "summary": "Supported section",
        "evidence_chunk_indices": [0],
    }],
}

validated = _validate(result, chunks)
assert validated["topics"][0]["evidence_chunk_indices"] == [1, 2]
assert validated["concepts"][0]["evidence_chunk_indices"] == [1]

# Invalid evidence must be removed instead of being silently mapped to a real chunk.
unsafe = {
    "topics": [{
        "title": "Unsafe",
        "description": "No such chunk",
        "evidence_chunk_indices": [99],
    }],
    "concepts": [],
    "key_points": [],
    "structure": [],
}
assert _validate(unsafe, chunks)["topics"] == []

print("TRACEABILITY TEST PASSED")
print("Valid evidence stays attached to exact chunk IDs.")
print("Invalid evidence is rejected (fail-closed).")
