# Runbook: malformed or invalid structured output

## Signal
Final answers must be JSON that validates against ANSWER_SCHEMA (the `schema_validity` evaluator). An invalid
output triggers one repair call: an extra model call and a retry. If the repair also fails, the run fails with
`error_category = malformed_response`.

## Likely causes
Output truncated at the token limit, prompt changes that encourage free-form prose, or tool results pasted
verbatim into the answer.

## Recommended actions (human-approved)
- Use the model provider's structured or constrained output features where available.
- Keep the output token limit comfortably above the expected answer size.
- Track schema validity per version; a drop is an early warning of a prompt regression.
