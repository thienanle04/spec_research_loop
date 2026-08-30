import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NodeHeadStatus, WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { JudgementStageContainer } from "./JudgementStageContainer";

const mocks = vi.hoisted(() => ({
  streamStart: vi.fn(),
  streamStartPending: vi.fn(),
  abort: vi.fn(),
  running: false,
  customFetch: vi.fn(),
}));

vi.mock("../loop/loop-session-save", () => ({
  useLoopSessionSave: () => ({
    queue: {
      flush: () => Promise.resolve(),
      enqueue: (mutation: () => Promise<unknown>) => mutation(),
    },
    status: "idle",
  }),
}));

vi.mock("./useJudgementStream", () => ({
  useJudgementStream: () => ({
    running: mocks.running,
    progress: 0,
    progressMessage: mocks.running ? "Starting Gap Judge" : null,
    error: null,
    start: mocks.streamStart,
    startPending: mocks.streamStartPending,
    abort: mocks.abort,
  }),
}));

vi.mock("@/lib/api/mutator", () => ({
  customFetch: (...args: unknown[]) => mocks.customFetch(...args),
}));

vi.mock("@/lib/api/generated/endpoints", () => ({
  getGetSessionApiLoopSessionsSessionIdGetQueryKey: (sessionId: string) => [
    "/api/loop/sessions",
    sessionId,
  ],
}));

function session(
  node: WorkflowNode = WorkflowNode.gap_judge,
  nodeHeads: LoopSessionResponse["node_heads"] = [],
): LoopSessionResponse {
  return {
    id: "session-1",
    title: "Judgement test",
    version: 4,
    working_draft_node: node,
    working_draft_narrative: {},
    node_heads: nodeHeads,
    cards: [],
    produced_spec_version: null,
    valid_spec_version_id: "spec-1",
    created_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
  };
}

describe("JudgementStageContainer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.running = false;
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "gap_judge",
        issues: [
          {
            id: "issue-1",
            finding_kind: "gap_unsupported_by_sources",
            severity: "CRITICAL",
            reason: "No cited passage supports the gap statement.",
            suggestion: "Cite a supporting passage.",
            target_card_id: null,
          },
        ],
      },
    });
    mocks.streamStart.mockResolvedValue(undefined);
  });

  it("shows Gap Judge Issues instead of a raw narrative editor", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={session()} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Gap unsupported by sources")).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("No cited passage supports the gap statement.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("starts Gap Judge generate from the workbench action", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={session()} />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Regenerate Gap Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "gap_judge",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
  });

  it("sends stale re-accept only after the workbench Stale dialog requests generate", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const staleSession = session(WorkflowNode.gap_judge, [
      {
        node: WorkflowNode.gap_judge,
        status: NodeHeadStatus.stale,
        stage_revision_id: "rev-1",
        generated_since_prepare: false,
        head_revision: null,
      },
    ]);
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={staleSession} />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Regenerate Gap Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({ staleReaccept: false }),
    );
    mocks.streamStart.mockClear();
    rerender(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={staleSession}
          generateRequestId={1}
        />
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(mocks.streamStart).toHaveBeenCalledWith(
        expect.objectContaining({ staleReaccept: true }),
      ),
    );
  });

  it("shows Evidence Judge Issues and starts generate", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "evidence_judge",
        issues: [
          {
            id: "issue-2",
            finding_kind: "unsupported_citation",
            severity: "CRITICAL",
            reason: "The cited passage does not entail the claim.",
            suggestion: "Cite a passage that entails the claim.",
            target_card_id: null,
          },
        ],
      },
    });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.evidence_judge)}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Unsupported citation")).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("The cited passage does not entail the claim.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Regenerate Evidence Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "evidence_judge",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
  });

  it("shows Contribution Judge Issues and starts generate", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "contribution_judge",
        issues: [
          {
            id: "issue-3",
            finding_kind: "contribution_not_novel",
            severity: "MAJOR",
            reason: "Prior work already states this contribution.",
            suggestion: "Narrow the novelty claim.",
            target_card_id: null,
          },
        ],
      },
    });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.contribution_judge)}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Contribution not novel")).toBeInTheDocument();
    expect(screen.getByText("MAJOR")).toBeInTheDocument();
    expect(screen.getByText("Prior work already states this contribution.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Regenerate Contribution Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "contribution_judge",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
  });

  it("shows Experiment Judge Issues and starts generate", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "experiment_judge",
        issues: [
          {
            id: "issue-4",
            finding_kind: "claim_broader_than_experiment",
            severity: "MAJOR",
            reason: "The claim outruns the experiment plan.",
            suggestion: "Narrow the claim.",
            target_card_id: null,
          },
        ],
      },
    });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.experiment_judge)}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Claim broader than experiment")).toBeInTheDocument();
    expect(screen.getByText("MAJOR")).toBeInTheDocument();
    expect(screen.getByText("The claim outruns the experiment plan.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Regenerate Experiment Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "experiment_judge",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
  });

  it("shows Conference Judge criterion scores instead of Judge Issues", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "conference_judge",
        issues: [],
        scores: {
          originality: 7,
          significance: 8,
          soundness: 6,
          clarity: 9,
          reproducibility: 5,
        },
      },
    });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.conference_judge)}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Originality")).toBeInTheDocument();
    expect(screen.getByText("7/10")).toBeInTheDocument();
    expect(screen.getByText("Significance")).toBeInTheDocument();
    expect(screen.getByText("8/10")).toBeInTheDocument();
    expect(screen.getByText("Soundness")).toBeInTheDocument();
    expect(screen.getByText("6/10")).toBeInTheDocument();
    expect(screen.getByText("Clarity")).toBeInTheDocument();
    expect(screen.getByText("9/10")).toBeInTheDocument();
    expect(screen.getByText("Reproducibility")).toBeInTheDocument();
    expect(screen.getByText("5/10")).toBeInTheDocument();
    expect(screen.queryByLabelText("Judge Issues")).not.toBeInTheDocument();
    expect(screen.queryByText("No Judge Issues on this Judge Run.")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Regenerate Conference Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "conference_judge",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
  });

  it("shows Aggregator Report issues, disagreement, scores, and pickable Handling Options", async () => {
    mocks.customFetch.mockImplementation(async (path: unknown) => {
      if (typeof path === "string" && path.endsWith("/pick")) {
        return { status: 200, data: session(WorkflowNode.claims) };
      }
      return {
        status: 200,
        data: {
          node: "aggregator",
          issues: [
            {
              id: "issue-5",
              finding_kind: "unsupported_citation",
              severity: "CRITICAL",
              reason: "The cited passage does not entail the claim.",
              suggestion: "Cite a passage that entails the claim.",
              target_card_id: null,
              source_node: "evidence_judge",
              cluster: "disagreement",
            },
          ],
          scores: {
            originality: 7,
            significance: 8,
            soundness: 6,
            clarity: 7,
            reproducibility: 5,
          },
          handling_options: [
            {
              id: "opt-1",
              finding_kind: "unsupported_citation",
              source_node: "evidence_judge",
              label: "Revise the claim",
              target_node: "claims",
              prose: "Cite a passage that entails the claim.",
            },
          ],
          readiness: "blocked",
        },
      };
    });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator)}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Unsupported citation")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Disagreement" })).toBeInTheDocument();
    expect(screen.getByText("Revise the claim")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Pick Revise the claim" })).toBeInTheDocument();
    expect(screen.getByLabelText("Other prose")).toBeInTheDocument();
    expect(screen.getAllByText("7/10").length).toBeGreaterThanOrEqual(1);
    await user.click(await screen.findByRole("button", { name: "Regenerate Aggregator" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "aggregator",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
    mocks.streamStart.mockClear();
    await user.click(screen.getByRole("button", { name: "Pick Revise the claim" }));
    expect(mocks.customFetch).toHaveBeenCalledWith(
      "/api/loop/sessions/session-1/pick",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_version: 4,
          handling_option_id: "opt-1",
        }),
      }),
    );
    expect(mocks.streamStart).not.toHaveBeenCalled();
  });

  it("offers run pending Judges and abort", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const pendingHeads: LoopSessionResponse["node_heads"] = [
      {
        node: WorkflowNode.gap_judge,
        status: NodeHeadStatus.empty,
        stage_revision_id: null,
        generated_since_prepare: false,
        head_revision: null,
      },
      {
        node: WorkflowNode.contribution_judge,
        status: NodeHeadStatus.empty,
        stage_revision_id: null,
        generated_since_prepare: false,
        head_revision: null,
      },
      {
        node: WorkflowNode.aggregator,
        status: NodeHeadStatus.empty,
        stage_revision_id: null,
        generated_since_prepare: false,
        head_revision: null,
      },
    ];
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.gap_judge, pendingHeads)}
        />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Run pending Judges" }));
    expect(mocks.streamStartPending).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
    expect(mocks.streamStart).not.toHaveBeenCalled();
  });

  it("sends batch Stale re-accept on run pending when a targeted Judge is Stale", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.experiment_judge, [
            {
              node: WorkflowNode.gap_judge,
              status: NodeHeadStatus.current,
              stage_revision_id: "rev-gap",
              generated_since_prepare: false,
              head_revision: null,
            },
            {
              node: WorkflowNode.experiment_judge,
              status: NodeHeadStatus.stale,
              stage_revision_id: "rev-exp",
              generated_since_prepare: false,
              head_revision: null,
            },
            {
              node: WorkflowNode.conference_judge,
              status: NodeHeadStatus.stale,
              stage_revision_id: "rev-conf",
              generated_since_prepare: false,
              head_revision: null,
            },
            {
              node: WorkflowNode.aggregator,
              status: NodeHeadStatus.stale,
              stage_revision_id: "rev-agg",
              generated_since_prepare: false,
              head_revision: null,
            },
          ])}
        />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Run pending Judges" }));
    expect(mocks.streamStartPending).toHaveBeenCalledWith(
      expect.objectContaining({ staleReaccept: true }),
    );
  });

  it("aborts run pending from Independent judges", async () => {
    mocks.running = true;
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={session()} />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Stop Judge" }));
    expect(mocks.abort).toHaveBeenCalled();
  });
});
