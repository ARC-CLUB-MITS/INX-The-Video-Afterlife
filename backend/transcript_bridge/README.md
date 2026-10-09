# INX Live Transcript Bridge

This small Node bridge is the primary live transcript provider for INX.

It uses `get-youtube-transcript`, which implements a current YouTube caption
acquisition path designed to handle PoToken-protected caption requests.

Install once:

```powershell
cd backend\transcript_bridge
npm install
```

Test:

```powershell
node get_transcript.mjs aircAruvnKk
```

The Python backend consumes the JSON output automatically.
