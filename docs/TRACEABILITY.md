# Step 4 — Trustworthy and Traceable AI Output

## Design goal

The model is allowed to **interpret** the transcript, but it is not allowed to define the source of its own claims.

The transcript database is the source of truth.

## Evidence flow

```text
YouTube captions
      ↓
transcript_segments
      ↓
transcript_chunks
      ↓
Gemini structured extraction
      ↓
evidence_chunk_indices
      ↓
backend validation
      ↓
real chunk timestamps + transcript excerpt
      ↓
UI + YouTube timestamp link
```

## Fail-closed behavior

An item without valid evidence is not shown or saved.

If Gemini returns a chunk number that does not exist, the backend rejects that item instead of guessing which chunk it meant.

## Timestamp rule

Gemini never supplies authoritative timestamps. The backend calculates `start_time` and `end_time` from the referenced stored chunks.

Therefore, a model mistake cannot create a fake timestamp such as `00:00` for a claim that actually came from another part of the transcript.

## User verification

Every knowledge item exposes:

- evidence chunk number(s)
- source excerpt
- timestamp range
- direct YouTube timestamp link

This lets a reviewer move from a generated claim back to the transcript and then to the original video.

## Why this matters for evaluation

The challenge explicitly evaluates grounding and asks the team to demonstrate where an answer comes from. The traceability layer makes that relationship explicit rather than asking the evaluator to trust the LLM.
