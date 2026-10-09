# Runbook: repeated tool calls, loops and tool-call budgets

## Signal
`max_consecutive_same_tool` counts identical consecutive tool calls in one run; five or more is flagged as a
suspected loop. The policy engine also enforces `max_tool_calls` per agent (rule SEC-008): once the budget is
exceeded the next call is blocked and the run fails with `tool_budget_exceeded`.

## Likely causes
- The agent re-plans after an ambiguous tool result and calls the same tool with the same arguments again.
- A prompt change that encourages "verify again" behaviour without a stopping condition.
- Tool results that are not added back to the agent's context, so the agent keeps asking.

## Recommended actions (human-approved)
- Add an explicit stopping rule to the prompt and pass previous tool results back to the model.
- De-duplicate identical tool calls inside a run (cache the first result).
- Keep the tool-call budget as a safety net; never remove it to "fix" loops.
