import re

import numpy as np


class CorpusRetriever:
    def __init__(self, corpus, model_path, top_n=10, score_threshold=0.60):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(
                "无法加载 sentence-transformers，请检查 torch/transformers/"
                "optree 依赖是否完整"
            ) from exc
        self.model = SentenceTransformer(str(model_path))
        self.top_n = top_n
        self.score_threshold = score_threshold
        self.sentence_records = self._split_sentences(corpus)
        self.sentences = [item["content"] for item in self.sentence_records]
        self.sent_embeddings = self.model.encode(self.sentences, convert_to_numpy=True) if self.sentences else np.array([])
        self.sent_embeddings = self._normalize_embeddings(self.sent_embeddings)

    def retrieve(self, target_entity):
        return "\n".join(
            hit["sentence"]
            for hit in self.retrieve_with_details(target_entity)
        )

    def retrieve_with_details(self, target_entity):
        if not self.sentences:
            return []
        direct_indices = [
            index
            for index, sentence in enumerate(self.sentences)
            if target_entity and target_entity in sentence
        ][:self.top_n]
        if len(direct_indices) >= self.top_n:
            return self._build_hits(direct_indices, None, set(direct_indices))

        entity_emb = self._normalize_embeddings(self.model.encode([target_entity], convert_to_numpy=True))
        similarities = np.dot(self.sent_embeddings, entity_emb.T).flatten()
        if similarities.size == 0:
            return self._build_hits(direct_indices, None, set(direct_indices))
        if not direct_indices and np.max(similarities) < self.score_threshold:
            return []

        semantic_indices = [
            index
            for index in np.argsort(similarities)[::-1]
            if similarities[index] >= self.score_threshold and index not in direct_indices
        ]
        top_indices = (direct_indices + semantic_indices)[:self.top_n]
        return self._build_hits(
            top_indices,
            similarities,
            set(direct_indices),
        )

    def export_segments(self):
        return [dict(item) for item in self.sentence_records]

    def _split_sentences(self, corpus):
        records = []
        for match in re.finditer(r"[^。！？；\n]+", corpus):
            raw = match.group(0)
            content = raw.strip()
            if len(content) <= 5:
                continue
            leading = len(raw) - len(raw.lstrip())
            start = match.start() + leading
            records.append(
                {
                    "index": len(records),
                    "content": content,
                    "start_offset": start,
                    "end_offset": start + len(content),
                }
            )
        return records

    def _build_hits(self, indices, similarities, direct_indices):
        hits = []
        for index in indices:
            direct = index in direct_indices
            score = 1.0 if direct else float(similarities[index])
            hits.append(
                {
                    "sentence_index": index,
                    "sentence": self.sentences[index],
                    "score": score,
                    "match_type": "direct" if direct else "semantic",
                }
            )
        return hits

    def _normalize_embeddings(self, embeddings):
        if embeddings.size == 0:
            return embeddings
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms
