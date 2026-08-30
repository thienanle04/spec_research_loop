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
An exported or stored binary/document produced from a Loop Session (for example a Final Spec export), kept in object storage and referenced from Postgres.
_Avoid_: file, blob, attachment (when you mean the domain export)

**Decision**:
A recorded Account choice that changes Loop Session history without being a generate: Confirm, reopen a current Workflow Node, revert, or a later-stage recorded pick. Choosing a Grilling Option, sending an Account note, and Send are generate input, not Decisions.
_Avoid_: event, log entry, chat message, Grilling Option click

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
The session's current editing Workflow Node plus narrative JSONB. In-progress typed attachments are working rows with no Stage Revision. Node-scoped narratives are retained while another Workflow Node is being edited, so navigating away and returning does not discard unconfirmed generated work. Navigating away or reopening a current Workflow Node keeps the last Stage Revision current; only a confirm whose content changed marks descendants Stale. Interpretation stores a structured turn list (the research idea, Grilling Question clusters, Account replies, Account notes) plus the latest Idea Frame. Grilling Questions are not Cards. Confirm is allowed once the Idea Frame's intent, problem, and research_question are all non-blank; unanswered Grilling Question clusters do not block Confirm. exhausted is a hint, not a gate. Confirm does not persist in-flight Grilling Option picks. Saving an earlier Account reply or note drops later turns.
_Avoid_: temp, cache, unsaved changes

**Loop Stage**:
A user-facing group of Workflow Nodes the Account recomputes together by opening empty or Stale Workflow Nodes in that group: Grilling (interpretation, decomposition), Related work (research inputs, related work), Gap, Contribution, Claims/evidence, Experiment planning, Spec Draft, Independent judges, Readiness. Spec Draft and Readiness have no Workflow Nodes. Confirm is per Workflow Node.
_Avoid_: step, bước, pipeline stage (when you mean this UI unit), Nav Unit

**Spec Draft**:
The Loop Stage whose UI shows the Produced Spec Version (and whether it is Valid or Stale). It is not a Workflow Node and has no Working Draft; confirming feasibility mints the Spec Version the Account reads here. For idea interpretation, Spec Draft shows the Idea Frame only—not the turn list (Node Head browse still shows turns). Product copy may say Spec Draft; glossary terms for the document remain Spec Version / Produced / Valid.
_Avoid_: Working Draft, Spec Version (as the stage name), spec construction stage

**Workflow Node**:
A confirmable unit in a Loop Session's invalidation graph (for example idea interpretation, contribution, or a Judge). A Loop Stage groups zero or more Workflow Nodes. Spec Draft and Readiness have none. A Spec Version is not a Workflow Node; confirming feasibility mints it.
_Avoid_: DAG node (in product copy), step, pipeline stage (that is a Loop Stage)

**Node Head**:
The Loop Session's pointer for one Workflow Node: empty, a current Stage Revision, or a Stale Stage Revision.
_Avoid_: NodeState, stage status, head (when you mean Valid Spec Version)

**Card**:
A first-class piece of the idea that keeps the same identity across Loop Stages (problem, research question, gap, contribution, claim, evidence, constraint, open question). Later stages attach research and spec data to it; a Stage Revision freezes the card body at confirm time. Constraint and open-question Cards are confirmed in Grilling, not in experiment planning. A Loop Session has one problem Card and one research-question Card; it may have many constraint and open-question Cards.
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
A model-authored paragraph on the Idea Frame that paraphrases what the Account wants, rewritten each generate. Not a Card. Required to Confirm.
_Avoid_: restatement (the whole Idea Frame), summary, preamble, understanding

**Account note**:
A free-form Account turn on interpretation Working Draft. Generate input, not a Decision. With an open Grilling Question cluster, a note may skip that cluster. It is not an Idea Frame edit and not a Card.
_Avoid_: prompt, chat message, comment, message (when you mean this turn)

**Citation**:
A stored source record in a Loop Session, optionally linked to Cards. It is not a Card.
_Avoid_: paper (when you mean this record), source (alone), blob

**Judge Run**:
One Judge's immutable evaluation of a Spec Version.
_Avoid_: review, score, feedback (when you mean this stored run)

**Stale**:
A Stage Revision or Spec Version whose upstream inputs have changed via a confirm with different content. It remains for history and diff; it is not used as input. Opening a Working Draft is not a change.
_Avoid_: deleted, invalid, outdated (when you mean this state)

**Stale re-accept**:
A Confirm on a Stale Workflow Node after the Account explicitly accepts proceeding without a successful generate or Judge Run since that node’s Working Draft was prepared from Stale. The acknowledgement is not a separate Decision.
_Avoid_: force confirm, skip regenerate, override stale, Confirm anyway (UI copy only)

**Context Projection**:
The payload assembled for a generate or Judge run from valid upstream Stage Revisions plus the Working Draft of the node being run.
_Avoid_: context (alone), prompt, Prompt View (when you mean the full assembly), RAG dump

**Prompt View**:
A Workflow-Node-scoped, prompt-ready slice derived from a Context Projection for an LLM generate or Judge call. It does not replace Context Projection.
_Avoid_: context (alone), prompt context, Prompt Projection, RAG dump
