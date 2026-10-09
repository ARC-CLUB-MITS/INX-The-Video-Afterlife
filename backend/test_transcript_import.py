"""Offline tests for manual transcript import + YouTube block cooldown."""
import time

from services.transcript_import_service import TranscriptImportError, parse_manual_transcript


def test_srt():
    raw = "1\n00:00:01,000 --> 00:00:03,500\nHello there\n\n2\n00:00:03,500 --> 00:00:06,000\nthis is <i>INX</i>\n"
    segs, info = parse_manual_transcript(raw)
    assert info["format"] == "srt/vtt" and not info["timestamps_estimated"]
    assert segs[0] == {"start": 1.0, "duration": 2.5, "text": "Hello there"}
    assert segs[1]["text"] == "this is INX"


def test_vtt_rolling_duplicates():
    raw = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nsame line\n\n00:00:02.000 --> 00:00:04.000\nsame line\n\n00:00:04.000 --> 00:00:06.000\nnext\n"
    segs, _ = parse_manual_transcript(raw)
    assert [s["text"] for s in segs] == ["same line", "next"]


def test_youtube_paste_two_line():
    raw = "0:00\nwelcome back\n0:05\nto the channel\n1:02\nlet's begin\n1:10:03\nvery late line\n"
    segs, info = parse_manual_transcript(raw)
    assert info["format"] == "timestamped text" and not info["timestamps_estimated"]
    assert [s["start"] for s in segs] == [0.0, 5.0, 62.0, 4203.0]
    assert segs[0]["duration"] == 5.0 and segs[1]["text"] == "to the channel"


def test_inline_timestamps():
    raw = "[00:00] intro words\n[00:07] more words\n[00:15] final words\n"
    segs, _ = parse_manual_transcript(raw)
    assert len(segs) == 3 and segs[1]["start"] == 7.0


def test_plain_text_is_flagged_estimated():
    raw = ("Neural networks learn from data. " * 20).strip()
    segs, info = parse_manual_transcript(raw)
    assert info["timestamps_estimated"] and segs[0]["start"] == 0.0
    assert all(b["start"] > a["start"] for a, b in zip(segs, segs[1:]))


def test_empty_rejected():
    for bad in ("", "   \n  ", None):
        try:
            parse_manual_transcript(bad)
        except TranscriptImportError:
            continue
        raise AssertionError("expected TranscriptImportError")


def test_chunks_from_import():
    from services.chunk_service import build_chunks
    raw = "\n".join(f"{i//60}:{i%60:02d}\n" + "word " * 12 for i in range(0, 300, 6))
    segs, _ = parse_manual_transcript(raw)
    chunks = build_chunks(segs)
    assert chunks and chunks[0]["start_time"] == 0.0


def test_block_cooldown_skips_network():
    from services import youtube_service as ys
    calls = []
    ys._fetch_live_primary = lambda vid: calls.append("node") or (_ for _ in ()).throw(
        RuntimeError("Could not parse the watch page (YouTube may be rate-limiting this IP)"))
    ys._fetch_python_fallback = lambda vid: calls.append("py") or (_ for _ in ()).throw(
        type("IpBlocked", (Exception,), {})("blocked"))
    ys._blocked_until = 0.0

    try:
        ys.get_transcript("aircAruvnKk")
    except ys.YouTubeBlockedError:
        pass
    else:
        raise AssertionError("expected YouTubeBlockedError")
    assert calls == ["node", "py"]          # one attempt each, no retry ladder

    try:
        ys.get_transcript("aircAruvnKk")
    except ys.YouTubeBlockedError:
        pass
    assert calls == ["node", "py"]          # cooldown: zero new requests
    assert ys._blocked_until > time.time()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)


def test_prompt_has_no_literal_example_citation():
    """Regression: the prompt example used to say [1], which small models copied."""
    from services import qa_service
    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        seen["kw"] = kw
        return '{"answer":"ok","supported":true,"evidence_chunk_indices":[0]}', "m"

    real = qa_service._call_ollama
    qa_service._call_ollama = fake
    chunks = [{"chunk_index": 0, "start_time": 0, "end_time": 5, "score": 0.9,
               "text": "weights are adjusted during training"}]
    try:
        out = qa_service.answer_question("What are weights adjusted during?", chunks)
    finally:
        qa_service._call_ollama = real
    assert '"evidence_chunk_indices": [1]' not in seen["prompt"]
    assert seen["kw"]["valid_indices"] == [0]
    assert out["supported"] and out["evidence_chunk_indices"] == [0]


def test_ollama_payload_constrains_citations_to_valid_chunks():
    """Regression: a 1.5B model kept citing [1] when only chunk 0 existed."""
    import json, urllib.request
    from services import qa_service
    sent = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"response": '{"answer":"a","supported":true,"evidence_chunk_indices":[0]}'}).encode()

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode())
        return FakeResp()

    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        qa_service._call_ollama("p", valid_indices=[0, 7])
    finally:
        urllib.request.urlopen = orig
    fmt = sent["body"]["format"]
    assert fmt["properties"]["evidence_chunk_indices"]["items"]["enum"] == [0, 7]