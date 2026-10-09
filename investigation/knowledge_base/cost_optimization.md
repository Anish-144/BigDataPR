# Runbook: cost and token efficiency

## Principle
Judge cost per SUCCESSFUL task, not per request. A cheaper model that fails more often can cost more per
success. In AgentShield all monetary values are ESTIMATES from config/pricing.yaml (illustrative local prices
for mock models).

## Where tokens go
- Input tokens: system prompt, retrieved context (top_k x chunk size), tool results and conversation history.
- Output tokens: answer length, verbose reasoning, and repair calls after malformed output.
- Extra calls: retries, re-planning after tool errors, and loops.

## Levers (human-approved)
- Reduce retrieved context only while Recall@K holds (see the retrieval quality runbook).
- Remove retry and repair sources (tool errors, malformed output): every retry is a paid model call.
- Cache stable prompt prefixes where the provider supports prompt caching.
- Route easy tasks to a smaller model and keep hard tasks on the larger one; verify with the regression gate.
- Shorten verbose prompts and ask for concise answers.
