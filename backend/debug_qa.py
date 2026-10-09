"""Shows exactly why Ollama's answer was rejected. Run from the backend folder:
    python debug_qa.py
Needs Ollama running. Does NOT touch MySQL, YouTube, or your data."""
import config  # loads backend/.env
from services import qa_service

_orig = qa_service._call_ollama


def spy(prompt, **kw):
    text, model = _orig(prompt, **kw)
    print("\n===== RAW OLLAMA OUTPUT =====")
    print(text)
    print("=============================\n")
    return text, model


qa_service._call_ollama = spy

chunks = [{
    "chunk_index": 0, "start_time": 0.0, "end_time": 20.0, "score": 0.61,
    "semantic_score": 0.40, "keyword_score": 1.0,
    "text": "neural networks learn from data layers transform inputs "
            "weights are adjusted during training loss measures the error",
}]

result = qa_service.answer_question("What do weights do during training?", chunks)
print("RESULT status :", result["grounding"].get("status"))
print("RESULT reason :", result["grounding"].get("reason"))
print("ANSWER        :", result["answer"])
print("SUPPORTED     :", result["supported"])
