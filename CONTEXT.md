# SpecResearch Loop

A website that turns a vague research idea into a verified research specification through a human-in-the-loop workflow (grilling, related work, gap, contribution, claims/evidence, experiment planning, Spec Draft, independent judges, and readiness). The system evaluates readiness criteria; it does not guarantee conference acceptance.

## Language

**Research Spec**:
The structured, user-confirmed specification of a research idea (problem, gap, contribution, claims, evidence, experiment plan, and open questions).
_Avoid_: paper, proposal (unless the user explicitly means a submitted paper), document dump

**SpecResearch Loop**:
The product and end-to-end workflow that moves an idea through research and judgement until the user confirms a Research Spec.
_Avoid_: pipeline (alone), agent swarm, autopilot research

**Loop Session**:
An Account's project: one research idea being clarified into a Research Spec; the durable unit they open, save, and resume. Canonical term is Loop Session; project means the same thing. It has an Account-editable title used as the list and header label; the title is not part of the Research Spec and is not a Stage Revision.
_Avoid_: session (alone), chat, conversation, thread

**Account**:
A signed-in person who owns Loop Sessions.
_Avoid_: user (when you mean the persisted identity), client, profile

**Spec Artifact**:
An exported or stored binary/document of the unedited Valid Spec Version, kept in object storage and referenced from Postgres. It is not an Export Scratch. CRITICAL Judge Issues fail Readiness; they do not block this export. When the current Aggregator Report still has any CRITICAL Issue, each Spec Artifact export requires a Critical Export Confirmation. Choosing a Handling Option does not clear the Readiness fail; the related Judge must run again and the CRITICAL Issue must be gone. A Judge Run never un-mints a Spec Version.
_Avoid_: file, blob, attachment (when you mean the domain export), Export Scratch

**Decision**:
A recorded Account choice that changes Loop Session history without being a generate: Confirm, reopen a current Workflow Node, revert, picking a Handling Option, or a Critical Export Confirmation. Choosing a Grilling Option, sending an Account note, and Send are generate input, not Decisions. Saving an Export Scratch Snapshot is not a Decision. Successful generate on a Judge records Confirm of that Judge even when Working Draft is not that Judge; Confirm of Aggregator still requires Working Draft Aggregator.
_Avoid_: event, log entry, chat message, Grilling Option click, auto-Confirm

**Critical Export Confirmation**:
A Decision recorded each time the Account confirms Spec Artifact export or Export Scratch download while the current Aggregator Report still has any CRITICAL Judge Issue. It does not make Readiness pass, does not mint a Spec Version, and does not clear Judge Issues. There is no session- or Spec-Version-scoped skip; each download is its own Decision.
_Avoid_: Handling Option, export anyway (as UI-only, unrecorded), override

**Stage Revision**:
An immutable, user-confirmed snapshot of one Workflow Node's output.
_Avoid_: commit, checkpoint, save (alone)

**Spec Version**:
An immutable assembled Research Spec taken from valid Stage Revisions at one moment.
_Avoid_: draft (alone), document, latest spec

**Produced Spec Version**:
The most recently minted Spec Version in a Loop Session; it may be stale after an upstream change.
_Avoid_: latest spec (alone)

**Valid Spec Version**:
The Produced Spec Version when it is not stale; otherwise the Loop Session has none until feasibility is confirmed again and mints a new Spec Version.
_Avoid_: current spec, head

**Working Draft**:
The session's current editing Workflow Node plus narrative JSONB. In-progress typed attachments are working rows with no Stage Revision. Node-scoped narratives are retained while another Workflow Node is being edited, so navigating away and returning does not discard unconfirmed generated work. Navigating away or reopening a current Workflow Node keeps the last Stage Revision current; only a confirm whose content changed marks descendants Stale. On Independent judges, Working Draft is Aggregator even when Aggregator is empty or Stale and even when a Judge is empty or Stale; generate on a Judge does not move it. Interpretation stores a structured turn list (the research idea, Grilling Question clusters, Account replies, Account notes) plus the latest Idea Frame. Grilling Questions are not Cards. Confirm is allowed once the Idea Frame's intent, problem, and research_question are all non-blank; unanswered Grilling Question clusters do not block Confirm. exhausted is a hint, not a gate. Confirm does not persist in-flight Grilling Option picks. Saving an earlier Account reply or note drops later turns.
_Avoid_: temp, cache, unsaved changes

**Loop Stage**:
A user-facing group of Workflow Nodes the Account recomputes together by opening empty or Stale Workflow Nodes in that group: Grilling (interpretation, decomposition), Related work (research inputs, related work), Gap, Contribution, Claims/evidence (`claims` only), Experiment planning, Spec Draft, Independent judges, Readiness. Spec Draft and Readiness have no Workflow Nodes. Confirm is per Workflow Node. Independent judges is one dashboard: five compact Judge Node Heads plus the Aggregator Report; it is not six destinations. Prepare of Independent judges still resets empty or Stale nodes in that group and lands Working Draft on Aggregator.
_Avoid_: step, bước, pipeline stage (when you mean this UI unit), Nav Unit, Judge tab

**Readiness**:
The Loop Stage with no Workflow Node that shows readiness criteria for the Valid Spec Version, derived from the current Aggregator Report. It is not conference acceptance. CRITICAL Judge Issues fail it; Conference Judge criterion scores are displayed and do not by themselves fail it. Spec Artifact export and Export Scratch download are not blocked by CRITICAL; each requires a Critical Export Confirmation while any CRITICAL remains. The same stage shows Clarification Review and the Export Scratch of a selected Spec Version. The Account opens the Export Scratch editor and preview as a Readiness mode, not a Loop Stage; they are not shown until then. While that mode is open the Loop Stage rail is hidden and the Loop Session header remains; Done returns to the rest of Readiness. The mode is addressable on the Readiness URL together with the Spec Version being edited; that URL does not change which Spec Version the criteria follow. Choosing an older Spec Version does not change the criteria, which always follow the current Valid Spec Version and Aggregator Report.
_Avoid_: acceptance, conference acceptance, score (alone), Conference Judge (that is a Workflow Node), Spec Draft, Export Scratch editor (as a Loop Stage)

**Export Scratch**:
A session-owned markdown document of one Spec Version that the Account may edit and download. One last-write-wins Export Scratch exists per Spec Version; it is not a Working Draft. First content is a paper-shaped projection; later edits are opaque markdown and need not keep those headings. The stored markdown is the downloaded file; PDF is a rendering of that markdown. Overlay edits autosave last-write-wins; they do not change Cards, Stage Revisions, Produced Spec Version, or Valid Spec Version. Changing the loop still means reopening a Workflow Node. Download uses the current Export Scratch, including edits not yet autosaved. Download while any CRITICAL remains on the current Aggregator Report requires a Critical Export Confirmation. It is not a Spec Version, Spec Artifact, Working Draft, or Card.
_Avoid_: Spec Version, Spec Artifact, Working Draft, fork (as the canonical name), scratch (alone), spec scratch, section JSON

**Export Scratch Snapshot**:
An immutable saved copy of an Export Scratch, bound to the Spec Version it was projected from. The first snapshot for a Spec Version is created when the Account Confirms Aggregator if that Spec Version has none (deterministic projection, no generate). Later snapshots are an explicit Save Snapshot from the Export Scratch editor. Diff is whole-document markdown against the previous snapshot of the same Spec Version and against that Spec Version's original projection; diffs are read on Readiness, not in the editor.
_Avoid_: Spec Version, Stage Revision, version (alone)

**Clarification Review**:
A read-only Readiness panel: the original research idea versus the gap, contribution, and claims of the Spec Version being viewed. Derived from stored Stage Revisions; not a generate, not Idea Frame, not a Card. Not a picker; those Cards are the ones already Confirmed on that Spec Version.
_Avoid_: restatement, Idea Frame, summary, generate

**Spec Draft**:
The Loop Stage whose UI shows the Produced Spec Version (and whether it is Valid or Stale). It is not a Workflow Node and has no Working Draft; confirming feasibility mints the Spec Version the Account reads here. For idea interpretation, Spec Draft shows the Idea Frame's problem and research_question only—not Intent, not the turn list (Node Head browse still shows the full Idea Frame and turns). For idea decomposition, Spec Draft omits problem and research_question Cards (those bodies are the confirmed Idea Frame fields); constraint and open-question Cards remain. Node Head and Working Draft of decomposition still show all four Card kinds. Product copy may say Spec Draft; glossary terms for the document remain Spec Version / Produced / Valid. Spec Draft is not the Export Scratch editor.
_Avoid_: Working Draft, Spec Version (as the stage name), spec construction stage, Export Scratch

**Workflow Node**:
A confirmable unit in a Loop Session's invalidation graph (for example idea interpretation, contribution, or a Judge). A Loop Stage groups zero or more Workflow Nodes. Spec Draft and Readiness have none. A Spec Version is not a Workflow Node; confirming feasibility mints it. Claim and Evidence Cards are confirmed together on `claims`; `evidence` is not a Workflow Node (it may still appear on old Decision rows).
_Avoid_: DAG node (in product copy), step, pipeline stage (that is a Loop Stage), Evidence (when you mean the Card kind or Evidence Judge)

**Node Head**:
The Loop Session's pointer for one Workflow Node: empty, a current Stage Revision, or a Stale Stage Revision. Independent judges compact heads show empty as none, current as done, and in-flight generate as evaluating.
_Avoid_: NodeState, stage status, head (when you mean Valid Spec Version)

**Card**:
A first-class piece of the idea that keeps the same identity across Loop Stages (problem, research question, gap, contribution, claim, evidence, constraint, open question). Later stages attach research and spec data to it; a Stage Revision freezes the card body at confirm time. Constraint and open-question Cards are confirmed in Grilling, not in experiment planning. Claim and Evidence Cards are both owned by `claims`; Confirm `claims` requires at least one non-blank Card of each kind. A Loop Session has one problem Card and one research-question Card; it may have many constraint and open-question Cards.
_Avoid_: sticky note, field, ticket, citation (citations are not Cards), Grilling Question

**Grilling Question**:
A model-posed question on interpretation Working Draft. Not a Card. Each question may include Grilling Options.
_Avoid_: Card, survey item, chat message

**Grilling Option**:
A proposed reply to a Grilling Question, shown after generate completes. Interpretation only. Choosing one is generate input, not a Decision.
_Avoid_: Card, Decision, chip, radio

**Idea Frame**:
The model-authored restatement of the research idea on interpretation Working Draft, rewritten each generate. Its fields are intent, problem, and research_question; all three must be non-blank to Confirm. It is not a Card. The Account cannot edit it. Confirm freezes the latest Idea Frame with the turn list. The confirmed problem and research_question fields are the source of those Card bodies; Intent is not a Card.
_Avoid_: Card, summary, restatement (alone), preamble

**Intent**:
A model-authored paragraph on the Idea Frame that paraphrases what the Account wants, rewritten each generate. Not a Card. Required to Confirm. Shown on interpretation Working Draft and Node Head; omitted from Spec Draft.
_Avoid_: restatement (the whole Idea Frame), summary, preamble, understanding

**Account note**:
A free-form Account turn on interpretation Working Draft. Generate input, not a Decision. With an open Grilling Question cluster, a note may skip that cluster. It is not an Idea Frame edit and not a Card.
_Avoid_: prompt, chat message, comment, message (when you mean this turn)

**Citation**:
A stored source record in a Loop Session, optionally linked to Cards. It is not a Card. Gap Judge and Contribution Judge treat Citation passages and related-work findings as support; they do not treat Evidence Cards as that support.
_Avoid_: paper (when you mean this record), source (alone), blob

**Judge Run**:
One Judge's immutable evaluation of a Spec Version, stored as typed rows on that Judge's Stage Revision. It is a list of Judge Issues plus, for Conference Judge, criterion scores (originality, significance, soundness, clarity, reproducibility). ACCEPT/REJECT is derived: any CRITICAL Judge Issue means not ACCEPT. Judges evaluate independently; a Judge Run must not include another Judge's output. Generate on a Judge or the Aggregator requires a Valid Spec Version. Successful generate on a Judge is Confirm of that Judge, including when Working Draft is Aggregator; a failed or aborted generate is not. Confirm freezes the evaluation even when it contains CRITICAL Issues. Opening Independent judges does not generate Judges.
_Avoid_: review, score, feedback (when you mean this stored run), verdict (alone), majority vote, auto-Confirm

**Judge Issue**:
A typed finding on a Judge Run: Finding Kind, Severity, reason, and suggestion. Not a Card. Not a Decision. Rule-based verifiers in `judgement` read Context Projection (not another module's tables). Evidence: citation passage does not entail the claim → `unsupported_citation`. Gap: no cited passage supports the gap statement → `gap_unsupported_by_sources` only. `gap_already_addressed` and `gap_untestable` are LLM-emitted. The LLM may add Issues and may raise Severity; it must not drop or lower a verifier-emitted Issue.
_Avoid_: comment, complaint, flag, triage item, MAJOR (as a Judge-level result)

**Finding Kind**:
A closed tag on a Judge Issue that selects the Severity floor. Day-one catalog: `gap_unsupported_by_sources`, `gap_already_addressed`, `gap_untestable`, `contribution_not_novel`, `contribution_overclaimed`, `unsupported_citation`, `claim_broader_than_experiment`, `experiment_insufficient_for_claim`. The LLM may not invent kinds; unknown tags are dropped. It may raise Severity above the floor, never lower it. Conference Judge emits criterion scores only, not Judge Issues.
_Avoid_: verdict, category (alone), issue type (when you mean this tag), other (as a Finding Kind)

**Severity**:
CRITICAL, MAJOR, or MINOR on a Judge Issue. Each Finding Kind has a floor. CRITICAL fails Readiness until that Issue is gone from the current Aggregator Report. It does not block Spec Artifact export or Export Scratch download; a Critical Export Confirmation is required while any CRITICAL remains. MAJOR and MINOR do not fail Readiness. Conference criterion scores are not Severity.
_Avoid_: priority, score, verdict, vote

**Handling Option**:
A proposed way to address a Judge Issue or disagreement cluster on the Aggregator Report. Offered for CRITICAL and MAJOR; MINOR Issues are listed without Handling Options. Choosing one is a Decision (PICK). If the target Node Head is current, PICK reopens it (same idea as EDIT) and does not mark it Stale; the Account leaves Independent judges. It writes a prose suggested patch (and target Card ids) onto that node's Working Draft narrative; it does not patch Card bodies, the Spec Version, Severity, or Judge Runs. Several Handling Options may share one Judge Issue and target different Workflow Nodes. Other is a Handling Option whose prose and target Workflow Node are supplied by the Account (gap, contribution, claims, experiment_plan, or idea_decomposition); the Aggregator LLM does not invent Other. Generate, Confirm, Stale, and related Judge re-runs follow the existing loop; Judges do not auto-run. PICK is offered on the working Aggregator Report, before Confirm Aggregator. Handling Options may be skipped for Spec Artifact export; skipping CRITICAL does not make Readiness pass.
_Avoid_: Grilling Option, override, export anyway, patch (when you mean the Decision), Apply suggestion

**Aggregator Report**:
The Aggregator's composed output from the five current Judge Runs: grouped Judge Issues, consensus vs disagreement, Readiness flags, and Handling Options. It copies Severity from Judge Runs and must not rewrite it. LLM copy may phrase Handling Options; it must not change Severity or invent a majority verdict. Independent judges shows Judge Issues and Handling Options here, not as five full Judge lists. Generate starts when all five Judge heads are current; Confirm Aggregator is still an Account Decision and advances to Readiness.
_Avoid_: verdict, majority vote, final score, Judge (the Aggregator is not a sixth Judge)

**Stale**:
A Stage Revision or Spec Version whose upstream inputs have changed via a confirm with different content. It remains for history and diff; it is not used as input. Opening a Working Draft is not a change.
_Avoid_: deleted, invalid, outdated (when you mean this state)

**Stale re-accept**:
An explicit ack that the Account accepts proceeding on a Stale Workflow Node without a successful generate or Judge Run since prepare. Required for Confirm and for generate (ADR 0036). A “run pending Judges” request may carry one ack covering generate on every Stale Judge in that batch. That ack does not cover Aggregator generate, Confirm, or other Loop Stages. When the five Judge heads are current, Aggregator generate may carry Stale re-accept for Aggregator; that ack does not cover Confirm Aggregator. The acknowledgement is not a separate Decision.
_Avoid_: force confirm, skip regenerate, override stale, Confirm anyway (UI copy only)

**Context Projection**:
The payload assembled for a generate or Judge run from valid upstream Stage Revisions plus the Working Draft of the node being run.
_Avoid_: context (alone), prompt, Prompt View (when you mean the full assembly), RAG dump

**Prompt View**:
A Workflow-Node-scoped, prompt-ready slice derived from a Context Projection for an LLM generate or Judge call. It does not replace Context Projection. A Judge's Prompt View must not include another Judge Run; the Aggregator's Prompt View is the five current Judge Runs. Gap Judge omits Evidence Cards and Claim Cards; Contribution Judge omits Evidence Cards and keeps Claim Cards; both include Citation passages and related-work findings. Evidence Judge, Experiment Judge, and Conference Judge keep Evidence Cards. The Account may start remaining empty or Stale Judges in parallel (“run pending Judges”); that action does not start the Aggregator. Stale Judges in the batch require the request's batch Stale re-accept. When all five Judge heads are current, Aggregator generate starts; a later successful Judge generate that leaves five heads current starts it again and replaces an unconfirmed Aggregator Report.
_Avoid_: context (alone), prompt context, Prompt Projection, RAG dump
