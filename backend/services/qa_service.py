"""Grounded Q&A for INX Step 8.

Gemini is given only the chunks returned by the verified hybrid retriever.
It may answer only from those chunks and must cite the supplied chunk indices.
The backend validates every citation against the retrieved evidence.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

try:
    from google import genai
    from google.genai import types
except ImportError:  # Evidence fallback remains available without the Gemini SDK.
    genai = None
    types = None

from services.llm_service import LLMProcessingError

QA_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "supported": {"type": "boolean"},
        "evidence_chunk_indices": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["answer", "supported", "evidence_chunk_indices"],
}



REFUSAL_TEXT = "The transcript evidence provided does not contain enough information to answer this."


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _meaningful_tokens(text):
    stop = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "how", "in", "is", "it", "of", "on", "or", "that", "the", "their",
        "this", "to", "what", "when", "where", "which", "why", "with", "does",
        "do", "can", "into", "about", "you", "your", "they", "we", "i",
    }
    words = re.findall(r"[a-zA-Z0-9]+", str(text).lower())
    return {w for w in words if w not in stop and len(w) > 2}

def _retrieval_guard(question, retrieved_chunks):
    """Reject weak retrieval before sending evidence to the LLM."""

    if not retrieved_chunks:
        print("[INX] Retrieval guard: no chunks retrieved.")
        return False, "No transcript evidence was retrieved for this question."

    min_score = _env_float("QA_MIN_RETRIEVAL_SCORE", 0.58)
    top = max(float(c.get("score", 0.0)) for c in retrieved_chunks)

    print(
        f"[INX] Retrieval guard: top_score={top:.3f}, "
        f"threshold={min_score:.3f}, "
        f"retrieved_chunks={len(retrieved_chunks)}"
    )

    if top < min_score:
        print("[INX] Retrieval guard rejected question: score below threshold.")
        return False, REFUSAL_TEXT

    q_tokens = _meaningful_tokens(question)

    if not q_tokens:
        print("[INX] Retrieval guard rejected question: no meaningful query terms.")
        return False, "Please ask a more specific question about the video."

    has_keyword_anchor = any(
        _meaningful_tokens(c.get("text", "")) & q_tokens
        for c in retrieved_chunks[: min(3, len(retrieved_chunks))]
    )

    if not has_keyword_anchor:
        print("[INX] Retrieval guard rejected question: no keyword anchor in top 3 chunks.")
        return False, REFUSAL_TEXT

    return True, ""

def _clean_citations(citations, valid_indices):
    if not isinstance(citations, list):
        return []
    valid_set = set(valid_indices)
    clean = []
    for value in citations:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            continue
        if idx in valid_set and idx not in clean:
            clean.append(idx)
    return clean


def _is_retryable_gemini_error(exc):
    text = str(exc).lower()
    markers = ("429", "503", "unavailable", "resource exhausted", "temporarily", "high demand", "rate limit", "quota", "billing", "exhausted")
    return any(marker in text for marker in markers)


def _retry_delay(attempt):
    return (2, 5, 10, 15)[min(int(attempt), 3)]


def _safe_gemini_fallback(retrieved_chunks, reason):
    """Return verified evidence instead of fabricating an answer when Gemini is unavailable."""
    sources = [
        {
            "chunk_index": int(c["chunk_index"]),
            "start_time": float(c["start_time"]),
            "end_time": float(c["end_time"]),
            "text": c["text"],
        }
        for c in retrieved_chunks[:3]
    ]
    return {
        "answer": "AI is temporarily unavailable. Showing the most relevant verified transcript evidence instead of guessing.",
        "supported": False,
        "evidence_chunk_indices": [s["chunk_index"] for s in sources],
        "sources": sources,
        "grounding": {
            "status": "fallback_evidence",
            "reason": reason,
            "retrieval_threshold": _env_float("QA_MIN_RETRIEVAL_SCORE", 0.58),
            "top_retrieval_score": max(float(c.get("score", 0.0)) for c in retrieved_chunks),
            "cited_retrieved_chunks": [s["chunk_index"] for s in sources],
        },
    }

def _qa_json_schema(valid_indices):
    """JSON schema that makes it impossible for the model to cite a chunk that
    was not retrieved. Ollama enforces this at decoding time."""
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "supported": {"type": "boolean"},
            "evidence_chunk_indices": {
                "type": "array",
                "items": {"type": "integer", "enum": [int(i) for i in valid_indices]},
                "maxItems": 3,
            },
        },
        "required": ["answer", "supported", "evidence_chunk_indices"],
    }


def _call_ollama(prompt, valid_indices=None):
    """Generate a JSON-only draft with the local Ollama API.

    When valid_indices is given, Ollama's structured-output mode constrains the
    citation list to those exact chunk numbers. Small models otherwise often
    invent indices such as [1]. The backend still validates everything afterwards.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b").strip()
    if not model:
        raise LLMProcessingError("OLLAMA_MODEL is empty. Configure it in backend/.env.")

    payload = {
        "model": model,
        "prompt": prompt + "\n\nReturn only a valid JSON object with keys answer, supported, evidence_chunk_indices.",
        "stream": False,
        "format": _qa_json_schema(valid_indices) if valid_indices else "json",
        "options": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = max(5, min(int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")), 300))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LLMProcessingError(f"Ollama is unavailable at {base_url}: {exc}") from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise LLMProcessingError(f"Ollama did not return a usable response: {exc}") from exc

    text = body.get("response") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise LLMProcessingError("Ollama returned an empty answer.")
    return text, model


def _call_gemini(prompt):
    """Generate a JSON draft with Gemini when explicitly selected or used as fallback."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if not api_key:
        raise LLMProcessingError("Gemini is not configured; GEMINI_API_KEY is missing.")
    if genai is None or types is None:
        raise LLMProcessingError("Gemini SDK is not installed.")

    client = genai.Client(api_key=api_key)
    response = None
    max_attempts = max(1, min(int(os.getenv("GEMINI_MAX_RETRIES", "3")), 5))
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=QA_SCHEMA,
                ),
            )
            break
        except Exception as retry_exc:
            if not _is_retryable_gemini_error(retry_exc) or attempt == max_attempts - 1:
                raise
            delay = _retry_delay(attempt)
            print(f"[INX] Gemini Q&A retry {attempt + 1}/{max_attempts - 1} in {delay}s")
            time.sleep(delay)
    text = getattr(response, "text", None)
    if not text:
        raise LLMProcessingError("Gemini returned an empty answer.")
    return text, model


def answer_question(question, retrieved_chunks):
    question = str(question or "").strip()
    if not question:
        raise LLMProcessingError("Question cannot be empty.")
    if not retrieved_chunks:
        raise LLMProcessingError("No transcript evidence was retrieved for this question.")

    allowed, guard_message = _retrieval_guard(question, retrieved_chunks)
    if not allowed:
        # This is a safe refusal, not an LLM failure. Never ask Gemini to guess.
        return {
            "answer": guard_message,
            "supported": False,
            "evidence_chunk_indices": [],
            "sources": [],
            "grounding": {
                "status": "refused",
                "reason": "retrieval_confidence_too_low",
                "retrieval_threshold": _env_float("QA_MIN_RETRIEVAL_SCORE", 0.58),
            },
        }

    evidence_parts = []
    valid_indices = []
    for chunk in retrieved_chunks:
        idx = int(chunk["chunk_index"])
        valid_indices.append(idx)
        evidence_parts.append(
            f"[CHUNK {idx}]\n"
            f"TIME: {float(chunk['start_time']):.3f}-{float(chunk['end_time']):.3f}\n"
            f"TEXT: {chunk['text']}"
        )

    evidence = "\n\n".join(evidence_parts)
    valid_text = ", ".join(str(x) for x in valid_indices)

    prompt = f"""
You are a strict transcript-grounded question-answering system.

Your ONLY source of truth is the supplied transcript evidence.
You have NO permission to use outside knowledge, memory, or assumptions.

CRITICAL RULES:

1. Answer only what the supplied transcript explicitly supports.
2. Treat the user's question as potentially containing false assumptions.
3. Never accept an unsupported premise merely because it appears in the question.
4. If the question contradicts the transcript, explicitly reject that premise.
5. If the evidence is insufficient or contradictory, set supported=false.
6. When supported=false, use this exact answer:
   "{REFUSAL_TEXT}"
7. Do not invent facts, explanations, numbers, causes, or relationships.
8. Every factual statement must be directly supported by the supplied evidence.
9. Cite only the exact supplied database chunk_index values (the numbers listed under VALID CHUNK INDICES).
10. Never invent or renumber citation indices.
11. Keep supported answers concise and limited to what the evidence establishes.

IMPORTANT EXAMPLE:
If the question asks why a network uses 100 hidden layers,
but the transcript describes two hidden layers,
you MUST NOT explain why it uses 100 layers.
You must reject the unsupported premise.

USER QUESTION:
{question}

VALID CHUNK INDICES:
{valid_text}

TRANSCRIPT EVIDENCE:
{evidence}

Return only valid JSON with these exact keys:
{{
  "answer": "string",
  "supported": true,
  "evidence_chunk_indices": [<chunk_index values copied from VALID CHUNK INDICES above>]
}}

For an unsupported question, set supported to false,
use the required refusal answer, and return an empty citation array.
"""
    provider = os.getenv("QA_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "gemini", "auto"}:
        print(f"[INX] Unknown QA_PROVIDER={provider!r}; using local Ollama.")
        provider = "ollama"
    print(f"[INX] Q&A provider selected: {provider}")
    try:
        provider_used = provider
        if provider == "gemini":
            text, model_used = _call_gemini(prompt)
        elif provider == "auto":
            try:
                text, model_used = _call_ollama(prompt, valid_indices=valid_indices)
                provider_used = "ollama"
            except Exception as ollama_exc:
                print(f"[INX] Ollama failed; trying configured Gemini provider: {ollama_exc}")
                text, model_used = _call_gemini(prompt)
                provider_used = "gemini"
        else:
            text, model_used = _call_ollama(prompt, valid_indices=valid_indices)
            provider_used = "ollama"

        try:
            result = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise LLMProcessingError("Gemini returned an invalid Q&A response.") from exc

        if not isinstance(result, dict):
            raise LLMProcessingError("Gemini returned an invalid Q&A response.")
# Deterministic protection against unsupported numerical premises.
        question_lower = question.lower()
        answer_lower = str(result.get("answer", "")).lower()
        evidence_lower = " ".join(
            str(chunk.get("text", "")).lower()
            for chunk in retrieved_chunks
        )

        false_numeric_premise = re.search(
            r"\b(\d+)\s+(?:hidden\s+)?layers?\b",
            question_lower,
        )

        if false_numeric_premise:
            claimed_count = false_numeric_premise.group(1)

            # If the question asserts a layer count that the transcript does not
            # support, fail closed rather than accepting the model's explanation.
            transcript_counts = {
                match.group(1)
                for match in re.finditer(
                    r"\b(\d+)\s+hidden\s+layers?\b",
                    evidence_lower,
                )
            }

            if (
                claimed_count not in transcript_counts
                and re.search(r"\bwhy\b|\bexactly\b", question_lower)
            ):
                print(
                    "[INX] Grounding validation rejected unsupported "
                    f"layer-count premise: {claimed_count}"
                )
                return {
                    "answer": REFUSAL_TEXT,
                    "supported": False,
                    "evidence_chunk_indices": [],
                    "sources": [],
                    "grounding": {
                        "status": "refused",
                        "reason": "unsupported_numeric_premise",
                        "provider": "ollama",
                    },
                }




        answer = str(result.get("answer", "")).strip()
        supported = bool(result.get("supported", False))
        citations = result.get("evidence_chunk_indices", [])
        if not isinstance(citations, list):
            citations = []

        clean = _clean_citations(citations, valid_indices)

        # Fail closed: a positive answer without valid source citations is never shown.
        if supported and not clean:
            raise LLMProcessingError("The generated answer did not provide valid transcript evidence.")

        if not answer:
            raise LLMProcessingError("Gemini returned an empty answer.")

        max_chars = max(300, int(os.getenv("QA_MAX_ANSWER_CHARS", "1200")))
        if len(answer) > max_chars:
            answer = answer[: max_chars - 3].rstrip() + "..."

        if not supported:
            clean = []
            answer = REFUSAL_TEXT

        by_index = {int(c["chunk_index"]): c for c in retrieved_chunks}
        sources = []
        for idx in clean:
            c = by_index[idx]
            sources.append({
                "chunk_index": idx,
                "start_time": float(c["start_time"]),
                "end_time": float(c["end_time"]),
                "text": c["text"],
            })

        # Citation must point to retrieved evidence, and at least one citation should
        # be among the strongest retrieved candidates. This prevents citation drift.
        top_indices = {int(c["chunk_index"]) for c in retrieved_chunks[:3]}
        if supported and not (set(clean) & top_indices):
            raise LLMProcessingError("The generated answer cited evidence outside the strongest retrieved context.")

        return {
            "answer": answer,
            "supported": supported,
            "evidence_chunk_indices": clean,
            "sources": sources,
            "grounding": {
                "status": "grounded" if supported else "refused",
                "provider": provider_used,
                "model": model_used,
                "retrieval_threshold": _env_float("QA_MIN_RETRIEVAL_SCORE", 0.58),
                "top_retrieval_score": max(float(c.get("score", 0.0)) for c in retrieved_chunks),
                "cited_retrieved_chunks": clean,
            },
        }
    except LLMProcessingError as exc:
        # The question and retrieval guard already passed. If Gemini returned an
        # unusable response, fall back to the retrieved source instead of failing.
        print(f"[INX] {provider} Q&A output was unusable; returning evidence fallback: {exc}")
        fallback = _safe_gemini_fallback(retrieved_chunks, f"{provider}_response_unusable")
        fallback["grounding"]["provider"] = provider
        return fallback
    except Exception as exc:
        print(f"[INX] {provider} Q&A error: {type(exc).__name__}: {exc}")
        error_text = str(exc).lower()
        if provider == "auto":
            reason = "all_providers_unavailable"
        elif _is_retryable_gemini_error(exc):
            reason = f"{provider}_temporarily_unavailable"
        else:
            reason = f"{provider}_provider_error"
        print("[INX] Returning verified evidence fallback instead of guessing.")
        fallback = _safe_gemini_fallback(retrieved_chunks, reason)
        fallback["grounding"]["provider"] = provider
        return fallback