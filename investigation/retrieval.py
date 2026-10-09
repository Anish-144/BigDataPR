"""Local retrieval over the investigation knowledge base.

Corpus: runbooks in investigation/knowledge_base/*.md (split by "## " section),
policy rules from config/policies.yaml, and the curated SQL catalog
(question + interpretation of every named query).

Backend: TF-IDF + cosine similarity (scikit-learn) by default - deterministic,
lightweight and offline. Set RETRIEVAL_BACKEND=sentence_transformers to use
Sentence Transformers + FAISS when those optional packages are installed
(pip install sentence-transformers faiss-cpu); otherwise TF-IDF is used.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from common.config import load_policy

KB_DIR = Path(__file__).resolve().parent / "knowledge_base"


@dataclass(frozen=True)
class Passage:
    passage_id: str
    title: str
    source: str  # runbook | policy | sql_catalog
    text: str


def _runbooks() -> list[Passage]:
    out = []
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_title = text.splitlines()[0].lstrip("# ").strip()
        sections = re.split(r"\n(?=## )", text)
        for i, sec in enumerate(sections):
            head = sec.splitlines()[0].lstrip("# ").strip()
            title = doc_title if i == 0 else f"{doc_title} - {head}"
            out.append(Passage(f"kb:{path.stem}#{i}", title, "runbook", sec.strip()))
    return out


def _policy() -> list[Passage]:
    pol = load_policy()
    return [Passage(f"policy:{r['rule_id']}", f"{r['rule_id']} {r['rule_name']}", "policy",
                    f"{r['rule_id']} {r['rule_name']} ({r['severity']}, category {r['category']}): {r['description']}")
            for r in pol["rules"]]


def _sql_catalog() -> list[Passage]:
    from lakehouse.sql_catalog import load_catalog

    return [Passage(f"sql:{n}", st.tags.get("title", n), "sql_catalog",
                    f"{st.tags.get('title', '')}. {st.tags.get('question', '')} {st.tags.get('interpretation', '')}")
            for n, st in load_catalog().items()]


def build_corpus() -> list[Passage]:
    return _runbooks() + _policy() + _sql_catalog()


class Retriever:
    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self.backend = "tfidf"
        texts = [f"{p.title}. {p.text}" for p in passages]
        if os.environ.get("RETRIEVAL_BACKEND", "tfidf") == "sentence_transformers":
            try:
                import faiss  # type: ignore
                from sentence_transformers import SentenceTransformer  # type: ignore

                self.model = SentenceTransformer(os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
                emb = self.model.encode(texts, normalize_embeddings=True).astype("float32")
                self.index = faiss.IndexFlatIP(emb.shape[1])
                self.index.add(emb)
                self.backend = "sentence_transformers+faiss"
                return
            except Exception:  # optional dependency missing -> deterministic TF-IDF
                pass
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self.matrix = self.vectorizer.fit_transform(texts)

    def search(self, query: str, k: int = 4, min_score: float = 0.08) -> list[tuple[Passage, float]]:
        if self.backend.startswith("sentence"):
            q = self.model.encode([query], normalize_embeddings=True).astype("float32")
            scores, idx = self.index.search(q, k)
            pairs = [(self.passages[i], float(s)) for i, s in zip(idx[0], scores[0]) if i >= 0]
            return [(p, s) for p, s in pairs if s >= max(min_score, 0.3)]
        q = self.vectorizer.transform([query])
        scores = (self.matrix @ q.T).toarray().ravel()
        order = np.argsort(-scores)[:k]
        return [(self.passages[i], float(scores[i])) for i in order if scores[i] >= min_score]


@lru_cache(maxsize=1)
def retriever() -> Retriever:
    return Retriever(build_corpus())
