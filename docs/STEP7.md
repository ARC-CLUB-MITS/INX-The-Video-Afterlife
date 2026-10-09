# Step 7 — Video Explorer UI

Step 7 turns the working retrieval system into an explorable product surface.

## Added
- YouTube player embedded beside the knowledge explorer.
- Overview tab for structure, topics, and concepts.
- Transcript tab with local text filtering and timestamp jumping.
- Search tab backed by the existing hybrid retrieval API.
- Clickable timestamps open the video at the relevant point.
- Verified evidence remains tied to transcript chunks.
- Responsive desktop/tablet/mobile layout.

## Architecture
The UI does not become a new source of truth. Transcript and knowledge remain in MySQL; search remains backed by the Step 6 hybrid retrieval service.
