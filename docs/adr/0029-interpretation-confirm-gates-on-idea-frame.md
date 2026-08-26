# Interpretation Confirm gates on a complete Idea Frame, not closed clusters

Confirm of `idea_interpretation` is allowed when the Idea Frame’s `intent`, `problem`, and `research_question` are all non-blank. Open Grilling Question clusters stay on the transcript and do not block Confirm. Confirm does not persist in-flight Grilling Option picks. Decomposition still copies problem and research_question from the frame (ADR 0028) and may mint constraint and open-question Cards only from Account turns. A two-field frame without Intent is incomplete until the next generate.

**Considered options:** keep the ADR 0027 cluster-closed gate; persist in-form answers on Confirm; drop the trailing unanswered cluster on Confirm; grandfather frames that lack Intent.

**Why:** Shared understanding is the Idea Frame the Account sees. Requiring every cluster closed made Confirm wait on exhausted generate. Unanswered questions are history, not spec Cards. In-flight picks are generate input, not a Decision.

Supersedes ADR 0027’s Confirm gate. Extends ADR 0018 and ADR 0028.
