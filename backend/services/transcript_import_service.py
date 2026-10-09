"""Manual transcript import for INX.

Used when YouTube blocks automatic retrieval. Accepts:

* SRT / WebVTT files (exact timestamps)
* YouTube "Show transcript" copy-paste, e.g. ``0:05`` on one line and the
  caption text on the next, or ``0:05 caption text`` on one line (exact timestamps)
* Plain text with no timestamps (timestamps are ESTIMATED from word count and
  the result is flagged so the UI can say so)

Returns the same segment shape the rest of INX already uses:
    {"start": float, "duration": float, "text": str}
"""
import re

MAX_IMPORT_CHARS = 2_000_000
ESTIMATED_WORDS_PER_SECOND = 2.5

_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE_RE = re.compile(rf"(?P<s>{_TS})\s*-->\s*(?P<e>{_TS})")
_LINE_TS_RE = re.compile(rf"^\s*\[?\(?(?P<ts>{_TS})\)?\]?\s*[-–—:]?\s*(?P<rest>.*)$")
_TAG_RE = re.compile(r"<[^>]+>")


class TranscriptImportError(Exception):
    """Expected user-facing error while importing a transcript."""


def _to_seconds(hours, minutes, seconds, millis):
    value = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
    if millis:
        value += int(millis.ljust(3, "0")[:3]) / 1000.0
    return float(value)


def _clean(text):
    text = _TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&gt;", ">").replace("&lt;", "<")
    return " ".join(text.split())


def _finish(segments, estimated=False):
    """Fill missing durations, drop duplicates, validate."""
    cleaned = []
    for seg in segments:
        text = _clean(seg["text"])
        if not text:
            continue
        # YouTube auto-captions repeat rolling lines in VTT; drop exact repeats.
        if cleaned and cleaned[-1]["text"] == text:
            cleaned[-1]["duration"] = max(
                cleaned[-1]["duration"],
                seg["start"] + seg["duration"] - cleaned[-1]["start"],
            )
            continue
        cleaned.append({"start": float(seg["start"]), "duration": float(seg["duration"]), "text": text})

    if not cleaned:
        raise TranscriptImportError("No usable transcript text was found in what you provided.")

    cleaned.sort(key=lambda s: s["start"])
    for i, seg in enumerate(cleaned):
        if seg["duration"] <= 0:
            if i + 1 < len(cleaned):
                seg["duration"] = max(0.5, cleaned[i + 1]["start"] - seg["start"])
            else:
                seg["duration"] = max(2.0, len(seg["text"].split()) / ESTIMATED_WORDS_PER_SECOND)
    return cleaned, estimated


def _parse_cues(text):
    """SRT / WebVTT."""
    segments = []
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        for idx, line in enumerate(lines):
            m = _CUE_RE.search(line)
            if not m:
                continue
            start = _to_seconds(*re.match(_TS, m.group("s")).groups())
            end = _to_seconds(*re.match(_TS, m.group("e")).groups())
            body = " ".join(lines[idx + 1:])
            segments.append({"start": start, "duration": max(0.0, end - start), "text": body})
            break
    return segments


def _parse_timestamped_lines(lines):
    """'0:05' / '0:05 text' / '[00:05] text' style transcripts."""
    segments = []
    current = None
    for line in lines:
        m = _LINE_TS_RE.match(line)
        if m:
            if current:
                segments.append(current)
            parts = re.match(_TS, m.group("ts")).groups()
            current = {"start": _to_seconds(*parts), "duration": 0.0, "text": m.group("rest")}
        elif current is not None and line.strip():
            current["text"] = f"{current['text']} {line.strip()}".strip()
    if current:
        segments.append(current)
    return segments


def _parse_plain(text):
    """No timestamps: split into short segments and ESTIMATE timing."""
    flat = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", flat)
    segments, buf, clock = [], [], 0.0

    def flush():
        nonlocal buf, clock
        if not buf:
            return
        seg_text = " ".join(buf)
        dur = max(1.0, len(seg_text.split()) / ESTIMATED_WORDS_PER_SECOND)
        segments.append({"start": round(clock, 3), "duration": round(dur, 3), "text": seg_text})
        clock += dur
        buf = []

    for sentence in sentences:
        buf.append(sentence)
        if sum(len(s.split()) for s in buf) >= 18:
            flush()
    flush()
    return segments


def parse_manual_transcript(raw):
    """Return (segments, info) where info = {"format": str, "timestamps_estimated": bool}."""
    if not isinstance(raw, str) or not raw.strip():
        raise TranscriptImportError("The transcript text is empty.")
    if len(raw) > MAX_IMPORT_CHARS:
        raise TranscriptImportError("That transcript is too large to import (limit about 2 MB of text).")

    text = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")

    if _CUE_RE.search(text):
        segments, estimated = _finish(_parse_cues(text))
        return segments, {"format": "srt/vtt", "timestamps_estimated": False}

    lines = [ln for ln in text.split("\n") if ln.strip()]
    ts_lines = [ln for ln in lines if _LINE_TS_RE.match(ln)]
    # Treat as a timestamped paste only if timestamps are clearly the structure.
    if len(ts_lines) >= 3 and len(ts_lines) >= 0.15 * len(lines):
        parsed = _parse_timestamped_lines(lines)
        if len(parsed) >= 2:
            segments, _ = _finish(parsed)
            return segments, {"format": "timestamped text", "timestamps_estimated": False}

    segments, _ = _finish(_parse_plain(text), estimated=True)
    return segments, {"format": "plain text", "timestamps_estimated": True}
