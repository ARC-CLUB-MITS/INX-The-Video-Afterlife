"""Local semantic embedding + FAISS indexing for INX Step 5.

Design rules:
- Transcript chunks in MySQL remain the source of truth.
- FAISS stores only normalized vectors; metadata maps each vector position
  back to the exact MySQL chunk index.
- Every indexed chunk carries a SHA-256 hash. Search refuses a stale index
  when the stored chunk text no longer matches the indexed text.
- Model is loaded lazily so Step 4 does not pay the Step 5 startup cost.
"""

import hashlib
import json
import os
from pathlib import Path
from threading import Lock

import numpy as np

try:
    import faiss
    from sentence_transformers import SentenceTransformer
except ImportError as exc:  # pragma: no cover - exercised when dependencies are missing
    faiss = None
    SentenceTransformer = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
BASE_DIR = Path(__file__).resolve().parents[1]
INDEX_DIR = BASE_DIR / "data" / "faiss_indexes"
MODEL_LOCK = Lock()
_MODEL = None


class EmbeddingProcessingError(RuntimeError):
    pass


def _require_dependencies():
    if faiss is None or SentenceTransformer is None:
        raise EmbeddingProcessingError(
            "Step 5 dependencies are missing. Run: pip install -r requirements.txt"
        ) from _IMPORT_ERROR


def _load_model():
    global _MODEL
    _require_dependencies()
    if _MODEL is None:
        with MODEL_LOCK:
            if _MODEL is None:
                print(f"[INX] Loading embedding model: {MODEL_NAME}")
                _MODEL = SentenceTransformer(MODEL_NAME)
                print("[INX] Embedding model loaded.")
    return _MODEL


def _index_paths(video_db_id):
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    stem = INDEX_DIR / f"video_{int(video_db_id)}"
    return stem.with_suffix(".faiss"), stem.with_suffix(".json")


def _hash_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def delete_index(video_db_id):
    index_path, metadata_path = _index_paths(video_db_id)
    for path in (index_path, metadata_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def get_index_status(video_db_id):
    index_path, metadata_path = _index_paths(video_db_id)
    if not index_path.exists() or not metadata_path.exists():
        return {
            "indexed": False,
            "model": MODEL_NAME,
            "chunk_count": 0,
        }

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return {
            "indexed": True,
            "model": metadata.get("model", MODEL_NAME),
            "dimension": metadata.get("dimension"),
            "chunk_count": len(metadata.get("chunks", [])),
            "created_at": metadata.get("created_at"),
        }
    except (OSError, ValueError, TypeError):
        return {"indexed": False, "model": MODEL_NAME, "chunk_count": 0}


def build_index(video_db_id, chunks):
    if not chunks:
        raise EmbeddingProcessingError("There are no transcript chunks to index.")

    model = _load_model()
    texts = [str(chunk["text"]).strip() for chunk in chunks]
    if any(not text for text in texts):
        raise EmbeddingProcessingError("A transcript chunk is empty and cannot be indexed.")

    print(f"[INX] Embedding {len(texts)} transcript chunks...")
    vectors = model.encode(
        texts,
        batch_size=16,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    vectors = np.asarray(vectors, dtype="float32")
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
        raise EmbeddingProcessingError("Embedding model returned an invalid vector matrix.")

    dimension = int(vectors.shape[1])
    index = faiss.IndexFlatIP(dimension)
    index.add(vectors)

    index_path, metadata_path = _index_paths(video_db_id)
    faiss.write_index(index, str(index_path))

    metadata = {
        "version": 1,
        "model": MODEL_NAME,
        "dimension": dimension,
        "video_db_id": int(video_db_id),
        "chunks": [
            {
                "position": position,
                "chunk_index": int(chunk["chunk_index"]),
                "text_sha256": _hash_text(chunk["text"]),
                "start_time": float(chunk["start_time"]),
                "end_time": float(chunk["end_time"]),
            }
            for position, chunk in enumerate(chunks)
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "indexed": True,
        "model": MODEL_NAME,
        "dimension": dimension,
        "chunk_count": len(chunks),
    }


def _load_verified_index(video_db_id, chunks):
    _require_dependencies()
    index_path, metadata_path = _index_paths(video_db_id)
    if not index_path.exists() or not metadata_path.exists():
        raise EmbeddingProcessingError("Semantic index has not been built for this video yet.")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        index = faiss.read_index(str(index_path))
    except Exception as exc:
        raise EmbeddingProcessingError("The semantic index is corrupted. Rebuild it.") from exc

    indexed_chunks = metadata.get("chunks")
    if not isinstance(indexed_chunks, list) or len(indexed_chunks) != len(chunks):
        raise EmbeddingProcessingError("The semantic index is stale. Rebuild it.")

    current_by_index = {int(c["chunk_index"]): c for c in chunks}
    for item in indexed_chunks:
        chunk_index = int(item["chunk_index"])
        current = current_by_index.get(chunk_index)
        if current is None or _hash_text(current["text"]) != item.get("text_sha256"):
            raise EmbeddingProcessingError("The semantic index is stale. Rebuild it.")

    if index.ntotal != len(chunks):
        raise EmbeddingProcessingError("The semantic index is inconsistent. Rebuild it.")

    return index, metadata


def search_index(video_db_id, query, chunks, top_k=5):
    query = str(query or "").strip()
    if not query:
        raise EmbeddingProcessingError("Search query cannot be empty.")

    index, metadata = _load_verified_index(video_db_id, chunks)
    model = _load_model()
    vector = model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype("float32")

    k = max(1, min(int(top_k), index.ntotal))
    scores, positions = index.search(vector, k)
    chunk_by_index = {int(c["chunk_index"]): c for c in chunks}
    results = []

    for score, position in zip(scores[0], positions[0]):
        if int(position) < 0:
            continue
        mapping = metadata["chunks"][int(position)]
        chunk = chunk_by_index[int(mapping["chunk_index"])]
        results.append(
            {
                "score": float(score),
                "chunk_index": int(chunk["chunk_index"]),
                "start_time": float(chunk["start_time"]),
                "end_time": float(chunk["end_time"]),
                "text": chunk["text"],
            }
        )

    return results
