import { getTranscript } from "get-youtube-transcript";

const videoId = process.argv[2];

if (!videoId) {
  console.error("Missing YouTube video ID.");
  process.exit(2);
}

try {
  const result = await getTranscript(videoId, { languages: ["en"] });

  const segments = Array.isArray(result?.segments)
    ? result.segments.map((segment) => ({
        start: Number(segment.start ?? 0),
        duration: Number(segment.duration ?? 0),
        text: String(segment.text ?? "").trim(),
      })).filter((segment) => segment.text)
    : [];

  if (!segments.length) {
    throw new Error("Transcript provider returned no usable segments.");
  }

  process.stdout.write(JSON.stringify({
    ok: true,
    language: result?.language ?? null,
    segments,
  }));
} catch (error) {
  console.error(error?.stack || error?.message || String(error));
  process.exit(1);
}
