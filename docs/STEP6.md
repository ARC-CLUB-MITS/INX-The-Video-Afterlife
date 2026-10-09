# Step 6 — Hybrid Search & Retrieval

Step 6 combines two retrieval signals:

- **Semantic similarity (65%)** from the verified FAISS index.
- **Keyword relevance (35%)** from exact/term overlap in the stored transcript chunks.

The backend ranks all chunks, removes duplicates by `chunk_index`, and returns the highest-ranked verified chunks.

## Trust boundary

FAISS and keyword matching are retrieval mechanisms only. The transcript chunks stored in MySQL remain the source of truth. Each result returns the actual stored chunk text and its timestamp.

## API

`GET /api/videos/<youtube_video_id>/search?q=<query>&top_k=5`

The existing endpoint now performs hybrid retrieval.

## Why hybrid retrieval?

Semantic search is good for paraphrases and conceptual questions. Keyword search is strong when the user asks for an exact term such as `sigmoid`, `ReLU`, or `784`. Combining both reduces misses.
