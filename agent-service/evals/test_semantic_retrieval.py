import json
from pathlib import Path

import pytest

from run_retrieval_eval import load_data
from semantic_retrieval import LocalSentenceTransformerEmbedder, MockEmbedder, SemanticIndex, cosine, normalize, product_text


PRODUCTS, _ = load_data()


def test_normalize_and_cosine():
    assert normalize([3, 4]) == pytest.approx([0.6, 0.8])
    assert cosine([1, 0], [0, 1]) == pytest.approx(0)
    assert cosine([2, 0], [1, 0]) == pytest.approx(1)
    with pytest.raises(ValueError):
        normalize([0, 0])
    with pytest.raises(ValueError):
        cosine([1], [1, 2])


def test_mock_index_is_deterministic_and_labeled():
    index = SemanticIndex(PRODUCTS, MockEmbedder())
    assert index.embedder.kind == "mock_lexical_hash"
    assert "迅步" in product_text(PRODUCTS[0])
    assert index.search("运动鞋", 3) == index.search("运动鞋", 3)
    assert all("id" in item and "score" in item for item in index.search("运动鞋", 3))


def test_bad_vectors_and_missing_real_model(tmp_path):
    class BadEmbedder:
        kind = "bad"

        def encode(self, texts):
            return [[0.0, 0.0] for _ in texts]

    with pytest.raises(ValueError):
        SemanticIndex(PRODUCTS, BadEmbedder())
    with pytest.raises(ValueError, match="目录不存在"):
        LocalSentenceTransformerEmbedder(tmp_path / "not-installed")
