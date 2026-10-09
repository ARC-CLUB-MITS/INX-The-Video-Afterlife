import json
import os
import time

try:
    from google import genai
    from google.genai import types
except ImportError:  # Allows transcript-only fallback and offline tests without the SDK.
    genai = None
    types = None


class LLMProcessingError(Exception):
    """Raised when Gemini cannot produce valid, grounded knowledge output."""


KNOWLEDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence_chunk_indices": {
                        "type": "array", "items": {"type": "integer"}
                    },
                },
                "required": ["title", "description", "evidence_chunk_indices"],
            },
        },
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "definition": {"type": "string"},
                    "evidence_chunk_indices": {
                        "type": "array", "items": {"type": "integer"}
                    },
                },
                "required": ["name", "definition", "evidence_chunk_indices"],
            },
        },
        "key_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "point": {"type": "string"},
                    "evidence_chunk_indices": {
                        "type": "array", "items": {"type": "integer"}
                    },
                },
                "required": ["point", "evidence_chunk_indices"],
            },
        },
        "structure": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "evidence_chunk_indices": {
                        "type": "array", "items": {"type": "integer"}
                    },
                },
                "required": ["title", "summary", "evidence_chunk_indices"],
            },
        },
    },
    "required": ["topics", "concepts", "key_points", "structure"],
}


def _clean_items(items, chunk_indices):
    """Fail closed: retain only items whose evidence points to real chunks."""
    valid_chunk_indices = set(chunk_indices)
    cleaned = []

    if not isinstance(items, list):
        return cleaned

    for item in items:
        if not isinstance(item, dict):
            continue

        evidence = item.get("evidence_chunk_indices", [])
        if not isinstance(evidence, list):
            continue

        valid_evidence = []
        for value in evidence:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index in valid_chunk_indices and index not in valid_evidence:
                valid_evidence.append(index)

        # No valid evidence = unsafe to show to the user.
        if not valid_evidence:
            continue

        cleaned_item = dict(item)
        cleaned_item["evidence_chunk_indices"] = valid_evidence
        cleaned.append(cleaned_item)

    return cleaned


def _validate(result, chunks):
    if not isinstance(result, dict):
        raise LLMProcessingError("Gemini returned an invalid knowledge object.")

    for key in ("topics", "concepts", "key_points", "structure"):
        if not isinstance(result.get(key), list):
            raise LLMProcessingError(f"Gemini response is missing the '{key}' list.")

    chunk_indices = [int(chunk["chunk_index"]) for chunk in chunks]

    for key in ("topics", "concepts", "key_points", "structure"):
        result[key] = _clean_items(result[key], chunk_indices)

    return result


def _extract_json(response):
    text = getattr(response, "text", None)
    if not text:
        raise LLMProcessingError("Gemini returned an empty response.")

    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise LLMProcessingError("Gemini returned text that was not valid JSON.") from exc



def _is_retryable_gemini_error(exc):
    """Return True for transient Gemini capacity/rate-limit failures."""
    text = str(exc).lower()
    markers = ("429", "503", "unavailable", "resource exhausted", "temporarily", "high demand", "rate limit", "quota", "billing", "exhausted")
    return any(marker in text for marker in markers)


def _retry_delay(attempt):
    # Short deterministic backoff keeps the demo responsive while surviving brief spikes.
    return (2, 5, 10, 15)[min(int(attempt), 3)]

def extract_knowledge_extractive(chunks):
    """Build clearly extractive, transcript-backed knowledge without an LLM.

    This fallback does not claim semantic understanding. Every item points to
    an exact stored chunk, and the route resolves its timestamps from that chunk.
    """
    import re
    from collections import Counter

    if not chunks:
        raise LLMProcessingError("There are no transcript chunks to analyze.")

    stop = {
        "about", "above", "after", "again", "against", "also", "among", "and", "any", "are",
        "because", "been", "before", "being", "between", "both", "but", "can", "could", "did",
        "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had",
        "has", "have", "having", "here", "how", "into", "its", "just", "more", "most", "not",
        "only", "other", "our", "out", "over", "same", "should", "some", "such", "than", "that",
        "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "too",
        "under", "very", "was", "were", "what", "when", "where", "which", "while", "who", "will",
        "with", "would", "you", "your", "like", "make", "made", "using", "use", "used", "one",
        "two", "first", "next", "lets", "let", "going", "want", "know", "think", "actually",
    }
    indexed = []
    frequency = Counter()
    for chunk in chunks:
        text = re.sub(r"\s+", " ", str(chunk.get("text", ""))).strip()
        sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
        if not sentences and text:
            sentences = [text]
        idx = int(chunk["chunk_index"])
        indexed.append((chunk, text, sentences, idx))
        words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)]
        frequency.update(w for w in words if w not in stop and len(w) >= 4)

    def shorten(text, limit=180):
        text = re.sub(r"\s+", " ", str(text)).strip()
        if len(text) <= limit:
            return text
        cut = text[:limit - 3].rsplit(" ", 1)[0]
        return (cut or text[:limit - 3]).rstrip(".,;:") + "..."

    def title_from(text, fallback):
        cleaned = re.sub(r"^[\W\d_]+", "", text).strip()
        cleaned = shorten(cleaned, 64).rstrip(".,;:")
        return cleaned or fallback

    # Chronological lesson structure: group chunks into up to six contiguous sections.
    count = len(indexed)
    section_count = min(6, count)
    structure = []
    for section in range(section_count):
        start = section * count // section_count
        end = (section + 1) * count // section_count
        group = indexed[start:end]
        first = next((sentences[0] for _, _, sentences, _ in group if sentences), group[0][1])
        summaries = []
        for _, _, sentences, _ in group:
            if sentences:
                summaries.append(sentences[0])
            if len(summaries) >= 2:
                break
        indices = [item[3] for item in group]
        structure.append({
            "title": title_from(first, f"Transcript section {section + 1}"),
            "summary": shorten(" ".join(summaries) or group[0][1]),
            "evidence_chunk_indices": indices,
        })

    # Topics use repeated content words and an exact sentence as their explanation.
    ranked_terms = [word for word, amount in frequency.most_common(14) if amount >= 2 and len(word) >= 4]
    topics = []
    seen_topic = set()
    for term in ranked_terms:
        match = next(((idx, sentence) for _, _, sentences, idx in indexed
                      for sentence in sentences if re.search(rf"\b{re.escape(term)}\b", sentence, re.I)), None)
        if not match:
            continue
        idx, sentence = match
        pretty = term.replace("_", " ").title()
        if pretty.lower() in seen_topic:
            continue
        seen_topic.add(pretty.lower())
        topics.append({"title": pretty, "description": shorten(sentence), "evidence_chunk_indices": [idx]})
        if len(topics) >= 8:
            break
    if not topics:
        for chunk, text, sentences, idx in indexed[:min(3, count)]:
            if text:
                topics.append({"title": title_from(sentences[0] if sentences else text, f"Topic from chunk {idx + 1}"),
                               "description": shorten(text), "evidence_chunk_indices": [idx]})

    # Concepts are repeated content terms with a verbatim explanatory sentence.
    concepts = []
    for term in ranked_terms:
        match = next(((idx, sentence) for _, _, sentences, idx in indexed
                      for sentence in sentences if re.search(rf"\b{re.escape(term)}\b", sentence, re.I)), None)
        if not match:
            continue
        idx, sentence = match
        concepts.append({"name": term.replace("_", " ").title(), "definition": shorten(sentence),
                         "evidence_chunk_indices": [idx]})
        if len(concepts) >= 10:
            break

    # Pick up to eight transcript sentences as key points; do not paraphrase them.
    key_points = []
    seen_points = set()
    for chunk, text, sentences, idx in indexed:
        candidates = sorted(sentences, key=lambda value: len(re.findall(r"\w+", value)), reverse=True)
        if not candidates and text:
            candidates = [text]
        if not candidates:
            continue
        sentence = shorten(candidates[0], 220)
        key = sentence.lower()
        if key in seen_points or len(sentence.split()) < 5:
            continue
        seen_points.add(key)
        key_points.append({"point": sentence, "evidence_chunk_indices": [idx]})
        if len(key_points) >= min(8, count):
            break

    result = {"topics": topics, "concepts": concepts, "key_points": key_points, "structure": structure}
    return _validate(result, chunks)


def extract_knowledge(chunks):
    if not chunks:
        raise LLMProcessingError("There are no transcript chunks to analyze.")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    if not api_key:
        raise LLMProcessingError("Gemini is not configured. Add GEMINI_API_KEY to backend/.env.")
    if not model:
        raise LLMProcessingError("Gemini is not configured. Add GEMINI_MODEL to backend/.env.")

    transcript_parts = []
    for chunk in chunks:
        # IMPORTANT: this is the database chunk_index, not the display number.
        transcript_parts.append(
            f"[CHUNK {int(chunk['chunk_index'])}]\n"
            f"TIME: {float(chunk['start_time']):.3f}-{float(chunk['end_time']):.3f}\n"
            f"TEXT: {chunk['text']}"
        )

    transcript = "\n\n".join(transcript_parts)
    valid_indices = ", ".join(str(int(c["chunk_index"])) for c in chunks)

    prompt = f"""
You are extracting structured knowledge from ONE educational video transcript.

GROUNDING IS STRICT AND MUST FAIL CLOSED:
- Use ONLY the transcript below.
- Never use outside knowledge.
- Every returned item MUST cite one or more exact CHUNK numbers.
- CHUNK numbers are the database's zero-based chunk_index values.
- Valid chunk numbers for this transcript are: {valid_indices}
- Copy evidence_chunk_indices EXACTLY from the [CHUNK N] labels.
- Do NOT convert them to 1-based numbering.
- Do NOT invent or modify chunk numbers.
- If you cannot support an item with an exact supplied chunk, omit it.
- Do not invent timestamps; the backend calculates timestamps from evidence.
- Keep descriptions concise and supported by the transcript.
- Do not answer questions. Extract knowledge only.

Return:
1. topics: major subject areas covered by the video.
2. concepts: important concepts with definitions supported by the transcript.
3. key_points: important takeaways explicitly supported by the transcript.
4. structure: chronological sections of the video.

Avoid duplicates and avoid merely copying one sentence as an item.

TRANSCRIPT:

{transcript}
"""

    try:
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
                        response_schema=KNOWLEDGE_SCHEMA,
                    ),
                )
                break
            except Exception as retry_exc:
                if not _is_retryable_gemini_error(retry_exc) or attempt == max_attempts - 1:
                    raise
                delay = _retry_delay(attempt)
                print(f"[INX] Gemini knowledge retry {attempt + 1}/{max_attempts - 1} in {delay}s")
                time.sleep(delay)

        result = _extract_json(response)
        return _validate(result, chunks)

    except LLMProcessingError:
        raise
    except Exception as exc:
        print(f"[INX] Gemini error: {type(exc).__name__}: {exc}")
        error_text = str(exc)

        if "401" in error_text or "API key" in error_text:
            message = "Gemini rejected the API key. Check GEMINI_API_KEY in backend/.env."
        elif "429" in error_text or "quota" in error_text.lower():
            message = "Gemini Free Tier quota/rate limit was reached. Check Google AI Studio → Rate Limit/Usage."
        elif "404" in error_text or "not found" in error_text.lower():
            message = f"The configured Gemini model '{model}' was not found or is not available to this API project."
        elif "403" in error_text or "permission" in error_text.lower():
            message = "Gemini denied access to this API key/project. Check the Google AI Studio project and API key."
        else:
            message = f"Gemini processing failed. Check the Flask terminal for the technical error: {error_text[:500]}"

        raise LLMProcessingError(message) from exc
