# Decomposition problem and research-question Cards come from the confirmed Idea Frame

When `idea_decomposition` generate runs after interpretation Confirm, the problem and research-question Card bodies are taken from the confirmed Idea Frame. Intent is not copied into Cards. Constraint and open-question Cards are taken from Account turns on the interpretation transcript (idea, answers, notes), not from unanswered Grilling Questions or model preamble. Those kinds remain owned by `idea_decomposition` (ADR 0015); the frame is not a Card and is not confirmed as Cards.

**Considered options:** let decomposition rewrite problem/RQ from the full transcript; project only the frame and drop turns.

**Why:** The Account Confirms the restatement they saw. Transcript-only rewrite can contradict that frame. Constraint and open-question Cards still need Account turns; unanswered Grilling Questions are not Card sources. Extends ADR 0015 and ADR 0018.
