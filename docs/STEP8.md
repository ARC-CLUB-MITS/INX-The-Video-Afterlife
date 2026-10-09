# Step 8 — Grounded AI Q&A

Step 8 adds question answering over the verified transcript.

Flow:

`Question → hybrid retrieval → top transcript chunks → Gemini → validated citations → answer + source timestamps`

Gemini receives only retrieved transcript chunks. The backend rejects supported answers without valid chunk citations. If the evidence is insufficient, the system refuses to invent an answer.

FAISS remains retrieval infrastructure and MySQL transcript chunks remain the source of truth.
