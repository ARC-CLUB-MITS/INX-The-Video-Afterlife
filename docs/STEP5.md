# Step 5 — Embedding & Indexing

## Goal
Turn each transcript chunk into a semantic vector so later retrieval can find meaning-related passages even when the user's wording does not exactly match the transcript.

## Architecture

```text
MySQL transcript_chunks
        |
        v
all-MiniLM-L6-v2
        |
        v
normalized embeddings
        |
        v
FAISS IndexFlatIP
        |
        +--> metadata JSON: vector position -> chunk_index + SHA-256
        |
        v
semantic search
        |
        v
MySQL chunk text + real timestamps
```

### Trust rule
FAISS is **not** the source of truth. It only finds candidate chunks.

Every index records a SHA-256 hash of each chunk's exact transcript text. Search verifies the current MySQL chunks against those hashes. If the transcript changed, search refuses to use the stale index and asks for a rebuild.

## Model

`sentence-transformers/all-MiniLM-L6-v2`

It is a lightweight general-purpose sentence embedding model and is appropriate for the 8 GB RAM development machine used for this project.

The model is loaded lazily: Step 4 does not load it until the user explicitly builds/searches the semantic index.

## FAISS

`IndexFlatIP` is used with normalized vectors. Inner product therefore behaves as cosine similarity.

There is no approximate index yet because the initial target is educational videos with tens or hundreds of chunks. Exact search is simple, deterministic, and high quality for this scale.

## Endpoints

- `GET /api/videos/<video_id>/index` — index status
- `POST /api/videos/<video_id>/index` — build/rebuild index
- `GET /api/videos/<video_id>/search?q=...&top_k=5` — semantic search

## Persistence

FAISS indexes live under:

`backend/data/faiss_indexes/`

The mapping file is stored beside the FAISS index. MySQL stores index metadata for visibility, while transcript content remains in MySQL.

## Rebuild behavior

When a fresh transcript/chunk set replaces existing data, the old FAISS index is deleted and its MySQL metadata is removed. This prevents retrieval from an obsolete transcript.

## Expected test

For the neural-network video, after building the index:

`query = "How do weights affect a neuron's activation?"`

The top results should be chunks around the weights/biases discussion rather than only exact keyword matches.
