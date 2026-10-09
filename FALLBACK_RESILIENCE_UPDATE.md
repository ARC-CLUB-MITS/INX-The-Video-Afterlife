# INX: The Video Afterlife — Fallback-Resilient Build

This is an upgrade of the existing INX project. The original Step 8 workspace UI, Flask API, MySQL schema, transcript chunks, local Sentence Transformer embeddings, FAISS indexing, and hybrid retrieval are preserved.

## What changed in this build

- **Gemini quota/configuration resilience:** Q&A returns retrieved transcript evidence with timestamps if Gemini is unavailable, quota-limited, misconfigured, or returns an unusable response. It does not invent an answer.
- **Knowledge-map fallback:** if Gemini knowledge extraction fails, the app builds a clearly labeled *extractive* map from transcript sentences and repeated terms. It is not represented as AI semantic analysis.
- **Evidence validation:** all extractive items use actual database `chunk_index` values; the existing persistence layer resolves timestamps from stored chunks.
- **Regression tests:** offline tests cover extraction fallback, evidence IDs, Q&A guard behavior, and quota fallback.
- **Original UI preserved:** only a small explanatory banner is shown when the extractive fallback is used.

## Start the app (Windows)

1. Keep using your existing MySQL database/schema and `.env` values. Do not overwrite your real `backend/.env` with `.env.example`.
2. In PowerShell, open the `backend` folder and activate your existing virtual environment.
3. Install backend dependencies if needed: `pip install -r requirements.txt`
4. Run offline tests: `python run_tests.py`
5. Start Flask using your existing project command (typically `python app.py`).
6. In a separate PowerShell terminal, open `frontend`, run `npm install` if needed, then `npm run dev`.

## Behavior when Gemini is unavailable

- Transcript capture and chunk storage continue normally.
- Knowledge extraction uses a transcript-only fallback, labeled in the Overview tab.
- Ask AI displays the most relevant retrieved transcript passages and source timestamps rather than pretending it generated an AI answer.
- Semantic search still requires the local embedding/FAISS index to be built.

The local FAISS index files from the supplied project archive are retained in this ZIP. If your local database has different video IDs, the backend's index-status endpoint will indicate whether an index needs rebuilding.
