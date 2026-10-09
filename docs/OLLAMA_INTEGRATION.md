# Ollama Q&A Integration

INX can use a locally running Ollama model for grounded question answering. The selected video's transcript remains the source of truth; Ollama is only the answer generator.

## Configure

Copy the relevant settings into `backend/.env` (keep your existing database settings and API keys):

```dotenv
QA_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:1.5b
OLLAMA_TIMEOUT_SECONDS=120
QA_MIN_RETRIEVAL_SCORE=0.58
QA_MAX_ANSWER_CHARS=1200
```

Provider choices:

- `ollama`: use local Ollama only. Recommended for demos that must not depend on Gemini quota.
- `gemini`: use Gemini only.
- `auto`: try Ollama first, then configured Gemini if Ollama fails.

Make sure `ollama list` shows the configured model and the Ollama API is reachable at `http://localhost:11434`.

## Safety behavior

- The route loads transcript chunks only for the selected YouTube video before retrieval.
- The existing retrieval guard runs before either provider is called.
- The prompt supplies only retrieved chunks and asks the model to abstain when evidence is insufficient.
- The backend validates citation indices against retrieved chunks and resolves timestamps from stored transcript data, not from model-generated timestamps.
- If the provider fails or produces an invalid response, INX returns retrieved transcript evidence rather than making up an answer.

Prompting and citation validation reduce unsupported answers but are not a mathematical proof of claim-level entailment. Test with unrelated, partially supported, and misleading questions before a live demo; the safe behavior is to abstain when evidence is insufficient.

## Test

From `backend/` with the virtual environment activated:

```powershell
python run_tests.py
```

The regression tests run offline and mock the Ollama call. Separately test the actual local API:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```
