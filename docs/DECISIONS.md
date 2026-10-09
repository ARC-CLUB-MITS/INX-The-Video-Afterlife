# Decisions — Step 2

## Transcript instead of video download

The challenge is about converting educational video content into searchable knowledge. Available captions/transcripts provide the required textual evidence while avoiding unnecessary video storage and processing.

## Preserve timestamps

Every transcript segment keeps its original start time and duration so later stages can provide source-linked answers.

## Store transcript segments separately

Segments are stored as rows instead of one large transcript so later retrieval can operate on smaller evidence units.

## Explicit error classification

YouTube failures are converted into understandable user messages. Technical exception details remain in the backend console for debugging.
