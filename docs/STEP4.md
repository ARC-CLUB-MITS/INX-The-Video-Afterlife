# Step 4 — Knowledge Extraction with Gemini

Step 4 converts transcript chunks into:

- Topics
- Concepts
- Key points
- Video structure

## Provider

This version uses Google's official `google-genai` Python SDK and Gemini.

Gemini structured output is used so the model returns predictable JSON. The
backend validates the returned evidence and derives timestamps from the
original transcript chunks instead of trusting model-generated timestamps.

## Configure

Create/edit:

```text
backend/.env
```

Add:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
```

Do not commit `.env`.

## Grounding

The model receives only transcript chunks.

Every extracted item must include one or more source chunk indices:

```text
topic
  ↓
evidence_chunk_indices
  ↓
original transcript chunk
  ↓
exact start/end timestamp
```

This prevents the model from inventing timestamps.

## Flow

```text
YouTube URL
    ↓
Transcript
    ↓
Transcript chunks
    ↓
Gemini structured extraction
    ↓
Evidence validation
    ↓
Timestamp mapping
    ↓
MySQL
    ↓
React knowledge explorer
```

## Error handling

The backend reports useful errors for:

- missing API key
- invalid API key
- quota/rate limits
- unavailable model
- permission errors
- malformed Gemini output
- unexpected provider failures

## Reliability update

Step 4 now uses two layers of resilience:

1. YouTube transcript retrieval retries transient 502/503/429/network failures up to 5 attempts with increasing delays (2s, 5s, 10s, 20s).
2. Successfully retrieved transcript segments and chunks are committed to MySQL before Gemini is called.
3. If Gemini fails after transcript retrieval, the next `/api/videos/process` request reuses the cached transcript/chunks instead of calling YouTube again.
4. If a video is already `ready`, the API returns the stored transcript, chunks, and knowledge without calling YouTube or Gemini again.

This implements the Step 4 rule: **retrieve once, persist early, analyze separately**.

## Traceability contract

Step 4 uses a fail-closed grounding design.

1. Gemini receives transcript chunks labelled with their exact database `chunk_index`.
2. Gemini must return those exact chunk IDs as `evidence_chunk_indices`.
3. The backend validates every evidence ID against the real chunk set.
4. The backend, not Gemini, calculates timestamps from the real chunks.
5. The database stores the evidence chunk IDs and a source excerpt with every generated topic, concept, key point, and structure section.
6. The UI displays the source chunk(s), excerpt, timestamp range, and a direct YouTube timestamp link.
7. Invalid or missing evidence is rejected rather than silently mapped to another chunk.

This means a generated statement can be traced as:

`knowledge item → evidence chunk ID → transcript text → timestamp → YouTube source`

No generated timestamp is trusted as model output.
