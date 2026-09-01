import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NodeHeadStatus, WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { needsStaleReaccept } from "@/features/loop/stage-signals";

import { ExperimentPlanStageContainer } from "./ExperimentPlanStageContainer";
import { FeasibilityStageContainer } from "./FeasibilityStageContainer";

const mocks = vi.hoisted(() => ({
  checkFeasibility: vi.fn(),
}));

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
    mutateAsync: mocks.checkFeasibility,
    isPending: false,
  }),
}));

function experimentSession(
  node: "experiment_plan" | "feasibility",
  overrides: Partial<LoopSessionResponse> = {},
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
      feasibility_report: {
        is_feasible: true,
        required_resources: [],
        potential_bottlenecks: [],
        mitigation_strategies: [],
        conclusion: "ok",
      },
    },
    node_heads: Object.values(WorkflowNode).map((workflowNode) => ({
      node: workflowNode,
      status:
        workflowNode === WorkflowNode.feasibility
          ? NodeHeadStatus.stale
          : NodeHeadStatus.current,
      stage_revision_id: null,
      generated_since_prepare: false,
      head_revision: null,
    })),
    cards: [],
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-21T00:00:00Z",
    updated_at: "2026-08-21T00:00:00Z",
    ...overrides,
  };
}

describe("ExperimentPlanStageContainer", () => {
  it("titles the panel Experiment plan on the experiment_plan Workflow Node", () => {
    const session = experimentSession(WorkflowNode.experiment_plan);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ExperimentPlanStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Experiment plan")).toBeInTheDocument();
    expect(screen.queryByText("Experiment Planning & Feasibility")).not.toBeInTheDocument();
    const objectiveBox = screen.getByText("Measure p95 latency").closest(".flex-1");
    expect(objectiveBox).not.toBeNull();
    expect(objectiveBox?.className).not.toMatch(/\bh-full\b/);
  });
});

describe("FeasibilityStageContainer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.checkFeasibility.mockResolvedValue({
      status: 200,
      data: {
        version: 11,
        report: {
          is_feasible: true,
          required_resources: ["1× A100"],
          potential_bottlenecks: [],
          mitigation_strategies: [],
          conclusion: "ok",
        },
      },
    });
  });

  it("titles the panel Feasibility on the feasibility Workflow Node", () => {
    const session = experimentSession(WorkflowNode.feasibility);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <FeasibilityStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Feasibility")).toBeInTheDocument();
    expect(screen.queryByText("Experiment Planning & Feasibility")).not.toBeInTheDocument();
  });

  it("marks generated_since_prepare after Re-check Feasibility", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const session = experimentSession(WorkflowNode.feasibility);
    queryClient.setQueryData(["/api/loop/sessions", session.id], {
      status: 200,
      data: session,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <FeasibilityStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    expect(
      needsStaleReaccept(
        session.node_heads.find((head) => head.node === WorkflowNode.feasibility),
      ),
    ).toBe(true);

    await user.click(screen.getByRole("button", { name: "Re-check Feasibility" }));
    await waitFor(() => expect(mocks.checkFeasibility).toHaveBeenCalled());

    const cached = queryClient.getQueryData(["/api/loop/sessions", session.id]) as {
      status: number;
      data: LoopSessionResponse;
    };
    const feasibilityHead = cached.data.node_heads.find(
      (head) => head.node === WorkflowNode.feasibility,
    );
    expect(feasibilityHead?.generated_since_prepare).toBe(true);
    expect(needsStaleReaccept(feasibilityHead)).toBe(false);
  });
});
