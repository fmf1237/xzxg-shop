"""小规模内存向量检索。Mock 编码器只验证协议，不代表语义能力。"""

import hashlib
from math import isfinite, sqrt
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    kind: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        ...


def product_text(product):
    return " ".join([product["name"], product["category"], product["brand"], *product["selling_points"]])


def normalize(vector):
    if not vector or any(not isfinite(float(value)) for value in vector):
        raise ValueError("向量为空或含非有限数")
    length = sqrt(sum(float(value) ** 2 for value in vector))
    if length == 0:
        raise ValueError("零向量无法归一化")
    return [float(value) / length for value in vector]


def cosine(left, right):
    if len(left) != len(right):
        raise ValueError("向量维度不一致")
    a, b = normalize(left), normalize(right)
    return sum(x * y for x, y in zip(a, b))


class MockEmbedder:
    """字符哈希桶，确定性且离线；没有训练，不具备真实语义泛化。"""

    kind = "mock_lexical_hash"

    def __init__(self, dimensions=64):
        self.dimensions = dimensions

    def encode(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for char in text.casefold():
                if char.isspace():
                    continue
                bucket = int.from_bytes(hashlib.sha256(char.encode("utf-8")).digest()[:4], "big") % self.dimensions
                vector[bucket] += 1
            vectors.append(vector)
        return vectors


class LocalSentenceTransformerEmbedder:
    """只接受已存在的本地模型目录；运行时不下载模型。"""

    kind = "real_local_sentence_transformer"

    def __init__(self, model_path):
        if not Path(model_path).is_dir():
            raise ValueError("真实 Embedding 模型目录不存在")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("请单独安装 sentence-transformers") from exc
        self.model = SentenceTransformer(str(model_path), local_files_only=True)

    def encode(self, texts):
        return self.model.encode(texts, convert_to_numpy=True).tolist()


class SemanticIndex:
    def __init__(self, products, embedder):
        self.products = products
        self.embedder = embedder
        vectors = embedder.encode([product_text(product) for product in products])
        if len(vectors) != len(products):
            raise ValueError("商品向量数量不匹配")
        self.vectors = [normalize(vector) for vector in vectors]
        if len({len(vector) for vector in self.vectors}) > 1:
            raise ValueError("商品向量维度不一致")

    def search(self, query, k=3):
        if k < 1:
            raise ValueError("k 必须是正整数")
        query_vectors = self.embedder.encode([query])
        if len(query_vectors) != 1:
            raise ValueError("查询向量数量不匹配")
        query_vector = normalize(query_vectors[0])
        if self.vectors and len(query_vector) != len(self.vectors[0]):
            raise ValueError("查询向量维度不一致")
        results = [
            {"id": product["id"], "score": sum(x * y for x, y in zip(query_vector, vector))}
            for product, vector in zip(self.products, self.vectors)
        ]
        return sorted(results, key=lambda item: (-item["score"], item["id"]))[:k]
