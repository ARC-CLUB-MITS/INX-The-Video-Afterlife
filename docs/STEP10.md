# Step 10 — Error Handling & Optimization

## Reliability added
- Gemini 429/503/high-demand failures automatically retry with short backoff.
- Knowledge extraction retries transient Gemini capacity errors.
- Grounded Q&A retries transient Gemini capacity errors.
- After retry exhaustion, Q&A fails closed into a **verified transcript evidence fallback** instead of inventing an answer.
- The frontend labels this state as `AI unavailable — verified evidence shown`.
- API-key, permission, model-not-found, and configuration errors remain explicit and are not hidden by the fallback.
- Retry count is configurable with `GEMINI_MAX_RETRIES` (default 3 attempts total).

## Demo behavior
Normal path:
`Question → Hybrid Retrieval → Grounding Gate → Gemini → Citation Validation → Answer`

Temporary Gemini outage:
`Question → Hybrid Retrieval → Grounding Gate → Gemini retries → Verified transcript evidence fallback`

Unsupported question:
`Question → Hybrid Retrieval → Grounding Gate → Safe refusal`

## Why this matters
The application never treats an external LLM outage as permission to guess. Retrieval remains useful even when generation is temporarily unavailable.
