# Step 11 — Testing & Documentation

Step 11 makes the project easier to verify before a jury/demo and documents the architecture and operating procedure.

## Offline regression tests

From `backend` with the virtual environment active:

```powershell
python run_tests.py
```

The runner checks:
- Python syntax across backend files
- retrieval keyword scoring
- knowledge evidence validation
- Q&A retrieval guard
- citation validation and fail-closed behavior
- Step 10 fallback/retry contracts

These tests do **not** call YouTube, Gemini, MySQL, or download models.

## Full manual test matrix

| Area | Test | Expected |
|---|---|---|
| URL | valid YouTube educational URL | transcript/chunks created |
| URL | malformed/non-YouTube URL | clear validation error |
| Transcript | captions unavailable | friendly failure; no fake data |
| Processing | process same video twice | no duplicate knowledge |
| Knowledge | inspect evidence | every item maps to real chunk IDs/timestamps |
| Index | build/rebuild FAISS | index ready and hash verified |
| Search | relevant query | ranked semantic + keyword results |
| Search | unrelated query | weak evidence rejected for Q&A |
| Q&A | supported question | concise answer + verified source |
| Q&A | unrelated question | safe refusal |
| Gemini | 503/429 | retry, then verified-evidence fallback |
| Gemini | missing/invalid key | explicit configuration error |
| Frontend | desktop/tablet/mobile | no horizontal overflow |

## Jury demo path

1. Open the app.
2. Process the prepared educational video.
3. Show knowledge extraction and evidence timestamps.
4. Show hybrid search for a concept.
5. Ask a transcript-supported question.
6. Open the verified source timestamp.
7. Ask an unrelated question and show the safe refusal.
8. If Gemini is temporarily unavailable, show the verified-evidence fallback instead of guessing.

## Grounding principle

**Retrieve first. Answer second. Verify always.**

The transcript and MySQL records remain the source of truth. AI-generated text is never allowed to invent transcript timestamps or cite chunks that were not retrieved.
