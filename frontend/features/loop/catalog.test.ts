import { describe, expect, it } from "vitest";

import { CardKind, LoopStage, WorkflowNode } from "@/lib/api/generated/model";

import {
  LOOP_STAGE_CATALOG,
  adjacentStop,
  ancestors,
  descendants,
  isIndependentJudgeNode,
  navStops,
  ownedCardKinds,
  railStop,
  resolveSelectedNode,
  resolveSelectedStage,
  sessionHref,
  stageForWorkflowNode,
  upstreamOfStage,
  workingDraftStop,
} from "./catalog";

describe("Loop Stage catalog", () => {
  it("lists Gap, Contribution, and Spec Draft as navigable Loop Stages", () => {
    expect(LOOP_STAGE_CATALOG.map((stage) => stage.id)).toEqual(Object.values(LoopStage));
    expect(LOOP_STAGE_CATALOG.map((stage) => stage.name)).toEqual([
      "Grilling",
      "Related work",
      "Gap",
      "Contribution",
      "Claims/evidence",
      "Experiment planning",
      "Spec Draft",
      "Independent judges",
      "Readiness",
    ]);
  });

  it("groups every generated Workflow Node without a second identifier vocabulary", () => {
    const grouped = LOOP_STAGE_CATALOG.flatMap((stage) => [...stage.nodes]);
    expect(grouped).toEqual(Object.values(WorkflowNode));
    expect(LOOP_STAGE_CATALOG.find((stage) => stage.id === LoopStage.related_work)?.nodes).toEqual([
      WorkflowNode.research_inputs,
      WorkflowNode.related_work,
    ]);
    expect(LOOP_STAGE_CATALOG.find((stage) => stage.id === LoopStage.gap)?.nodes).toEqual([
      WorkflowNode.gap,
    ]);
    expect(LOOP_STAGE_CATALOG.find((stage) => stage.id === LoopStage.contribution)?.nodes).toEqual([
      WorkflowNode.contribution,
    ]);
    expect(LOOP_STAGE_CATALOG.find((stage) => stage.id === LoopStage.spec_draft)?.nodes).toEqual([]);
    expect(LOOP_STAGE_CATALOG.find((stage) => stage.id === LoopStage.readiness)?.nodes).toEqual([]);
  });

  it("maps a Working Draft Workflow Node to its Loop Stage", () => {
    expect(stageForWorkflowNode(WorkflowNode.idea_interpretation)).toBe(LoopStage.grilling);
    expect(stageForWorkflowNode(WorkflowNode.idea_decomposition)).toBe(LoopStage.grilling);
    expect(stageForWorkflowNode(WorkflowNode.gap)).toBe(LoopStage.gap);
    expect(stageForWorkflowNode(WorkflowNode.contribution)).toBe(LoopStage.contribution);
    expect(stageForWorkflowNode(WorkflowNode.aggregator)).toBe(LoopStage.independent_judges);
  });

  it("treats the five Judges as Independent judges Node Heads, not Aggregator", () => {
    expect(isIndependentJudgeNode(WorkflowNode.gap_judge)).toBe(true);
    expect(isIndependentJudgeNode(WorkflowNode.conference_judge)).toBe(true);
    expect(isIndependentJudgeNode(WorkflowNode.aggregator)).toBe(false);
    expect(isIndependentJudgeNode(WorkflowNode.feasibility)).toBe(false);
  });

  it("falls back to the Working Draft Loop Stage when the query is absent or invalid", () => {
    expect(resolveSelectedStage(null, WorkflowNode.idea_decomposition)).toBe(LoopStage.grilling);
    expect(resolveSelectedStage("not-a-stage", WorkflowNode.contribution)).toBe(
      LoopStage.contribution,
    );
    expect(resolveSelectedStage(LoopStage.contribution, WorkflowNode.contribution)).toBe(
      LoopStage.contribution,
    );
    expect(resolveSelectedStage(LoopStage.related_work, WorkflowNode.idea_interpretation)).toBe(
      LoopStage.related_work,
    );
    expect(resolveSelectedStage(LoopStage.spec_draft, WorkflowNode.feasibility)).toBe(
      LoopStage.spec_draft,
    );
  });

  it("resolves viewed Workflow Node from the query and falls back inside the Loop Stage", () => {
    expect(resolveSelectedNode(LoopStage.grilling, null, WorkflowNode.idea_decomposition)).toBe(
      WorkflowNode.idea_decomposition,
    );
    expect(
      resolveSelectedNode(LoopStage.grilling, WorkflowNode.idea_decomposition, WorkflowNode.idea_interpretation),
    ).toBe(WorkflowNode.idea_decomposition);
    expect(
      resolveSelectedNode(LoopStage.grilling, WorkflowNode.gap, WorkflowNode.idea_decomposition),
    ).toBe(WorkflowNode.idea_interpretation);
    expect(resolveSelectedNode(LoopStage.related_work, "not-a-node", WorkflowNode.idea_interpretation)).toBe(
      WorkflowNode.research_inputs,
    );
    expect(resolveSelectedNode(LoopStage.spec_draft, WorkflowNode.gap, WorkflowNode.feasibility)).toBeUndefined();
    expect(
      resolveSelectedNode(
        LoopStage.independent_judges,
        WorkflowNode.gap_judge,
        WorkflowNode.aggregator,
      ),
    ).toBe(WorkflowNode.aggregator);
  });

  it("walks Back and Next across Workflow Nodes and nodeless Loop Stages", () => {
    const stops = navStops();
    expect(stops[0]).toEqual({ stage: LoopStage.grilling, node: WorkflowNode.idea_interpretation });
    expect(stops.at(-1)).toEqual({ stage: LoopStage.readiness });
    expect(adjacentStop({ stage: LoopStage.grilling, node: WorkflowNode.idea_interpretation }, -1)).toBeNull();
    expect(adjacentStop({ stage: LoopStage.experiment_planning, node: WorkflowNode.feasibility }, 1)).toEqual({
      stage: LoopStage.spec_draft,
    });
    expect(adjacentStop({ stage: LoopStage.spec_draft }, 1)).toEqual({
      stage: LoopStage.independent_judges,
    });
    expect(adjacentStop({ stage: LoopStage.readiness }, 1)).toBeNull();
  });

  it("builds session hrefs with node omitted on Spec Draft and Readiness", () => {
    expect(railStop(LoopStage.related_work)).toEqual({
      stage: LoopStage.related_work,
      node: WorkflowNode.research_inputs,
    });
    expect(railStop(LoopStage.spec_draft)).toEqual({ stage: LoopStage.spec_draft });
    expect(railStop(LoopStage.independent_judges)).toEqual({
      stage: LoopStage.independent_judges,
    });
    expect(sessionHref("session-1", workingDraftStop(WorkflowNode.claims))).toBe(
      `/sessions/session-1?stage=${LoopStage.claims_evidence}&node=${WorkflowNode.claims}`,
    );
    expect(sessionHref("session-1", { stage: LoopStage.readiness })).toBe(
      `/sessions/session-1?stage=${LoopStage.readiness}`,
    );
  });

  it("derives Contribution upstream from generated Workflow Node edges", () => {
    expect(ancestors(WorkflowNode.contribution)).toEqual(
      new Set([
        WorkflowNode.gap,
        WorkflowNode.related_work,
        WorkflowNode.research_inputs,
        WorkflowNode.idea_decomposition,
        WorkflowNode.idea_interpretation,
      ]),
    );
    expect(upstreamOfStage(LoopStage.grilling)).toEqual(new Set());
    expect(upstreamOfStage(LoopStage.related_work)).toEqual(
      new Set([WorkflowNode.idea_interpretation, WorkflowNode.idea_decomposition]),
    );
    expect(upstreamOfStage(LoopStage.gap)).toEqual(
      new Set([
        WorkflowNode.idea_interpretation,
        WorkflowNode.idea_decomposition,
        WorkflowNode.research_inputs,
        WorkflowNode.related_work,
      ]),
    );
    expect(upstreamOfStage(LoopStage.contribution)).toEqual(
      new Set([
        WorkflowNode.idea_interpretation,
        WorkflowNode.idea_decomposition,
        WorkflowNode.research_inputs,
        WorkflowNode.related_work,
        WorkflowNode.gap,
      ]),
    );
    expect(upstreamOfStage(LoopStage.spec_draft)).toEqual(new Set());
  });

  it("walks current descendants from the invalidation catalog", () => {
    expect(descendants(WorkflowNode.idea_interpretation)).toEqual(
      new Set(Object.values(WorkflowNode).filter((node) => node !== WorkflowNode.idea_interpretation)),
    );
    expect(descendants(WorkflowNode.aggregator)).toEqual(new Set());
  });

  it("maps every generated Card kind to one confirming Workflow Node", () => {
    expect(ownedCardKinds(WorkflowNode.idea_interpretation)).toEqual([]);
    expect(ownedCardKinds(WorkflowNode.idea_decomposition)).toEqual([
      CardKind.problem,
      CardKind.research_question,
      CardKind.constraint,
      CardKind.open_question,
    ]);
    expect(ownedCardKinds(WorkflowNode.gap)).toEqual([CardKind.gap]);
    expect(ownedCardKinds(WorkflowNode.contribution)).toEqual([CardKind.contribution]);
    expect(ownedCardKinds(WorkflowNode.claims)).toEqual([CardKind.claim]);
    expect(ownedCardKinds(WorkflowNode.evidence)).toEqual([CardKind.claim, CardKind.evidence]);
    expect(ownedCardKinds(WorkflowNode.experiment_plan)).toEqual([]);
  });
});
