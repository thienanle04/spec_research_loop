# Judge Issues, Severity floors, and disagreement without majority vote

Independent judges do not vote and do not share Prompt Views. Each Judge Run is a list of Judge Issues (closed Finding Kind + Severity floor) plus Conference criterion scores. The Aggregator is a deterministic composer: it copies Severity, groups consensus vs disagreement, derives Readiness, and may use an LLM only to phrase Handling Options. Majority vote is rejected: Gap ACCEPT cannot override Evidence `unsupported_citation`. CRITICAL Issues fail Readiness; they never un-mint a Spec Version. Confirm of a Judge or Aggregator freezes the evaluation even when CRITICAL remains. Blocking Spec Artifact export on CRITICAL is superseded by ADR 0041.

Verifier-emitted Issues (Evidence entailment → `unsupported_citation`; Gap with no supporting passage → `gap_unsupported_by_sources`) cannot be dropped or lowered by the LLM. `gap_already_addressed` is LLM-only. Generate on any Judge or Aggregator requires a Valid Spec Version. Handling Option PICK is a Decision: reopen the target node if current, write a prose suggested patch, do not patch Cards. “Run pending Judges” may carry one Stale re-accept for generate on every Stale Judge in that batch (not Aggregator, Confirm, or other stages).

**Status:** accepted; Spec Artifact export-block clause superseded by ADR 0041.

**Considered options:** majority vote across Judges (rejected — incommensurable outputs; wrong Judge voting on citation entailment); treat every Judge as an equal gate (rejected — Conference 7/10 is not a citation check); Account override-and-export while CRITICAL remains (rejected here; reopened in ADR 0041 as a recorded Critical Export Confirmation, not a silent skip); Aggregator as a sixth LLM Judge (rejected — would launder votes); severity assigned freely by the LLM (rejected — would under-grade CRITICAL).

**Why:** TOPIC requires independent Judges, measuring disagreement, and Account-chosen fixes with related verifiers re-run. A citation that does not support a claim is a structural fail of the Research Spec, not one ballot among five. Readiness still fails; export is a separate Decision (ADR 0041).
