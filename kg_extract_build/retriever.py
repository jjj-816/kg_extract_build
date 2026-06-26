import re

import numpy as np
from sentence_transformers import SentenceTransformer


class CorpusRetriever:
    def __init__(self, corpus, model_path, top_n=10, score_threshold=0.60):
        self.model = SentenceTransformer(str(model_path))
        self.top_n = top_n
        self.score_threshold = score_threshold
        self.sentences = [s.strip() for s in re.split(r"[。！？；\n]", corpus) if len(s.strip()) > 5]
        self.sent_embeddings = self.model.encode(self.sentences, convert_to_numpy=True) if self.sentences else np.array([])
        self.sent_embeddings = self._normalize_embeddings(self.sent_embeddings)

    def retrieve(self, target_entity):
        if not self.sentences:
            return ""
        direct_indices = [
            index
            for index, sentence in enumerate(self.sentences)
            if target_entity and target_entity in sentence
        ][:self.top_n]
        if len(direct_indices) >= self.top_n:
            return "\n".join(self.sentences[i] for i in direct_indices)

        entity_emb = self._normalize_embeddings(self.model.encode([target_entity], convert_to_numpy=True))
        similarities = np.dot(self.sent_embeddings, entity_emb.T).flatten()
        if similarities.size == 0:
            return "\n".join(self.sentences[i] for i in direct_indices)
        if not direct_indices and np.max(similarities) < self.score_threshold:
            return ""

        semantic_indices = [
            index
            for index in np.argsort(similarities)[::-1]
            if similarities[index] >= self.score_threshold and index not in direct_indices
        ]
        top_indices = (direct_indices + semantic_indices)[:self.top_n]
        return "\n".join(self.sentences[i] for i in top_indices)

    def _normalize_embeddings(self, embeddings):
        if embeddings.size == 0:
            return embeddings
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms
