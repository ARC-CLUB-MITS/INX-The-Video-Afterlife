from services.retrieval_service import _keyword_score


def test_keyword_exact_phrase():
    assert _keyword_score("sigmoid function", "The sigmoid function squishes values") > 0.5


def test_keyword_unrelated():
    assert _keyword_score("sigmoid function", "A discussion about database indexes") < 0.5


if __name__ == "__main__":
    test_keyword_exact_phrase()
    test_keyword_unrelated()
    print("Retrieval tests passed.")
