import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { ExperimentPlanningStageContainer } from "./ExperimentPlanningStageContainer";

vi.mock("../loop/loop-session-save", () => ({
  useLoopSessionSave: () => ({
    queue: { enqueue: (mutation: () => Promise<unknown>) => mutation() },
    status: "idle",
  }),
}));

vi.mock("@/lib/api/generated/endpoints", () => ({
  getGetSessionApiLoopSessionsSessionIdGetQueryKey: (sessionId: string) => [
    "/api/loop/sessions",
    sessionId,
  ],
  useGenerateExperimentApiSpecSessionsSessionIdExperimentPlanGeneratePost: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useCheckFeasibilityApiSpecSessionsSessionIdFeasibilityCheckPost: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

function experimentSession(
  node: "experiment_plan" | "feasibility",
): LoopSessionResponse {
  return {
    id: "session-1",
    title: "Experiment test",
    version: 10,
    working_draft_node: node,
    working_draft_narrative: {
      plan: {
        experiments: [
          {
            claim: "Latency drops under load",
            action: "Run a 30-minute load test",
            objective: "Measure p95 latency",
            significance: "Shows the claim is practical",
          },
        ],
      },
    },
    node_heads: [],
    cards: [],
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-21T00:00:00Z",
    updated_at: "2026-08-21T00:00:00Z",
  };
}

describe("ExperimentPlanningStageContainer", () => {
  it("titles the panel Experiment plan on the experiment_plan Workflow Node", () => {
    const session = experimentSession(WorkflowNode.experiment_plan);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ExperimentPlanningStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Experiment plan")).toBeInTheDocument();
    expect(screen.queryByText("Experiment Planning & Feasibility")).not.toBeInTheDocument();
    const objectiveBox = screen.getByText("Measure p95 latency").closest(".flex-1");
    expect(objectiveBox).not.toBeNull();
    expect(objectiveBox?.className).not.toMatch(/\bh-full\b/);
  });

  it("titles the panel Feasibility on the feasibility Workflow Node", () => {
    const session = experimentSession(WorkflowNode.feasibility);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ExperimentPlanningStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Feasibility")).toBeInTheDocument();
    expect(screen.queryByText("Experiment Planning & Feasibility")).not.toBeInTheDocument();
  });
});
