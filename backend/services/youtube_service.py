import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi


class YouTubeProcessingError(Exception):
    """Expected user-facing error while processing a YouTube video."""


class YouTubeBlockedError(YouTubeProcessingError):
    """YouTube is blocking automated requests from this IP (CAPTCHA / IpBlocked).

    The UI uses this to offer manual transcript import instead of retrying.
    """


# Circuit breaker: once YouTube blocks this IP, stop sending it more requests
# for a while. Hammering a blocked IP only extends the block.
BLOCK_COOLDOWN_SECONDS = int(os.environ.get("YOUTUBE_BLOCK_COOLDOWN_SECONDS", "900"))
_blocked_until = 0.0

_BLOCK_MARKERS = (
    "unusual traffic", "captcha", "ipblocked", "requestblocked", "ip has been blocked",
    "rate-limiting this ip", "could not parse the watch page", "sign in to confirm",
)


def _is_block_error(exc):
    haystack = f"{type(exc).__name__} {exc}".lower()
    return any(marker in haystack for marker in _BLOCK_MARKERS)


def _blocked_message():
    return (
        "YouTube is blocking automatic transcript requests from this network right now. "
        "You can import the transcript manually instead."
    )


def extract_video_id(url):
    if not isinstance(url, str) or not url.strip():
        raise YouTubeProcessingError("Please enter a YouTube URL.")

    value = url.strip()
    parsed = urlparse(value)
    host = parsed.netloc.lower().split(":")[0]
    path = parsed.path

    video_id = None

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif path.startswith("/embed/"):
            video_id = path.split("/embed/", 1)[1].split("/")[0]
        elif path.startswith("/shorts/"):
            video_id = path.split("/shorts/", 1)[1].split("/")[0]
        elif path.startswith("/live/"):
            video_id = path.split("/live/", 1)[1].split("/")[0]

    elif host == "youtu.be":
        video_id = path.strip("/").split("/")[0]

    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise YouTubeProcessingError(
            "Unsupported or invalid YouTube URL. Please provide a valid YouTube video URL."
        )

    return video_id


def _normalize_segments(segments):
    normalized = []

    for item in segments:
        if hasattr(item, "text"):
            text = item.text
            start = item.start
            duration = item.duration
        else:
            text = item.get("text", "")
            start = item.get("start", 0)
            duration = item.get("duration", 0)

        text = " ".join(str(text).split())
        if not text:
            continue

        normalized.append(
            {
                "start": float(start or 0),
                "duration": float(duration or 0),
                "text": text,
            }
        )

    if not normalized:
        raise YouTubeProcessingError(
            "The transcript provider returned an empty transcript."
        )

    return normalized


def _bridge_path():
    return Path(__file__).resolve().parents[1] / "transcript_bridge" / "get_transcript.mjs"


def _node_path():
    return os.environ.get("NODE_EXECUTABLE", "node")


def _fetch_live_primary(video_id):
    """Fast live provider: Node get-youtube-transcript with PoToken-aware acquisition."""
    script = _bridge_path()

    if not script.exists():
        raise RuntimeError("Live transcript bridge is missing.")

    try:
        completed = subprocess.run(
            [_node_path(), str(script), video_id],
            cwd=str(script.parent),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Node.js was not found. Install Node.js LTS and run npm install "
            "inside backend\\transcript_bridge."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The live transcript provider timed out after 20 seconds.") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        raise RuntimeError(detail[-4000:] if detail else "Live transcript provider failed.")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Live transcript provider returned invalid JSON.") from exc

    segments = _normalize_segments(payload.get("segments", []))
    return segments


def _fetch_python_fallback(video_id):
    api = YouTubeTranscriptApi()
    result = api.fetch(video_id)
    snippets = getattr(result, "snippets", result)
    return _normalize_segments(snippets)


def _friendly_error(exc):
    name = type(exc).__name__
    raw = str(exc).strip().lower()

    if "transcriptsdisabled" in name.lower() or "transcriptdisabled" in name.lower():
        return "This video has captions/transcripts disabled."

    if "novideo" in raw or "video unavailable" in raw or name == "VideoUnavailable":
        return "This YouTube video is unavailable or not public."

    if "no transcript" in raw or "notranslat" in raw:
        return "No usable transcript was found for this video."

    if "potoken" in raw:
        return (
            "YouTube requires an additional caption verification token for this video. "
            "The live provider could not obtain it."
        )

    if "429" in raw or "too many requests" in raw:
        return "YouTube temporarily rate-limited the transcript request."

    if "502" in raw or "bad gateway" in raw or "503" in raw:
        return "YouTube temporarily returned a server error while retrieving captions."

    return "We could not retrieve a usable live transcript from YouTube."


def get_transcript(video_id):
    """
    Retrieve a live transcript quickly.

    Primary provider:   Node get-youtube-transcript
    Fallback provider:  youtube-transcript-api (kept as-is)

    If YouTube reports an IP block, we try the Python fallback ONCE (no retry
    ladder), then trip a cooldown so further requests are not sent. Callers get
    YouTubeBlockedError so the UI can offer manual transcript import.
    """
    global _blocked_until

    remaining = _blocked_until - time.time()
    if remaining > 0:
        print(f"[INX] YouTube block cooldown active ({int(remaining)}s left); skipping live request.")
        raise YouTubeBlockedError(_blocked_message())

    primary_error = None
    blocked = False

    print(f"[INX] Live transcript: trying primary provider for {video_id}...")
    started = time.perf_counter()

    try:
        segments = _fetch_live_primary(video_id)
        elapsed = time.perf_counter() - started
        print(
            f"[INX] Live transcript succeeded via primary provider: "
            f"{len(segments)} segments in {elapsed:.2f}s."
        )
        return segments
    except Exception as exc:
        primary_error = exc
        blocked = _is_block_error(exc)
        print(f"[INX] Primary live transcript provider failed: {type(exc).__name__}: {exc}")

    # If blocked, one fallback attempt only. Otherwise the original short ladder.
    attempts = ((1, 0),) if blocked else ((1, 0), (2, 2))
    for attempt, delay in attempts:
        if delay:
            time.sleep(delay)

        try:
            print(f"[INX] Fallback transcript attempt {attempt}/{len(attempts)}...")
            segments = _fetch_python_fallback(video_id)
            print(f"[INX] Live transcript succeeded via Python fallback: {len(segments)} segments.")
            return segments
        except Exception as exc:
            raw = str(exc).lower()
            if _is_block_error(exc):
                blocked = True
                break
            transient = any(
                marker in raw
                for marker in ("502", "bad gateway", "503", "service unavailable")
            )
            print(f"[INX] Fallback transcript attempt {attempt} failed: {type(exc).__name__}: {exc}")
            if not transient:
                break

    if blocked:
        _blocked_until = time.time() + BLOCK_COOLDOWN_SECONDS
        print(f"[INX] YouTube block detected. Pausing live requests for {BLOCK_COOLDOWN_SECONDS}s.")
        raise YouTubeBlockedError(_blocked_message())

    detail = _friendly_error(primary_error) if primary_error else "Transcript retrieval failed."
    raise YouTubeProcessingError(detail)
