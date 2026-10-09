import re


# Target size is deliberately moderate so later retrieval can return
# focused evidence to the LLM instead of very large transcript blocks.
TARGET_WORDS = 140
MAX_WORDS = 190
MIN_WORDS = 45
OVERLAP_WORDS = 25


def _normalize_text(text):
    text = str(text or "")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _word_count(text):
    return len(text.split())


def build_chunks(segments):
    """
    Combine timestamped transcript segments into coherent retrieval chunks.

    We preserve segment boundaries and timestamps. A chunk is never split
    in the middle of a transcript segment.
    """
    if not segments:
        return []

    cleaned = []

    for segment in segments:
        text = _normalize_text(segment.get("text", ""))
        if not text:
            continue

        cleaned.append(
            {
                "start": float(segment.get("start", 0)),
                "duration": float(segment.get("duration", 0)),
                "text": text,
            }
        )

    chunks = []
    current = []
    current_words = 0

    def flush():
        nonlocal current, current_words

        if not current:
            return

        text = " ".join(item["text"] for item in current)
        start_time = current[0]["start"]
        last = current[-1]
        end_time = last["start"] + last["duration"]

        chunks.append(
            {
                "chunk_index": len(chunks),
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "text": text,
                "word_count": _word_count(text),
                "segment_count": len(current),
            }
        )

        # Keep a small overlap from the end of the current chunk.
        overlap = []
        overlap_words = 0

        for item in reversed(current):
            item_words = _word_count(item["text"])

            if overlap_words + item_words > OVERLAP_WORDS and overlap:
                break

            overlap.insert(0, item)
            overlap_words += item_words

            if overlap_words >= OVERLAP_WORDS:
                break

        current = overlap
        current_words = overlap_words

    for segment in cleaned:
        words = _word_count(segment["text"])

        # A very long individual caption is kept intact rather than
        # cutting it arbitrarily. This preserves source evidence.
        if current and current_words + words > MAX_WORDS:
            flush()

        current.append(segment)
        current_words += words

        # Prefer a natural stopping point after reaching the target.
        if current_words >= TARGET_WORDS:
            flush()

    if current:
        flush()

    # Very small final chunks can be merged into the previous chunk when
    # doing so does not create an oversized retrieval block.
    if len(chunks) >= 2 and chunks[-1]["word_count"] < MIN_WORDS:
        previous = chunks[-2]
        last = chunks[-1]

        if previous["word_count"] + last["word_count"] <= MAX_WORDS:
            previous["text"] += " " + last["text"]
            previous["end_time"] = last["end_time"]
            previous["word_count"] = _word_count(previous["text"])
            previous["segment_count"] += last["segment_count"]
            chunks.pop()

    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index

    return chunks
