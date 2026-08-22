# Interpretation Working Draft is a structured turn list

Interpretation generate stores a turn list on the Working Draft (idea, Grilling Question clusters with preamble, Account replies), not `narrative.text`. Cluster Send is `{ expected_version, answers }` (`option` xor `other` per question). The trailer is `{ exhausted, cards: [], questions: [{ text, options }] }`; streamed prose is the cluster preamble. `exhausted: true` requires empty `questions`. Parse failure still mutates nothing (ADR 0024). PATCH of interpretation replies may change Account turns only; saving an earlier reply truncates later turns. Decomposition generate and Card upserts are unchanged.

**Considered options:** keep `Account:` prose as source of truth plus a latest `questions` array; ephemeral options in SSE only; format answers into `message`.

**Why:** The Account-facing step is questions with Grilling Options. Two sources of truth (prose blob and structured questions) would drift. Confirm and Context Projection need the full grilling, not only the latest cluster.
