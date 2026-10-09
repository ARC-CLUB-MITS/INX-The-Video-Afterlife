"""Offline regression runner for INX: The Video Afterlife.

Run from backend with the project virtual environment activated:
    python run_tests.py

These tests do not call YouTube, Gemini, MySQL, or FAISS network services.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check_python_syntax():
    files = [
        path for path in ROOT.rglob('*.py')
        if '.venv' not in path.parts
        and '__pycache__' not in path.parts
    ]    
    for path in files:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    return len(files)


def check_static_contracts():
    retrieval = (ROOT / 'services' / 'retrieval_service.py').read_text(encoding='utf-8')
    embedding = (ROOT / 'services' / 'embedding_service.py').read_text(encoding='utf-8')
    qa = (ROOT / 'services' / 'qa_service.py').read_text(encoding='utf-8')
    routes = (ROOT / 'routes' / 'video_routes.py').read_text(encoding='utf-8')

    assert '_keyword_score' in retrieval
    assert 'IndexFlatIP' in embedding
    assert 'REFUSAL_TEXT' in qa
    assert '_clean_citations' in qa
    assert 'fallback_evidence' in qa
    assert 'GEMINI_MAX_RETRIES' in qa
    assert '_call_ollama' in qa and 'QA_PROVIDER' in qa
    llm = (ROOT / 'services' / 'llm_service.py').read_text(encoding='utf-8')
    assert 'extract_knowledge_extractive' in llm
    assert 'knowledge_mode=knowledge_mode' in routes
    assert 'search' in routes and 'index' in routes


def check_retrieval_unit_tests():
    from test_retrieval import test_keyword_exact_phrase, test_keyword_unrelated
    test_keyword_exact_phrase()
    test_keyword_unrelated()


def check_grounding_unit_tests():
    from services.llm_service import _validate
    chunks = [
        {'chunk_index': 0, 'start_time': 0, 'end_time': 10, 'text': 'first'},
        {'chunk_index': 1, 'start_time': 10, 'end_time': 20, 'text': 'second'},
    ]
    safe = {
        'topics': [{'title': 'T', 'description': 'D', 'evidence_chunk_indices': [1]}],
        'concepts': [], 'key_points': [], 'structure': [],
    }
    assert _validate(safe, chunks)['topics'][0]['evidence_chunk_indices'] == [1]
    unsafe = {
        'topics': [{'title': 'T', 'description': 'D', 'evidence_chunk_indices': [999]}],
        'concepts': [], 'key_points': [], 'structure': [],
    }
    assert _validate(unsafe, chunks)['topics'] == []


def check_qa_guard_tests():
    import os
    from services.qa_service import answer_question, _retrieval_guard, _clean_citations, _is_retryable_gemini_error, _safe_gemini_fallback, REFUSAL_TEXT
    chunks = [{'chunk_index': 5, 'score': 0.72, 'start_time': 0, 'end_time': 10, 'text': 'neural network has 784 input neurons'}]
    ok, _ = _retrieval_guard('why 784 input neurons', chunks)
    assert ok
    ok, message = _retrieval_guard('who won a football match', chunks)
    assert not ok and message == REFUSAL_TEXT
    assert _clean_citations([5, 999, '5'], [5]) == [5]
    assert _is_retryable_gemini_error(Exception("quota exhausted"))

    # Exercise the Ollama provider branch without requiring a live local model.
    import services.qa_service as qa_module
    old_provider = os.environ.get('QA_PROVIDER')
    old_ollama = qa_module._call_ollama
    os.environ['QA_PROVIDER'] = 'ollama'
    qa_module._call_ollama = lambda prompt, **kw: ('{\"answer\":\"The transcript says 784 input neurons.\",\"supported\":true,\"evidence_chunk_indices\":[5]}', 'test-model')
    try:
        ollama_result = answer_question('why 784 input neurons', chunks)
        assert ollama_result['grounding']['status'] == 'grounded'
        assert ollama_result['grounding']['provider'] == 'ollama'
        assert ollama_result['sources'][0]['chunk_index'] == 5
    finally:
        qa_module._call_ollama = old_ollama
        if old_provider is None:
            os.environ.pop('QA_PROVIDER', None)
        else:
            os.environ['QA_PROVIDER'] = old_provider

    fallback = _safe_gemini_fallback([{'chunk_index': 5, 'score': 0.72, 'start_time': 0, 'end_time': 10, 'text': 'verified source'}], 'test')
    assert fallback['grounding']['status'] == 'fallback_evidence'
    assert fallback['sources'][0]['chunk_index'] == 5
    old_key = os.environ.pop('GEMINI_API_KEY', None)
    old_provider = os.environ.get('QA_PROVIDER')
    os.environ['QA_PROVIDER'] = 'gemini'
    try:
        direct = answer_question('why 784 input neurons', chunks)
        assert direct['grounding']['status'] == 'fallback_evidence'
        assert direct['sources'][0]['chunk_index'] == 5
    finally:
        if old_key is not None:
            os.environ['GEMINI_API_KEY'] = old_key
        if old_provider is None:
            os.environ.pop('QA_PROVIDER', None)
        else:
            os.environ['QA_PROVIDER'] = old_provider


def check_extractive_knowledge_fallback():
    from services.llm_service import extract_knowledge_extractive
    chunks = [
        {'chunk_index': 0, 'start_time': 0, 'end_time': 10, 'text': 'A neural network contains neurons and layers. Neural networks learn weights from examples.'},
        {'chunk_index': 1, 'start_time': 10, 'end_time': 20, 'text': 'The input layer receives data. The hidden layer combines inputs using weights and activation functions.'},
        {'chunk_index': 2, 'start_time': 20, 'end_time': 30, 'text': 'Weights change during training. Neural networks use training examples to improve predictions.'},
    ]
    result = extract_knowledge_extractive(chunks)
    assert result['structure'] and result['key_points']
    valid = {c['chunk_index'] for c in chunks}
    for category in ('topics', 'concepts', 'key_points', 'structure'):
        for item in result[category]:
            assert item['evidence_chunk_indices']
            assert set(item['evidence_chunk_indices']).issubset(valid)


def check_manual_import_and_block_cooldown():
    import test_transcript_import as t
    for name in dir(t):
        if name.startswith('test_'):
            getattr(t, name)()


def main():
    count = check_python_syntax()
    check_static_contracts()
    check_retrieval_unit_tests()
    check_grounding_unit_tests()
    check_qa_guard_tests()
    check_extractive_knowledge_fallback()
    check_manual_import_and_block_cooldown()
    print(f'PASS: Python syntax ({count} files)')
    print('PASS: retrieval keyword tests')
    print('PASS: knowledge evidence validation')
    print('PASS: Q&A grounding guard, provider selection, and citation validation')
    print('PASS: extractive knowledge fallback and evidence validation')
    print('ALL OFFLINE REGRESSION TESTS PASSED')


if __name__ == '__main__':
    main()