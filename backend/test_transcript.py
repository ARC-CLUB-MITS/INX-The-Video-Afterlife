import sys
import time

from services.youtube_service import extract_video_id, get_transcript

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=aircAruvnKk"
video_id = extract_video_id(url)

print(f"Testing LIVE transcript retrieval for: {video_id}")
started = time.perf_counter()
segments = get_transcript(video_id)
elapsed = time.perf_counter() - started

print(f"SUCCESS: {len(segments)} transcript segments retrieved in {elapsed:.2f}s.")
print("First segment:")
print(segments[0])
