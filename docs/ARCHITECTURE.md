# Architecture — Step 2

```text
React
  |
  | POST /api/videos/process
  v
Flask
  |
  +--> Validate YouTube URL
  |
  +--> Extract 11-character video ID
  |
  +--> youtube-transcript-api
  |       |
  |       +--> timestamp
  |       +--> text
  |
  +--> Normalize transcript
  |
  +--> MySQL
          |
          +--> videos
          +--> transcript_segments
```

The application never downloads the YouTube video itself.
