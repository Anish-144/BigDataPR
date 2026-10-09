# Runbook: prompt injection

## What is detected
Rule SEC-004 matches prompt-injection indicators in user input and in retrieved documents, for example
"ignore previous instructions", "you are now in developer mode", "reveal the system prompt", or
"send all records to <email or URL>". The matches are heuristic: a finding means "investigate", not
"attack confirmed".

## Defence in depth
1. Retrieved documents and tool results are treated as untrusted data; instructions inside them are never executed.
2. Tool allowlists (SEC-001) and prohibited actions (SEC-002) block the tool calls an injection asks for.
3. Each finding is linked to the span (retrieval or input guard) that contained the indicator.

## Recommended actions (human-approved)
- Remove or quarantine poisoned documents from the knowledge base (KB-018 and KB-019 in the synthetic corpus).
- Keep indicator rules precise. Rule v1 matched benign advice ("send data to unknown addresses") and produced
  false positives until v2 required an explicit email or URL destination.
