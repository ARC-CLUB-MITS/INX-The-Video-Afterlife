# Testing — Step 4 Gemini

## 1. Configuration

Check `backend/.env`:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

## 2. Successful extraction

Test:

```text
https://www.youtube.com/watch?v=aircAruvnKk
```

Expected:
- transcript retrieved
- chunks created
- topics displayed
- concepts displayed
- key points displayed
- structure displayed

## 3. Grounding

Inspect the generated records:

```sql
SELECT title, start_time, end_time
FROM video_topics;

SELECT name, start_time, end_time
FROM video_concepts;
```

Timestamps must fall within transcript chunk ranges.

## 4. Reprocessing

Process the same video again.

Expected:
- old transcript/chunks/knowledge for that video are replaced
- no duplicate knowledge rows accumulate

## 5. Missing API key

Remove `GEMINI_API_KEY`.

Expected:
- clear configuration error
- no fake knowledge is stored

## 6. Rate limit/quota

If the Gemini Free Tier quota is exhausted, the backend should report a quota/rate-limit message rather than presenting fabricated results.

## 7. Invalid model

Set an invalid `GEMINI_MODEL`.

Expected:
- model-not-found/unavailable error
- technical details in Flask terminal


## YouTube 502 test

Run:

```powershell
cd backend
python test_transcript.py
```

Expected:

```text
SUCCESS: ... transcript segments retrieved.
```

If the first attempt gets a temporary 502, the backend retries automatically.

## Step 11 regression runner

For a single offline pass across the main contracts, run from `backend`:

```powershell
python run_tests.py
```

See `docs/STEP11.md` for the complete manual test matrix and jury demonstration flow.
