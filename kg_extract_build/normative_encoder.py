"""规范向量编码器：冻结 encoder_profile，查询与文档编码一致。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .normative import stable_hash


@dataclass(frozen=True)
class EncoderProfile:
    embedding_model_key: str
    embedding_model_revision: str
    embedding_dimension: int
    query_prefix: str = ""
    document_prefix: str = ""
    pooling: str = "mean"
    normalize: bool = True
    max_input_tokens: int = 128


def build_encoder_profile_hash(profile: EncoderProfile) -> str:
    return stable_hash(
        {
            "model_key": profile.embedding_model_key,
            "model_revision": profile.embedding_model_revision,
            "dimension": profile.embedding_dimension,
            "query_prefix": profile.query_prefix,
            "document_prefix": profile.document_prefix,
            "pooling": profile.pooling,
            "normalize": profile.normalize,
            "max_input_tokens": profile.max_input_tokens,
        }
    )


def model_revision(model_path) -> str:
    path = Path(str(model_path))
    if not path.exists():
        return hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    digest = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file())
    for file_path in files:
        digest.update(str(file_path).encode("utf-8"))
        try:
            digest.update(file_path.read_bytes()[:4096])
        except OSError:
            pass
    return digest.hexdigest()


def _encode(model, texts, prefix, normalize):
    texts = [f"{prefix}{text}" if prefix else text for text in texts]
    vectors = model.encode(texts, convert_to_numpy=True)
    if normalize:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
    return vectors


class NormativeEncoder:
    def __init__(self, model_path, profile: EncoderProfile):
        self._profile = profile
        self._model = None
        self._model_path = model_path

    def _lazy(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:
                raise RuntimeError(
                    "无法加载 sentence-transformers，请检查依赖"
                ) from exc
            self._model = SentenceTransformer(str(self._model_path))
        return self._model

    def encode_documents(self, texts):
        return _encode(self._lazy(), texts, self._profile.document_prefix, self._profile.normalize)

    def encode_query(self, text):
        return _encode(self._lazy(), [text], self._profile.query_prefix, self._profile.normalize)[0]

    def tokenize(self, text):
        tokenizer = getattr(self._lazy(), "tokenize", None)
        if tokenizer is None:
            return str(text).split()
        return tokenizer(text)

    def close(self):
        self._model = None
