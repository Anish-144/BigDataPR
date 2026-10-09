"""Deterministic retrieval and grounding metrics for RAG evaluation.

All functions take document IDs (ranked) and ground-truth relevant IDs. They
are only meaningful where ground truth exists, which is the case for every
synthetic RAG task in the test lab.
"""

from __future__ import annotations

from typing import Iterable, Sequence


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    if not rel:
        return 0.0
    return len(rel & set(retrieved[:k])) / len(rel)


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    if k <= 0:
        return 0.0
    rel = set(relevant)
    return len(rel & set(retrieved[:k])) / k


def reciprocal_rank(retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    rel = set(relevant)
    for i, doc_id in enumerate(retrieved, start=1):
        if doc_id in rel:
            return 1.0 / i
    return 0.0


def mean_reciprocal_rank(results: Iterable[tuple[Sequence[str], Iterable[str]]]) -> float:
    rrs = [reciprocal_rank(r, rel) for r, rel in results]
    return sum(rrs) / len(rrs) if rrs else 0.0


def citation_coverage(citations: Sequence[str], retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    """Fraction of relevant documents that the answer cites *and* were actually retrieved.

    A citation to a document that was never retrieved is not counted (it cannot
    be grounded in the retrieved evidence).
    """
    rel = set(relevant)
    if not rel:
        return 0.0
    grounded = set(citations) & set(retrieved) & rel
    return len(grounded) / len(rel)


def unsupported_citation_rate(citations: Sequence[str], retrieved: Sequence[str]) -> float:
    """Fraction of citations pointing at documents that were not retrieved (hallucinated sources)."""
    if not citations:
        return 0.0
    return sum(1 for c in citations if c not in set(retrieved)) / len(citations)


def groundedness(answer_tokens: Iterable[str], evidence_tokens: Iterable[str]) -> float:
    """Share of content tokens in the answer that also occur in the cited evidence."""
    ans = [t for t in answer_tokens]
    if not ans:
        return 0.0
    ev = set(evidence_tokens)
    return sum(1 for t in ans if t in ev) / len(ans)
