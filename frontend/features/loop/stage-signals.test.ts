import { describe, expect, it } from "vitest";

import { CardKind, LoopStage, NodeHeadStatus, WorkflowNode } from "@/lib/api/generated/model";
import type { NodeHeadResponse } from "@/lib/api/generated/model";

import {
  deriveStageActions,
  deriveStageSignals,
  hasConfirmableWorkingDraft,
  incompleteUpstreamNodes,
  isInvalidationSubjectDismissed,
  needsStaleReaccept,
  shouldAutoPrepare,
  shouldDimStaleContent,
  specInvalidationInView,
  staleInvalidationStages,
  withGeneratedSincePrepare,
} from "./stage-signals";

function heads(
  overrides: Partial<Record<WorkflowNode, NodeHeadStatus>> = {},
): NodeHeadResponse[] {
  return Object.values(WorkflowNode).map((node) => ({
    node,
    status: overrides[node] ?? NodeHeadStatus.empty,
    stage_revision_id: null,
    generated_since_prepare: false,
    head_revision: null,
  }));
}

describe("Loop Stage signals", () => {
  it("marks Grilling as needs work when both Node Heads are empty", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.grilling,
        nodeHeads: heads(),
        workingDraftNode: WorkflowNode.idea_interpretation,
      }),
    ).toEqual({
      completion: "needs_work",
      editing: true,
      available: true,
    });
  });

  it("marks Grilling as needs work when interpretation is current and decomposition is empty", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.grilling,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.idea_decomposition,
      }),
    ).toEqual({
      completion: "needs_work",
      editing: true,
      available: true,
    });
  });

  it("marks Grilling complete when both Node Heads are current", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.grilling,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.research_inputs,
      }),
    ).toEqual({
      completion: "complete",
      editing: false,
      available: true,
    });
  });

  it("keeps Complete and Editing independent when a current Grilling node is the Working Draft", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.grilling,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.idea_interpretation,
      }),
    ).toEqual({
      completion: "complete",
      editing: true,
      available: true,
    });
  });

  it("marks Grilling stale when any Node Head is stale, even if the other is current", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.grilling,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.stale,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.idea_interpretation,
      }),
    ).toEqual({
      completion: "stale",
      editing: true,
      available: true,
    });
  });

  it("marks Grilling stale when Node Heads mix empty and stale", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.grilling,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.empty,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.stale,
        }),
        workingDraftNode: WorkflowNode.idea_decomposition,
      }),
    ).toEqual({
      completion: "stale",
      editing: true,
      available: true,
    });
  });

  it("does not treat Related work as available while Grilling Node Heads are incomplete", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.related_work,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.idea_decomposition,
      }),
    ).toEqual({
      completion: "needs_work",
      editing: false,
      available: false,
    });
  });

  it("makes Related work available only after both Grilling Node Heads are current", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.related_work,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.research_inputs,
      }),
    ).toEqual({
      completion: "needs_work",
      editing: true,
      available: true,
    });
  });

  it("marks Related work stale from a stale Node Head among its own Workflow Nodes", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.related_work,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          [WorkflowNode.related_work]: NodeHeadStatus.stale,
          [WorkflowNode.gap]: NodeHeadStatus.empty,
        }),
        workingDraftNode: WorkflowNode.related_work,
      }),
    ).toEqual({
      completion: "stale",
      editing: true,
      available: true,
    });
  });

  it("attaches a stale gap Node Head to Gap, not Related work", () => {
    const nodeHeads = heads({
      [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
      [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
      [WorkflowNode.research_inputs]: NodeHeadStatus.current,
      [WorkflowNode.related_work]: NodeHeadStatus.current,
      [WorkflowNode.gap]: NodeHeadStatus.stale,
    });
    expect(
      deriveStageSignals({
        stage: LoopStage.related_work,
        nodeHeads,
        workingDraftNode: WorkflowNode.related_work,
      }),
    ).toEqual({
      completion: "complete",
      editing: true,
      available: true,
    });
    expect(
      deriveStageSignals({
        stage: LoopStage.gap,
        nodeHeads,
        workingDraftNode: WorkflowNode.gap,
      }),
    ).toEqual({
      completion: "stale",
      editing: true,
      available: true,
    });
  });

  it("displays Spec Draft as Not evaluated with no completion proxy", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.spec_draft,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.idea_decomposition,
      }),
    ).toEqual({
      completion: "not_evaluated",
      editing: false,
      available: true,
    });
  });

  it("displays Readiness as Not evaluated with no completion proxy", () => {
    expect(
      deriveStageSignals({
        stage: LoopStage.readiness,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        }),
        workingDraftNode: WorkflowNode.idea_decomposition,
      }),
    ).toEqual({
      completion: "not_evaluated",
      editing: false,
      available: true,
    });
  });

  it("displays Readiness as blocked or ready from the Aggregator Report", () => {
    const nodeHeads = heads({
      [WorkflowNode.aggregator]: NodeHeadStatus.current,
    });
    expect(
      deriveStageSignals({
        stage: LoopStage.readiness,
        nodeHeads,
        workingDraftNode: WorkflowNode.aggregator,
        readinessState: "blocked",
      }),
    ).toEqual({
      completion: "blocked",
      editing: false,
      available: true,
    });
    expect(
      deriveStageSignals({
        stage: LoopStage.readiness,
        nodeHeads,
        workingDraftNode: WorkflowNode.aggregator,
        readinessState: "ready",
      }),
    ).toEqual({
      completion: "ready",
      editing: false,
      available: true,
    });
  });

  it("lists incomplete upstream Workflow Nodes for an unavailable Loop Stage", () => {
    expect(
      incompleteUpstreamNodes({
        stage: LoopStage.related_work,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        }),
      }),
    ).toEqual([WorkflowNode.idea_decomposition]);
    expect(
      new Set(
        incompleteUpstreamNodes({
          stage: LoopStage.gap,
          nodeHeads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      ),
    ).toEqual(new Set([WorkflowNode.research_inputs, WorkflowNode.related_work]));
  });
});

describe("Loop Stage actions", () => {
  it("does not offer Start or Recompute on Spec Draft", () => {
    expect(
      deriveStageActions({
        stage: LoopStage.spec_draft,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        }),
      }),
    ).toEqual({ canStart: false, canRecompute: false, editableNodes: [] });
  });

  it("starts Gap when Related work Node Heads are current", () => {
    expect(
      deriveStageActions({
        stage: LoopStage.gap,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          [WorkflowNode.related_work]: NodeHeadStatus.current,
        }),
      }),
    ).toEqual({ canStart: true, canRecompute: false, editableNodes: [] });
  });

  it("does not start Related work when only Gap is empty", () => {
    expect(
      deriveStageActions({
        stage: LoopStage.related_work,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          [WorkflowNode.related_work]: NodeHeadStatus.current,
          [WorkflowNode.gap]: NodeHeadStatus.empty,
        }),
      }),
    ).toEqual({
      canStart: false,
      canRecompute: false,
      editableNodes: [WorkflowNode.research_inputs, WorkflowNode.related_work],
    });
  });
});

describe("shouldAutoPrepare", () => {
  const grillingCurrent = {
    [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
    [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
  };

  it("prepares an empty node when the Working Draft is current in another Loop Stage", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.related_work,
        selectedNode: WorkflowNode.research_inputs,
        workingDraftNode: WorkflowNode.idea_decomposition,
        nodeHeads: heads(grillingCurrent),
      }),
    ).toBe(true);
  });

  it("prepares a Stale node when the Working Draft is current in another Loop Stage", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.related_work,
        selectedNode: WorkflowNode.related_work,
        workingDraftNode: WorkflowNode.contribution,
        nodeHeads: heads({
          ...grillingCurrent,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          [WorkflowNode.related_work]: NodeHeadStatus.stale,
          [WorkflowNode.gap]: NodeHeadStatus.current,
          [WorkflowNode.contribution]: NodeHeadStatus.current,
        }),
      }),
    ).toBe(true);
  });

  it("does not prepare a current Node Head in a mixed Loop Stage", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.related_work,
        selectedNode: WorkflowNode.research_inputs,
        workingDraftNode: WorkflowNode.contribution,
        nodeHeads: heads({
          ...grillingCurrent,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          [WorkflowNode.related_work]: NodeHeadStatus.stale,
          [WorkflowNode.gap]: NodeHeadStatus.current,
          [WorkflowNode.contribution]: NodeHeadStatus.current,
        }),
      }),
    ).toBe(false);
  });

  it("does not prepare Spec Draft or a missing Workflow Node", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.spec_draft,
        selectedNode: undefined,
        workingDraftNode: WorkflowNode.feasibility,
        nodeHeads: heads(grillingCurrent),
      }),
    ).toBe(false);
  });

  it("does not prepare an unavailable Loop Stage", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.related_work,
        selectedNode: WorkflowNode.research_inputs,
        workingDraftNode: WorkflowNode.idea_interpretation,
        nodeHeads: heads(),
      }),
    ).toBe(false);
  });

  it("does not prepare the Working Draft already on that empty or Stale node", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.related_work,
        selectedNode: WorkflowNode.research_inputs,
        workingDraftNode: WorkflowNode.research_inputs,
        nodeHeads: heads({
          ...grillingCurrent,
          [WorkflowNode.research_inputs]: NodeHeadStatus.empty,
        }),
      }),
    ).toBe(false);
    expect(
      shouldAutoPrepare({
        stage: LoopStage.grilling,
        selectedNode: WorkflowNode.idea_decomposition,
        workingDraftNode: WorkflowNode.idea_decomposition,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.stale,
        }),
      }),
    ).toBe(false);
  });

  it("does not prepare when the Working Draft is not current", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.grilling,
        selectedNode: WorkflowNode.idea_decomposition,
        workingDraftNode: WorkflowNode.idea_interpretation,
        nodeHeads: heads(),
      }),
    ).toBe(false);
  });

  it("does not prepare while the Working Draft is a current node in the same Loop Stage", () => {
    expect(
      shouldAutoPrepare({
        stage: LoopStage.grilling,
        selectedNode: WorkflowNode.idea_decomposition,
        workingDraftNode: WorkflowNode.idea_interpretation,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.empty,
        }),
      }),
    ).toBe(false);
    expect(
      shouldAutoPrepare({
        stage: LoopStage.grilling,
        selectedNode: WorkflowNode.idea_decomposition,
        workingDraftNode: WorkflowNode.idea_interpretation,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.stale,
        }),
      }),
    ).toBe(false);
  });
});

describe("Confirm signals", () => {
  it("warns only when reconfirming a current Workflow Node with current descendants", () => {
    expect(
      staleInvalidationStages({
        node: WorkflowNode.idea_interpretation,
        nodeHeads: heads(),
      }),
    ).toEqual([]);
    expect(
      staleInvalidationStages({
        node: WorkflowNode.idea_interpretation,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        }),
      }),
    ).toEqual([]);
    expect(
      staleInvalidationStages({
        node: WorkflowNode.idea_interpretation,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        }),
      }),
    ).toEqual([LoopStage.grilling, LoopStage.related_work]);
    expect(
      staleInvalidationStages({
        node: WorkflowNode.idea_interpretation,
        nodeHeads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          [WorkflowNode.related_work]: NodeHeadStatus.current,
          [WorkflowNode.gap]: NodeHeadStatus.current,
        }),
      }),
    ).toEqual([LoopStage.grilling, LoopStage.related_work, LoopStage.gap]);
  });

  it("treats nonblank narrative text or a nonblank owned Card as confirmable", () => {
    expect(
      hasConfirmableWorkingDraft({
        working_draft_node: WorkflowNode.idea_interpretation,
        working_draft_narrative: { text: "   " },
        cards: [
          {
            id: "card-1",
            kind: CardKind.problem,
            body: { text: "owned by decomposition" },
            created_at: "2026-08-15T10:00:00Z",
            updated_at: "2026-08-15T10:00:00Z",
          },
        ],
      }),
    ).toBe(false);
    expect(
      hasConfirmableWorkingDraft({
        working_draft_node: WorkflowNode.idea_interpretation,
        working_draft_narrative: { text: "Latency in GPU kernels" },
        cards: [],
      }),
    ).toBe(false);
    expect(
      hasConfirmableWorkingDraft({
        working_draft_node: WorkflowNode.idea_interpretation,
        working_draft_narrative: {
          exhausted: true,
          frame: {
            intent: "You want to reduce GPU kernel latency.",
            problem: "Latency in GPU kernels",
            research_question: "Can tiling help?",
          },
          turns: [
            { role: "account", kind: "idea", text: "Latency in GPU kernels" },
            { role: "model", preamble: "Done.", questions: [] },
          ],
        },
        cards: [],
      }),
    ).toBe(true);
    expect(
      hasConfirmableWorkingDraft({
        working_draft_node: WorkflowNode.idea_decomposition,
        working_draft_narrative: {},
        cards: [
          {
            id: "card-1",
            kind: CardKind.problem,
            body: { text: "Memory bandwidth" },
            created_at: "2026-08-15T10:00:00Z",
            updated_at: "2026-08-15T10:00:00Z",
          },
        ],
      }),
    ).toBe(true);
  });
});

describe("Stale re-accept flag", () => {
  it("clears needsStaleReaccept after withGeneratedSincePrepare", () => {
    const nodeHeads = heads({
      [WorkflowNode.contribution]: NodeHeadStatus.stale,
    });
    const head = nodeHeads.find((item) => item.node === WorkflowNode.contribution);
    expect(needsStaleReaccept(head)).toBe(true);

    const updated = withGeneratedSincePrepare({
      id: "session-1",
      title: "t",
      version: 1,
      working_draft_node: WorkflowNode.contribution,
      working_draft_narrative: {},
      node_heads: nodeHeads,
      cards: [],
      produced_spec_version: null,
      valid_spec_version_id: null,
      created_at: "2026-08-15T10:00:00Z",
      updated_at: "2026-08-15T10:00:00Z",
    });
    const marked = updated.node_heads.find((item) => item.node === WorkflowNode.contribution);
    expect(marked?.generated_since_prepare).toBe(true);
    expect(needsStaleReaccept(marked)).toBe(false);
  });

  it("dims only when re-accept is needed and the invalidation banner is visible", () => {
    const stale = heads({ [WorkflowNode.contribution]: NodeHeadStatus.stale }).find(
      (item) => item.node === WorkflowNode.contribution,
    );
    expect(shouldDimStaleContent(stale, true)).toBe(true);
    expect(shouldDimStaleContent(stale, false)).toBe(false);
    expect(shouldDimStaleContent({ ...stale!, generated_since_prepare: true }, true)).toBe(false);
  });

  it("tracks Spec Draft invalidation in view and per-subject dismiss against the wave key", () => {
    expect(
      specInvalidationInView({
        selectedNode: WorkflowNode.idea_decomposition,
        selectedStage: LoopStage.grilling,
        viewedNodeStale: true,
        specVersionStale: true,
      }),
    ).toBe(true);
    expect(
      specInvalidationInView({
        selectedNode: WorkflowNode.idea_decomposition,
        selectedStage: LoopStage.grilling,
        viewedNodeStale: false,
        specVersionStale: true,
      }),
    ).toBe(false);
    expect(
      specInvalidationInView({
        selectedNode: undefined,
        selectedStage: LoopStage.spec_draft,
        viewedNodeStale: false,
        specVersionStale: true,
      }),
    ).toBe(true);

    const wave = "idea_decomposition|spec:1";
    expect(
      isInvalidationSubjectDismissed(WorkflowNode.idea_decomposition, wave, {
        [WorkflowNode.idea_decomposition]: wave,
      }),
    ).toBe(true);
    expect(
      isInvalidationSubjectDismissed(WorkflowNode.idea_interpretation, wave, {
        [WorkflowNode.idea_decomposition]: wave,
      }),
    ).toBe(false);
    expect(
      isInvalidationSubjectDismissed("spec_draft", wave, { spec_draft: wave }),
    ).toBe(true);
    expect(
      isInvalidationSubjectDismissed("spec_draft", wave, { spec_draft: "other-wave" }),
    ).toBe(false);
  });
});
