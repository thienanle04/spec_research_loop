import { CardKind, WorkflowNode } from "@/lib/api/generated/model";

import { parseFrame, parseTurns } from "@/features/idea/turns";

import { CARD_KIND_LABELS, WORKFLOW_NODE_LABELS } from "./catalog";
import {
  DevLeftovers,
  ExperimentPlanView,
  FeasibilityReportView,
  GapBodyView,
  parseExperimentPlan,
  parseFeasibilityReport,
  parseResearchInputs,
  RelatedWorkRevisionView,
  ResearchInputsView,
} from "./stage-revision-viewers";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function unknownFields(value: Record<string, unknown>, knownKeys: readonly string[]): Record<string, unknown> | null {
  const rest: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (!knownKeys.includes(key)) {
      rest[key] = entry;
    }
  }
  return Object.keys(rest).length > 0 ? rest : null;
}

function fieldText(value: unknown): string | null {
  if (!isRecord(value) || typeof value.text !== "string") {
    return null;
  }
  return value.text;
}

function cardKindLabel(kind: unknown): string {
  if (typeof kind === "string" && Object.values(CardKind).includes(kind as CardKind)) {
    return CARD_KIND_LABELS[kind as CardKind];
  }
  return typeof kind === "string" ? kind : "Card";
}

const CARDS_ONLY_NODES = new Set<WorkflowNode>([
  WorkflowNode.contribution,
  WorkflowNode.claims,
  WorkflowNode.evidence,
]);

function GrillingRevision({
  narrative,
  showLeftovers,
  showTurns = true,
}: {
  narrative: Record<string, unknown>;
  showLeftovers: boolean;
  showTurns?: boolean;
}) {
  const frame = parseFrame(narrative);
  const turns = showTurns ? parseTurns(narrative) : [];
  const leftover = unknownFields(narrative, ["turns", "frame", "exhausted"]);
  const hasFrame = Boolean(frame.intent || frame.problem || frame.research_question);
  return (
    <div className="grid min-w-0 grid-cols-1 gap-3">
      {hasFrame ? (
        <dl className="grid gap-2 text-sm">
          {frame.intent ? (
            <div>
              <dt className="font-medium">Intent</dt>
              <dd className="whitespace-pre-wrap">{frame.intent}</dd>
            </div>
          ) : null}
          {frame.problem ? (
            <div>
              <dt className="font-medium">Problem</dt>
              <dd className="whitespace-pre-wrap">{frame.problem}</dd>
            </div>
          ) : null}
          {frame.research_question ? (
            <div>
              <dt className="font-medium">Research question</dt>
              <dd className="whitespace-pre-wrap">{frame.research_question}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {turns.length > 0 ? (
        <ol className="grid gap-2 text-sm">
          {turns.map((turn, index) => (
            <li key={index} className="rounded-md border bg-muted/40 px-3 py-2">
              {turn.role === "account" && turn.kind === "answers" ? (
                <p>{turn.answers.map((answer) => ("option" in answer ? answer.option : answer.other)).join(", ")}</p>
              ) : turn.role === "model" ? (
                <p className="whitespace-pre-wrap">{turn.preamble || turn.questions.map((q) => q.text).join(" ")}</p>
              ) : (
                <p className="whitespace-pre-wrap">{turn.text}</p>
              )}
            </li>
          ))}
        </ol>
      ) : null}
      <DevLeftovers show={showLeftovers} value={leftover} />
    </div>
  );
}

function CardSnapshotView({
  cards,
  preferGapBody,
  showLeftovers,
}: {
  cards: unknown[];
  preferGapBody: boolean;
  showLeftovers: boolean;
}) {
  const hideKindTitle = new Set<string>([CardKind.gap, CardKind.contribution, CardKind.claim]);
  return (
    <>
      {cards.map((card, index) => {
        if (!isRecord(card)) {
          return (
            <DevLeftovers key={index} show={showLeftovers} value={card} label="Invalid card" />
          );
        }
        const body = isRecord(card.body) ? card.body : null;
        const text = body ? fieldText(body) : null;
        const gapBody = preferGapBody && body && typeof body.statement === "string";
        const unknownBody = body && !gapBody ? unknownFields(body, ["text"]) : null;
        const unknownCard = unknownFields(card, ["id", "kind", "body"]);
        const showKindTitle =
          typeof card.kind === "string" ? !hideKindTitle.has(card.kind) : true;
        return (
          <div
            key={typeof card.id === "string" ? card.id : index}
            className="min-w-0 rounded-md border bg-muted/40 px-3 py-2"
          >
            {showKindTitle ? (
              <p className="text-sm font-medium">{cardKindLabel(card.kind)}</p>
            ) : null}
            {gapBody && body ? <GapBodyView body={body} showLeftovers={showLeftovers} /> : null}
            {!gapBody && text ? <p className="text-sm whitespace-pre-wrap">{text}</p> : null}
            <DevLeftovers show={showLeftovers} value={unknownBody} />
            {body === null && card.body !== undefined ? (
              <DevLeftovers show={showLeftovers} value={card.body} label="Card body" />
            ) : null}
            <DevLeftovers show={showLeftovers} value={unknownCard} />
          </div>
        );
      })}
    </>
  );
}

export function StageRevisionBody({
  node,
  payload,
  showNodeLabel = true,
  sessionId,
  stageRevisionId,
  showLeftovers = true,
  showTurns = true,
}: {
  node: WorkflowNode;
  payload: unknown;
  showNodeLabel?: boolean;
  sessionId?: string;
  stageRevisionId?: string | null;
  showLeftovers?: boolean;
  /** When false (Spec Draft), grilling narratives omit the turn list and show Idea Frame only. */
  showTurns?: boolean;
}) {
  if (!isRecord(payload)) {
    return (
      <div className="grid min-w-0 grid-cols-1 gap-2">
        {showNodeLabel ? <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p> : null}
        <DevLeftovers show={showLeftovers} value={payload} label="Unstructured payload" />
      </div>
    );
  }

  const narrative = isRecord(payload.narrative) ? payload.narrative : null;
  const grilling =
    narrative && (Array.isArray(narrative.turns) || isRecord(narrative.frame));
  const narrativeText = narrative && !grilling ? fieldText(narrative) : null;
  const cards = Array.isArray(payload.card_snapshot) ? payload.card_snapshot : null;
  const cardsOnly = CARDS_ONLY_NODES.has(node);
  const hasConfirmedGapCard =
    node === WorkflowNode.gap &&
    Boolean(cards?.some((card) => isRecord(card) && card.kind === CardKind.gap));

  const researchInputs =
    narrative && node === WorkflowNode.research_inputs ? parseResearchInputs(narrative) : null;
  const experimentPlan =
    narrative && node === WorkflowNode.experiment_plan ? parseExperimentPlan(narrative) : null;
  const feasibilityReport =
    narrative && node === WorkflowNode.feasibility ? parseFeasibilityReport(narrative) : null;
  const structuredNarrative = Boolean(researchInputs || experimentPlan || feasibilityReport);

  const resolvedRevisionId =
    stageRevisionId ??
    (typeof payload.stage_revision_id === "string" ? payload.stage_revision_id : null);

  const knownNarrativeKeys = [
    "text",
    ...(hasConfirmedGapCard ? (["candidate"] as const) : []),
    ...(researchInputs ? (["keywords", "preferred_sources"] as const) : []),
    ...(experimentPlan ? (["plan"] as const) : []),
    ...(feasibilityReport ? (["feasibility_report", "plan"] as const) : []),
    ...(node === WorkflowNode.related_work
      ? (["search_audit", "queries", "status"] as const)
      : []),
  ];

  const cardsOnlyHidden =
    narrative && cardsOnly
      ? Object.fromEntries(
          Object.entries(narrative).filter(([key]) =>
            ["directions", "cards", "saved", "text"].includes(key),
          ),
        )
      : null;
  const narrativeLeftover = narrative
    ? cardsOnly
      ? unknownFields(narrative, ["directions", "cards", "saved", "text"])
      : grilling
        ? null
        : unknownFields(narrative, knownNarrativeKeys)
    : null;

  const unknownNode = unknownFields(payload, ["narrative", "card_snapshot", "stage_revision_id"]);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-2">
      {showNodeLabel ? <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p> : null}
      {grilling && narrative ? (
        <GrillingRevision
          narrative={narrative}
          showLeftovers={showLeftovers}
          showTurns={showTurns}
        />
      ) : null}
      {researchInputs ? <ResearchInputsView value={researchInputs} /> : null}
      {node === WorkflowNode.related_work && sessionId ? (
        <RelatedWorkRevisionView sessionId={sessionId} stageRevisionId={resolvedRevisionId} />
      ) : null}
      {node === WorkflowNode.related_work && !sessionId ? (
        <p className="text-sm text-muted-foreground">
          Related Work matrix requires a Loop Session context to load frozen citations.
        </p>
      ) : null}
      {experimentPlan ? <ExperimentPlanView plan={experimentPlan} /> : null}
      {feasibilityReport ? <FeasibilityReportView report={feasibilityReport} /> : null}
      {!cardsOnly && !structuredNarrative && narrativeText ? (
        <p className="text-sm whitespace-pre-wrap">{narrativeText}</p>
      ) : null}
      <DevLeftovers show={showLeftovers} value={cardsOnly ? cardsOnlyHidden : null} label="Generate leftovers" />
      {!grilling ? <DevLeftovers show={showLeftovers} value={narrativeLeftover} /> : null}
      {narrative === null && payload.narrative !== undefined ? (
        <DevLeftovers show={showLeftovers} value={payload.narrative} label="Narrative" />
      ) : null}
      {cards ? (
        <CardSnapshotView
          cards={cards}
          preferGapBody={node === WorkflowNode.gap}
          showLeftovers={showLeftovers}
        />
      ) : payload.card_snapshot !== undefined ? (
        <DevLeftovers show={showLeftovers} value={payload.card_snapshot} label="Card snapshot" />
      ) : null}
      <DevLeftovers show={showLeftovers} value={unknownNode} />
    </div>
  );
}
