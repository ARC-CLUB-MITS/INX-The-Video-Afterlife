# Step 3 — Transcript Cleaning + Intelligent Chunking

## Goal

Convert raw timestamped transcript segments into smaller, coherent retrieval units for later semantic search and question answering.

## Pipeline

```text
Raw transcript segments
        ↓
Normalize whitespace
        ↓
Combine adjacent segments
        ↓
Target ~140 words
        ↓
Maximum ~190 words
        ↓
25-word overlap
        ↓
Preserve start/end timestamps
        ↓
Store in transcript_chunks
```

## Why chunk?

A raw transcript can contain hundreds of tiny caption segments. Sending those directly to an LLM is inefficient and makes retrieval noisy.

Chunks become the evidence units for Step 5 retrieval.

## Timestamp preservation

Each chunk records:

- start_time
- end_time
- original transcript segment count

This enables later answers to cite the exact part of the video.

## Chunk size

The implementation uses approximately 140 words per chunk, with a maximum of approximately 190 words and a small overlap.

This is intentionally based on words rather than a hard tokenizer dependency in Step 3. Exact token-aware sizing can be introduced later if needed.

## Important design rule

We never cut a transcript segment in the middle. Chunk boundaries occur between source segments so evidence remains traceable to the original transcript.
