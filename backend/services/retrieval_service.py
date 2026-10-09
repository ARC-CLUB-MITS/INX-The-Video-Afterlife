"""Grounded hybrid retrieval for INX.

Semantic and keyword scores are kept in the same 0..1 scale.  MySQL transcript
chunks remain the source of truth; FAISS is used only to rank candidates.
"""
import re
from services.embedding_service import search_index, EmbeddingProcessingError

STOPWORDS = {
    "a","an","and","are","as","at","be","by","for","from","how","in","is","it","of","on","or","that","the","their","this","to","what","when","where","which","why","with","does","do","can","into","about","you","your","they","we","i","who"
}


def _tokens(text):
    words = re.findall(r"[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)?", str(text).lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _keyword_score(query, text):
    q = list(dict.fromkeys(_tokens(query)))
    if not q:
        return 0.0
    t = set(_tokens(text))
    matched = sum(1 for word in q if word in t)
    overlap = matched / len(q)
    phrase = str(query).strip().lower()
    haystack = str(text).lower()
    phrase_bonus = 0.20 if len(phrase) > 3 and phrase in haystack else 0.0
    return max(0.0, min(1.0, overlap + phrase_bonus))


def hybrid_search(video_db_id, query, chunks, top_k=5):
    query = str(query or "").strip()
    if not query:
        raise EmbeddingProcessingError("Search query cannot be empty.")

    semantic = search_index(video_db_id, query, chunks, top_k=max(len(chunks), int(top_k)))
    semantic_by_index = {int(item["chunk_index"]): item for item in semantic}
    results = []

    for chunk in chunks:
        idx = int(chunk["chunk_index"])
        semantic_item = semantic_by_index.get(idx)
        raw_semantic = float(semantic_item["score"]) if semantic_item else 0.0
        # FAISS IndexFlatIP is cosine-like here because embeddings are normalized.
        # Never shift 0 to 0.5: unrelated queries must not receive a fake baseline.
        semantic_norm = max(0.0, min(1.0, raw_semantic))
        keyword = _keyword_score(query, chunk["text"])
        hybrid = (0.65 * semantic_norm) + (0.35 * keyword)
        results.append({
            "score": max(0.0, min(1.0, hybrid)),
            "semantic_score": semantic_norm,
            "keyword_score": keyword,
            "chunk_index": idx,
            "start_time": float(chunk["start_time"]),
            "end_time": float(chunk["end_time"]),
            "text": chunk["text"],
        })

    results.sort(key=lambda item: (item["score"], item["keyword_score"], item["semantic_score"]), reverse=True)
    # Below this level the result is normally weak/noisy. Returning no result is
    # more trustworthy than presenting an unrelated passage as relevant.
    strong = [item for item in results if item["score"] >= 0.12]
    return (strong or results[:1])[: max(1, min(int(top_k), len(results)))]
