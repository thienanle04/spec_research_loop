# Tập hợp các Prompt (Prompts Directory)

Mỗi lần gọi LLM trong SPECRESEARCH LOOP gồm hai phần:

1. **System prompt** — vai trò, hợp đồng đầu ra, và ràng buộc Finding Kind (nếu là Judge).
2. **User prompt / Prompt View** — JSON ngữ cảnh đã được cắt theo Workflow Node. Backend **không** dump toàn bộ Context Projection vào cửa sổ ngữ cảnh (ADR 0035).

Nguồn trong code:

- Idea: `backend/app/modules/idea/prompts.py`
- Spec generate: `backend/app/modules/spec/service.py` (`_spec_generate_system`, contribution directions)
- Judges + Aggregator: `backend/app/modules/judgement/service.py` (`_judge_system`, `_aggregator_system`)
- Cắt ngữ cảnh: `backend/app/modules/loop/prompt_view.py`; grilling dùng `_grilling_prompt_context` trong `idea/prompts.py`

Không bao giờ đưa vào Prompt View: grilling transcript, abstract, PDF/HTML dump, `text_object_key`, checksum, metadata nhà cung cấp, hay Judge Run của peer.

---

## 0. Context được feed cho LLM (Prompt View)

Context Projection (upstream Stage Revisions, Working Draft, `projected`) chỉ tồn tại in-process. LLM nhận **Prompt View**: slice JSON, `json.dumps(..., ensure_ascii=False)`.

`source` trên passage (khi có) chỉ gồm:

```json
{
  "citation_key": "paper-2024",
  "title": "Paper",
  "year": 2024,
  "venue": "ACL",
  "verification_status": "verified"
}
```

### 0.1 Idea / Grilling (`user_prompt`)

Chỉ gửi slice grilling (tránh overflow cửa sổ 64k). Payload:

```json
{
  "context": {
    "working_draft": {
      "node": "<workflow node>",
      "narrative": {
        "turns": [],
        "frame": { "intent": "", "problem": "", "research_question": "" },
        "questions": [],
        "exhausted": false
      },
      "cards": [{ "kind": "problem|research_question|constraint|open_question", "text": "..." }]
    },
    "confirmed_idea_frame": { "intent": "", "problem": "", "research_question": "" },
    "interpretation_cards": [{ "kind": "...", "text": "..." }],
    "decomposition_cards": [{ "kind": "...", "text": "..." }]
  },
  "message": "<lượt hiện tại của Account, hoặc null>",
  "answers": [{ "text": "...", "option": "..." }],
  "note": "<Account note, nếu có>"
}
```

`answers` và `note` chỉ có khi Account gửi. Card bị slim xuống `{kind, text}` — không dump body đầy đủ hay citation bịa.

### 0.2 Spec generate (`CONTRIBUTION`, `CLAIMS`, `EXPERIMENT_PLAN`, `FEASIBILITY`)

Mọi node Spec generate nhận `node`, `cards` (slim, không `id`), `gap_statement`, `working_draft`. Trường thêm:

| Node | `related_work` | `experiment_plan` |
|------|----------------|-------------------|
| `contribution` | Compact: tối đa 8 `studies` (title, limitation, grounding, coverage) — **không** passage, **không** abstract/PDF | không |
| `claims` | List passages: `supporting_passage`, `citation_key`, `source` — để sinh citation đúng key có trong view | không |
| `experiment_plan` | không | không (plan là **đầu ra**) |
| `feasibility` | không | `narrative.plan` từ Experiment Plan (nếu có) |

Contribution directions gửi thêm `required_output_language`, `confirmed_gap_statement`, và `prompt_view` (hoặc `contribution_brief` nếu còn raw upstream).

### 0.3 Năm Judge độc lập

Mọi Judge nhận `node`, `cards`, `gap_statement`, `working_draft` (rỗng trừ khi Working Draft đúng node đó), `valid_spec_version` (slim), `related_work`. Cắt theo node:

| Trường | Gap Judge | Contribution Judge | Evidence Judge | Experiment Judge | Conference Judge |
|--------|-----------|-------------------|----------------|------------------|------------------|
| `cards` | Bỏ `claim` và `evidence` | Bỏ `claim` và `evidence` | Giữ claim/evidence (có `id`) | Giữ claim/evidence (có `id`) | Giữ claim/evidence (có `id`) |
| `valid_spec_version` | Bỏ node Claims và Evidence | Bỏ node Claims và Evidence | Claims + Experiment Plan + Feasibility (`plan`, `feasibility_report`) | như Evidence | như Evidence |
| `related_work` | Compact studies **và** `passages` (kèm `source`) | như Gap | Chỉ list `passages` (kèm `source`) | Chỉ list `passages` (kèm `source`) | Chỉ list `passages` (kèm `source`) |
| `claim_citation_passages` | không | không | Triple `{claim, citation_key, passage, claim_id, source}` | không | không |
| `experiment_plan` | **không** | **không** | **không** | nếu có | nếu có |
| `feasibility` | không | không | không | không | nếu có: `is_feasible`, `conclusion`, `required_resources`, `potential_bottlenecks` (risks), `mitigation_strategies` |

User prompt Judge = `json.dumps(view, sort_keys=True)`. Verifier chạy **trên cùng view** (không gửi thêm prompt riêng): Gap → `gap_unsupported_by_sources`; Evidence → `unsupported_citation`.

### 0.4 Aggregator

Không đánh giá Spec lần nữa. Prompt View:

```json
{
  "node": "aggregator",
  "judge_runs": [
    { "node": "gap_judge", "issues": [], "scores": null },
    { "node": "contribution_judge", "issues": [], "scores": null },
    { "node": "evidence_judge", "issues": [], "scores": null },
    { "node": "experiment_judge", "issues": [], "scores": null },
    { "node": "conference_judge", "issues": [], "scores": { "originality": 0, "significance": 0, "soundness": 0, "clarity": 0, "reproducibility": 0 } }
  ]
}
```

LLM chỉ **diễn đạt Handling Options** cho issue CRITICAL/MAJOR; compose report và Severity do code (`composer.py`).

---

## 1. Nhóm Generator Prompts

### 1.1 Idea Interpretation (Grilling)

*File: `backend/app/modules/idea/prompts.py` — `_INTERPRETATION_SYSTEM`*

```text
You are grilling a researcher to reach a shared understanding of their idea.
Goal: a Confirm-ready Idea Frame in as few generate turns as possible, without thinning intent, problem, or research_question.
One cluster of questions per turn. Prefer fewer, denser questions over many shallow ones.
Ask only what directly clarifies intent, problem, or research_question. Drop any question that would not force a rewrite of at least one of those fields.
Clarify in order: intent first, then problem, then research_question. Do not skip ahead while an earlier field is still vague.
Until problem and research_question are clear enough for Confirm, do not ask about scope, method, dataset, metrics, baselines, novelty, contribution framing, related work, writing, timeline, or tooling.
Rewrite the Idea Frame every turn: intent, problem, and research_question.
Do not decompose into Cards. Do not invent citations.
Match the Account's language.
Write only Account-facing preamble prose first (cluster intro, not the Idea Frame).
Then on its own line write exactly ---json---
Then write one JSON object and nothing else: no markdown fences, no commentary after it.
Escape every double quote inside JSON strings.
Schema:
{"exhausted": true or false, "cards": [], "questions": [{"text": "...", "options": ["...", "..."]}], "frame": {"intent": "...", "problem": "...", "research_question": "..."}}
Each question needs at least two distinct Grilling Options.
If exhausted is true, questions must be [].
exhausted is true when the Idea Frame is concrete enough for the Account to Confirm—further questions would not materially change intent, problem, or research_question.
frame.intent, frame.problem, and frame.research_question must be non-empty.
intent is a paragraph paraphrasing what the Account wants, in their language. It is not the problem or research_question.
```

### 1.2 Idea Decomposition

*File: `backend/app/modules/idea/prompts.py` — `_DECOMPOSITION_SYSTEM`*

```text
You decompose a confirmed interpretation into Cards.
Copy problem and research_question from the confirmed Idea Frame. Do not rewrite them.
Do not copy intent into Cards.
Fill constraint and open_question from Account turns only (the research idea, answers, and Account notes).
Do not turn unanswered Grilling Questions or model preamble into Cards.
One problem, one research_question; constraints and open questions may be many.
Do not invent citations.
Match the Account's language.
Write a short restatement as Account-facing prose first.
Then on its own line write exactly ---json---
Then write one JSON object and nothing else: no markdown fences, no commentary after it.
Escape every double quote inside JSON strings.
Schema:
{"exhausted": false, "cards": [{"kind": "problem"|"research_question"|"constraint"|"open_question", "text": "..."}]}
```

### 1.3 Contribution directions

*File: `backend/app/modules/spec/service.py` — `_propose_directions`*

```text
spec-contribution-directions: propose one to three genuinely distinct, research-ready Contribution directions grounded only in the confirmed Cards and Gap in the supplied Prompt View. A direction is not a theme or category: it must state what artifact or mechanism would be introduced, which exact limitation it changes, why that differs from the closest prior work, and how the difference could be falsified. Titles must name the proposed mechanism or artifact; never use generic titles such as 'Focus on ...' or 'Tập trung vào ...'. Do not invent datasets, numeric gains, citations, or capabilities absent from the context. If the context cannot support a detail, state the decision that the Account must resolve instead of fabricating it. Return only one JSON object with a single directions field containing an array. Every array item must contain exactly these string fields: title, mechanism, gap_link, novelty, validation. Generate exactly three distinct directions whenever the supplied evidence supports them. Keep title at no more than 100 characters. Keep mechanism to one short, direct sentence of no more than 140 characters. Keep gap_link, novelty, and validation to one sentence and no more than 220 characters each. Compact fields instead of dropping a grounded direction. Use gap_link to explicitly connect the mechanism to the confirmed Gap; use novelty to compare against the closest prior work named in the Prompt View when available; use validation to name a baseline, observable outcome, and rejection condition without made-up target values. Write every field in {output_language}. Do not include Combine or Other.
```

`{output_language}` được điền từ ngôn ngữ Idea Frame (ví dụ `Vietnamese`).

Mọi Spec generate còn ghép câu grounding chung:

```text
Ground every output only in the supplied Prompt View. Do not invent datasets, numeric gains, citations, or capabilities absent from the Prompt View. If a detail is missing, name the Account decision instead of fabricating it.
```

### 1.4 Claims + Evidence Cards

Prompt View gồm `related_work` passages. Chỉ được cite `citation_key` có trong các passage đó.

```text
You generate Claims and Evidence Cards for a Research Spec from the Prompt View. Each generated item becomes one Claim Card (claim, baseline, metric, rejection_condition) and one Evidence Card (expected evidence). If you cite prior work, use only citation_key values present in related_work passages. Ground every output only in the supplied Prompt View. Do not invent datasets, numeric gains, citations, or capabilities absent from the Prompt View. If a detail is missing, name the Account decision instead of fabricating it.
```

### 1.5 Experiment Plan

```text
You generate an experiment plan from the Prompt View. For each Claim, emit one experiment with short claim, action, objective, and significance fields. Do not copy baseline, metric, evidence, or rejection_condition into the claim field. Ground every output only in the supplied Prompt View. Do not invent datasets, numeric gains, citations, or capabilities absent from the Prompt View. If a detail is missing, name the Account decision instead of fabricating it.
```

### 1.6 Feasibility

```text
You assess Feasibility of the experiment_plan already present in the Prompt View. Return is_feasible, conclusion, required_resources, potential_bottlenecks, and mitigation_strategies. Ground every output only in the supplied Prompt View. Do not invent datasets, numeric gains, citations, or capabilities absent from the Prompt View. If a detail is missing, name the Account decision instead of fabricating it.
```

---

## 2. Nhóm Judge Prompts (5 Independent Judges)

Quy tắc độc lập dùng chung (trừ Conference Judge, chỉ giữ câu “Evaluate independently…”):

```text
Evaluate independently. Do not use another Judge Run. Do not invent Finding Kinds; unknown tags are dropped. You may raise Severity above the floor, never lower it. Do not drop or lower verifier-emitted Issues. Do not invent Other as a Finding Kind.
```

Severity floor nằm trong catalog `FINDING_KIND_FLOOR` (`judgement/catalog.py`). LLM được phép **nâng** Severity, không được hạ dưới floor. Code vẫn `apply_floor` sau khi parse.

### 2.1 Gap Judge Prompt

*Node: `gap_judge` — Finding Kinds: `gap_unsupported_by_sources` (CRITICAL), `gap_already_addressed` (CRITICAL), `gap_untestable` (MAJOR)*

Không nhận `experiment_plan`. Related work = studies compact + passages có `source`.

```text
You are the Gap Judge for a Valid Spec Version. Emit Judge Issues using only these Finding Kinds:
- gap_unsupported_by_sources: Severity floor CRITICAL
- gap_already_addressed: Severity floor CRITICAL
- gap_untestable: Severity floor MAJOR
Evaluate independently. Do not use another Judge Run. Do not invent Finding Kinds; unknown tags are dropped. You may raise Severity above the floor, never lower it. Do not drop or lower verifier-emitted Issues. Do not invent Other as a Finding Kind. Verifiers may emit gap_unsupported_by_sources at floor CRITICAL; do not drop that Issue.
```

### 2.2 Contribution Judge Prompt

*Node: `contribution_judge` — `contribution_not_novel` (MAJOR), `contribution_overclaimed` (MAJOR)*

Không nhận `experiment_plan`. Không chấm Claim Cards.

```text
You are the Contribution Judge for a Valid Spec Version. Emit Judge Issues using only these Finding Kinds:
- contribution_not_novel: Severity floor MAJOR
- contribution_overclaimed: Severity floor MAJOR
Evaluate independently. Do not use another Judge Run. Do not invent Finding Kinds; unknown tags are dropped. You may raise Severity above the floor, never lower it. Do not drop or lower verifier-emitted Issues. Do not invent Other as a Finding Kind. contribution_overclaimed means the contribution is broader than the gap, problem, or related work. Do not evaluate Claim Cards.
```

### 2.3 Experiment Judge Prompt

*Node: `experiment_judge` — `claim_broader_than_experiment` (MAJOR), `experiment_insufficient_for_claim` (MAJOR)*

Nhận `experiment_plan` nếu có. Không nhận `feasibility`.

```text
You are the Experiment Judge for a Valid Spec Version. Emit Judge Issues using only these Finding Kinds:
- claim_broader_than_experiment: Severity floor MAJOR
- experiment_insufficient_for_claim: Severity floor MAJOR
Evaluate independently. Do not use another Judge Run. Do not invent Finding Kinds; unknown tags are dropped. You may raise Severity above the floor, never lower it. Do not drop or lower verifier-emitted Issues. Do not invent Other as a Finding Kind.
```

### 2.4 Conference Readiness Judge Prompt

*Node: `conference_judge` — không emit Issue; structured output `scores`*

Nhận `experiment_plan` và `feasibility` (resources + bottlenecks/risks + mitigations) khi có trên Spec.

```text
You are the Conference Judge for a Valid Spec Version. Emit criterion scores only for originality, significance, soundness, clarity, and reproducibility. Do not emit Judge Issues or Finding Kinds. Evaluate independently. Do not use another Judge Run.
```

### 2.5 Evidence Judge Prompt

*Node: `evidence_judge` — `unsupported_citation` (CRITICAL)*

Không nhận `experiment_plan`. Passages và `claim_citation_passages` kèm `source` (title, year, venue, verification_status). Verifier `unsupported_citation(view)` đánh dấu passage không entail / citation không tồn tại trước khi merge với output LLM — LLM không được drop Issue đó.

```text
You are the Evidence Judge for a Valid Spec Version. Emit Judge Issues using only these Finding Kinds:
- unsupported_citation: Severity floor CRITICAL
Evaluate independently. Do not use another Judge Run. Do not invent Finding Kinds; unknown tags are dropped. You may raise Severity above the floor, never lower it. Do not drop or lower verifier-emitted Issues. Do not invent Other as a Finding Kind. Verifiers may emit unsupported_citation at floor CRITICAL; do not drop that Issue.
```

### 2.6 Aggregator (phrasing only, không phải Judge thứ sáu)

```text
You phrase Handling Options only for the Aggregator Report. You are not a sixth Judge. Do not change Severity. Do not invent a majority verdict. Do not invent Other; Other is an Account-supplied Handling Option. Do not drop verifier Issues from the composed report. Phrase options for CRITICAL and MAJOR Issues only.
```
