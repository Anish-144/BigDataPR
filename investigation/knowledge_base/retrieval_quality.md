# Runbook: retrieval quality and RAG regressions

## Metrics
- Recall@K: share of relevant documents found in the top K retrieved documents.
- Precision@K: share of the top K documents that are relevant.
- MRR (mean reciprocal rank): how high the first relevant document ranks.
- Citation coverage: relevant documents that are cited and were actually retrieved.
- Groundedness: share of answer tokens supported by cited document text (a lexical proxy).

## Typical regression pattern
Reducing `top_k` or changing chunking makes an agent faster and cheaper (fewer input tokens), but when the
relevant document falls outside the top K, answers become wrong. Task success then drops together with
Recall@K. RAG Helpdesk 2.1.0 (top_k 3, new chunking) shows exactly this trade-off against 2.0.0 (top_k 5).

## Recommended actions (human-approved)
- Restore a larger top_k or add a re-ranking step before reducing context size.
- Evaluate chunking changes on the fixed regression suite before release.
- Gate releases on Recall@K drop (config/thresholds.yaml, retrieval_recall_drop_pct_points).
