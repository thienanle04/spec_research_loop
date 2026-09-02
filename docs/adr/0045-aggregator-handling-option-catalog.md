# Aggregator plants Handling Options, then phrases

Every Aggregator generate composes Judge Issues, plants catalog Handling Options on each CRITICAL and MAJOR Issue, then (only if any such Issue exists) asks the LLM to rewrite label and prose. Phrasing must not drop required rows, add targets, or invent Other. `idea_decomposition` is Other-only. Catalog templates stay if phrasing fails or is skipped. Confirm Aggregator is blocked while phrasing is in-flight; PICK and Other are not. A later successful Judge generate, or another Aggregator generate, tears down the unconfirmed working report and runs the sequence again. There is no phrase-only generate.

**Considered options:** one LLM call that both composes and invents options (rejected — empty or failed copy left CRITICAL Issues with no PICK); a second Workflow Node after Aggregator (rejected — Handling Options belong on the Aggregator Report); phrase-only retry (rejected — compose is deterministic; a second generate kind is unique in the loop).

**Why:** Coverage is a product invariant. Copy is optional polish. PICK must not wait on the LLM; Confirm must not freeze mid-phrase.
