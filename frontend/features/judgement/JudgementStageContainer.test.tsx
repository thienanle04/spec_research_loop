import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NodeHeadStatus, WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { JudgementStageContainer, JudgeRunRevisionView } from "./JudgementStageContainer";

const mocks = vi.hoisted(() => ({
  streamStart: vi.fn(),
  streamStartPending: vi.fn(),
  abort: vi.fn(),
  running: false,
  progressMessage: null as string | null,
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
    progressMessage: mocks.progressMessage,
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

function emptyIndependentJudgesHeads(): LoopSessionResponse["node_heads"] {
  return [
    WorkflowNode.gap_judge,
    WorkflowNode.contribution_judge,
    WorkflowNode.evidence_judge,
    WorkflowNode.experiment_judge,
    WorkflowNode.conference_judge,
    WorkflowNode.aggregator,
  ].map((node) => ({
    node,
    status: NodeHeadStatus.empty,
    stage_revision_id: null,
    generated_since_prepare: false,
    head_revision: null,
  }));
}

function currentIndependentJudgesHeads(): LoopSessionResponse["node_heads"] {
  return emptyIndependentJudgesHeads().map((head) =>
    head.node === WorkflowNode.aggregator
      ? head
      : {
          ...head,
          status: NodeHeadStatus.current,
          stage_revision_id: `rev-${head.node}`,
        },
  );
}

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
    mocks.progressMessage = null;
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

  it("shows compact empty Judge heads and the Aggregator panel without starting generate", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [],
        handling_options: [],
        scores: null,
      },
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, emptyIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    const heads = await screen.findByRole("list", { name: "Judge Node Heads" });
    const gap = within(heads).getByRole("listitem", { name: "Gap Judge" });
    expect(gap).toHaveTextContent("Gap Judge");
    expect(gap).toHaveTextContent("Check whether the gap is actually supported by the literature.");
    expect(within(heads).getByRole("listitem", { name: "Contribution Judge" })).toHaveTextContent(
      "Contribution Judge",
    );
    expect(within(heads).getByRole("listitem", { name: "Contribution Judge" })).toHaveTextContent(
      "Check whether the contribution is new, clear, and overstated.",
    );
    expect(within(heads).getByRole("listitem", { name: "Evidence Judge" })).toHaveTextContent(
      "Evidence Judge",
    );
    expect(within(heads).getByRole("listitem", { name: "Evidence Judge" })).toHaveTextContent(
      "Check whether citations actually support the accompanying content.",
    );
    expect(within(heads).getByRole("listitem", { name: "Experiment Judge" })).toHaveTextContent(
      "Experiment Judge",
    );
    expect(within(heads).getByRole("listitem", { name: "Experiment Judge" })).toHaveTextContent(
      "Check whether the experiments are sufficient to support the claim.",
    );
    expect(within(heads).getByRole("listitem", { name: "Conference Judge" })).toHaveTextContent(
      "Conference Judge",
    );
    expect(within(heads).getByRole("listitem", { name: "Conference Judge" })).toHaveTextContent(
      "Evaluate originality, significance, soundness, clarity, and reproducibility.",
    );
    expect(within(heads).getByText("Gap Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Contribution Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Evidence Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Experiment Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Conference Judge")).toBeInTheDocument();
    const name = within(gap).getByText("Gap Judge");
    const status = within(gap).getByText("None");
    expect(name.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(heads).getAllByText("None")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: "Generate Gap Judge" })).not.toBeInTheDocument();
    const runButton = screen.getByRole("button", { name: "Run evaluation" });
    expect(runButton).toHaveClass("w-full");
    expect(heads.compareDocumentPosition(runButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const consensus = screen.getByRole("region", { name: "Consensus" });
    expect(runButton.compareDocumentPosition(consensus) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/Aggregator copies Judge Issues/)).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Workflow Nodes" })).not.toBeInTheDocument();
    expect(mocks.streamStart).not.toHaveBeenCalled();
    expect(mocks.streamStartPending).not.toHaveBeenCalled();
  });

  it("shows compact Judge heads instead of a raw narrative editor", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={session()} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("list", { name: "Judge Node Heads" })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Gap Judge" })).toBeInTheDocument();
    expect(screen.getByText("Gap Judge")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Working Draft/i })).not.toBeInTheDocument();
  });

  it("does not offer Generate Aggregator or Regenerate Aggregator", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [],
        handling_options: [],
        scores: null,
      },
    });
    const emptyClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { unmount } = render(
      <QueryClientProvider client={emptyClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, emptyIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("list", { name: "Judge Node Heads" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate Aggregator" })).not.toBeInTheDocument();
    unmount();

    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
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
    const reportClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={reportClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, currentIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("list", { name: "Judge Node Heads" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Regenerate Aggregator" })).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.streamStart).not.toHaveBeenCalled());
  });

  it("starts Aggregator generate when five Judge heads are current and Aggregator is empty", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [],
        handling_options: [],
        scores: null,
      },
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, currentIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(mocks.streamStart).toHaveBeenCalledWith(
        expect.objectContaining({
          node: WorkflowNode.aggregator,
          staleReaccept: false,
        }),
      ),
    );
  });

  it("starts Aggregator generate with Stale re-accept when five Judge heads are current and Aggregator is Stale", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [],
        handling_options: [],
        scores: null,
      },
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const staleAggregatorHeads = currentIndependentJudgesHeads().map((head) =>
      head.node === WorkflowNode.aggregator
        ? {
            ...head,
            status: NodeHeadStatus.stale,
            stage_revision_id: "rev-aggregator",
            generated_since_prepare: false,
          }
        : head,
    );
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, staleAggregatorHeads)}
        />
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(mocks.streamStart).toHaveBeenCalledWith(
        expect.objectContaining({
          node: WorkflowNode.aggregator,
          staleReaccept: true,
        }),
      ),
    );
  });

  it("does not start Aggregator generate when Judge heads are not current", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const staleSession = session(WorkflowNode.aggregator, [
      {
        node: WorkflowNode.aggregator,
        status: NodeHeadStatus.stale,
        stage_revision_id: "rev-1",
        generated_since_prepare: false,
        head_revision: null,
      },
    ]);
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={staleSession} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("list", { name: "Judge Node Heads" })).toBeInTheDocument();
    await waitFor(() => expect(mocks.streamStart).not.toHaveBeenCalled());
  });

  it("shows Evidence Judge compact head on the Aggregator dashboard", async () => {
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
    expect(await screen.findByRole("listitem", { name: "Evidence Judge" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Judge Node Heads" })).toBeInTheDocument();
    expect(mocks.streamStart).not.toHaveBeenCalled();
  });

  it("shows Contribution Judge compact head on the Aggregator dashboard", async () => {
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
    expect(await screen.findByRole("listitem", { name: "Contribution Judge" })).toBeInTheDocument();
    expect(mocks.streamStart).not.toHaveBeenCalled();
  });

  it("shows Experiment Judge compact head on the Aggregator dashboard", async () => {
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
    expect(await screen.findByRole("listitem", { name: "Experiment Judge" })).toBeInTheDocument();
    expect(mocks.streamStart).not.toHaveBeenCalled();
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
    expect(mocks.streamStart).not.toHaveBeenCalled();
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
              grounds: {
                subject: "Brass instruments improve soil nitrogen fixation.",
                excerpts: [
                  {
                    citation_key: "large-language-models-as-optimizers-2023",
                    passage: "An optimizer model proposes prompts.",
                  },
                ],
              },
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
    expect(screen.getByLabelText("Originating Judge")).toHaveTextContent("Evidence Judge");
    expect(screen.getByText("Brass instruments improve soil nitrogen fixation.")).toBeInTheDocument();
    expect(screen.getByText("large-language-models-as-optimizers-2023")).toBeInTheDocument();
    expect(screen.getByText("An optimizer model proposes prompts.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Disagreement" })).toBeInTheDocument();
    expect(screen.getByText("Revise the claim")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Pick Revise the claim" })).toBeInTheDocument();
    expect(screen.getByLabelText("Other prose")).toBeInTheDocument();
    expect(screen.getAllByText("7/10").length).toBeGreaterThanOrEqual(1);
    expect(mocks.streamStart).not.toHaveBeenCalled();
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
    await user.click(await screen.findByRole("button", { name: "Run evaluation" }));
    expect(mocks.streamStartPending).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
    expect(mocks.streamStart).not.toHaveBeenCalled();
  });

  it("updates compact heads per run-pending SSE node then invalidates the session", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    let finish: (() => void) | undefined;
    let emit: ((event: unknown) => void) | undefined;
    mocks.streamStartPending.mockImplementation(
      (options: { onEvent?: (event: unknown) => void }) => {
        emit = options.onEvent;
        return new Promise<void>((resolve) => {
          finish = resolve;
        });
      },
    );
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [],
        handling_options: [],
        scores: null,
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, emptyIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Run evaluation" }));
    const heads = screen.getByRole("list", { name: "Judge Node Heads" });
    emit?.({
      type: "progress",
      node: "gap_judge",
      message: "Starting Gap Judge",
      pct: 0,
    });
    const gap = within(heads).getByRole("listitem", { name: "Gap Judge" });
    await waitFor(() =>
      expect(within(gap).getByText("Evaluating")).toBeInTheDocument(),
    );
    emit?.({
      type: "draft_patch",
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
    });
    emit?.({ type: "done", node: "gap_judge", version: 5 });
    await waitFor(() =>
      expect(within(gap).getByText("Done")).toBeInTheDocument(),
    );
    expect(within(gap).queryByText(/1 CRITICAL/)).not.toBeInTheDocument();
    emit?.({
      type: "progress",
      node: "contribution_judge",
      message: "Starting Contribution Judge",
      pct: 0,
    });
    const contribution = within(heads).getByRole("listitem", { name: "Contribution Judge" });
    await waitFor(() =>
      expect(within(contribution).getByText("Evaluating")).toBeInTheDocument(),
    );
    emit?.({
      type: "draft_patch",
      node: "contribution_judge",
      issues: [],
    });
    emit?.({ type: "done", node: "contribution_judge", version: 5 });
    await waitFor(() =>
      expect(within(contribution).getByText("Done")).toBeInTheDocument(),
    );
    emit?.({
      type: "draft_patch",
      node: "conference_judge",
      issues: [],
      scores: {
        originality: 7,
        significance: 8,
        soundness: 6,
        clarity: 9,
        reproducibility: 5,
      },
    });
    emit?.({ type: "done", node: "conference_judge", version: 5 });
    const conference = within(heads).getByRole("listitem", { name: "Conference Judge" });
    await waitFor(() =>
      expect(within(conference).getByText("Done")).toBeInTheDocument(),
    );
    expect(within(conference).queryByText("7/10")).not.toBeInTheDocument();
    expect(within(gap).getByText("Done")).toBeInTheDocument();
    emit?.({
      type: "draft_patch",
      node: "aggregator",
      issues: [
        {
          id: "issue-agg",
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
        clarity: 9,
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
    });
    emit?.({ type: "done", node: "aggregator", version: 6 });
    expect(await screen.findByText("Unsupported citation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pick Revise the claim" })).toBeInTheDocument();
    finish?.();
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ["/api/loop/sessions", "session-1"] }),
      ),
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
    await user.click(await screen.findByRole("button", { name: "Run evaluation" }));
    expect(mocks.streamStartPending).toHaveBeenCalledWith(
      expect.objectContaining({ staleReaccept: true }),
    );
  });

  it("does not call abort Stop Judge while generate is running", async () => {
    mocks.running = true;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={session()} />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("button", { name: "Stop Judge" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop generation" })).toBeInTheDocument();
    expect(screen.queryByText("Running Judge…")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Generating…");
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
    await user.click(await screen.findByRole("button", { name: "Stop generation" }));
    expect(mocks.abort).toHaveBeenCalled();
  });

  it("does not offer per-head Generate; Run pending is the only generate", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: { node: "aggregator", issues: [], handling_options: [], scores: null },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, emptyIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: "Run evaluation" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate Gap Judge" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate Conference Judge" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run evaluation" }));
    expect(mocks.streamStartPending).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
    expect(mocks.streamStart).not.toHaveBeenCalled();
  });

  it("hides Run pending when five Judge heads are current and keeps scores off the chips", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [
          {
            id: "issue-old",
            finding_kind: "unsupported_citation",
            severity: "CRITICAL",
            reason: "The cited passage does not entail the claim.",
            suggestion: "Cite a passage that entails the claim.",
            target_card_id: null,
            source_node: "evidence_judge",
            cluster: "disagreement",
          },
        ],
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
        scores: {
          originality: 7,
          significance: 8,
          soundness: 6,
          clarity: 7,
          reproducibility: 5,
        },
      },
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const dashboard = session(WorkflowNode.aggregator, currentIndependentJudgesHeads());
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={dashboard} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Revise the claim")).toBeInTheDocument();
    const heads = screen.getByRole("list", { name: "Judge Node Heads" });
    expect(within(heads).getAllByText("Done")).toHaveLength(5);
    expect(within(heads).queryByText("current")).not.toBeInTheDocument();
    expect(within(heads).queryByText("7/10")).not.toBeInTheDocument();
    expect(screen.getAllByText("7/10").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByRole("button", { name: "Run evaluation" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Regenerate Evidence Judge" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Regenerate Gap Judge" })).not.toBeInTheDocument();
    expect(dashboard.working_draft_node).toBe(WorkflowNode.aggregator);
  });

  it("shows stale on a Stale compact head and Run pending sends Stale re-accept without a dialog", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const staleHeads: LoopSessionResponse["node_heads"] = emptyIndependentJudgesHeads().map((head) =>
      head.node === WorkflowNode.gap_judge
        ? {
            ...head,
            status: NodeHeadStatus.stale,
            stage_revision_id: "rev-gap",
            generated_since_prepare: false,
          }
        : head,
    );
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, staleHeads)}
        />
      </QueryClientProvider>,
    );
    const gap = await screen.findByRole("listitem", { name: "Gap Judge" });
    expect(within(gap).getByText("Stale")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Stale Workflow Node" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run evaluation" }));
    expect(mocks.streamStart).not.toHaveBeenCalled();
    expect(mocks.streamStartPending).toHaveBeenCalledWith(
      expect.objectContaining({ staleReaccept: true }),
    );
  });

  it("signals Confirm only when Working Draft Aggregator has a working report", async () => {
    const onConfirmabilityChange = vi.fn();
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [],
        handling_options: [],
        scores: null,
      },
    });
    const user = userEvent.setup();
    let emit: ((event: unknown) => void) | undefined;
    mocks.streamStartPending.mockImplementation(
      (options: { onEvent?: (event: unknown) => void }) => {
        emit = options.onEvent;
        return Promise.resolve();
      },
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, emptyIndependentJudgesHeads())}
          onConfirmabilityChange={onConfirmabilityChange}
        />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(onConfirmabilityChange).toHaveBeenCalledWith(false));
    await user.click(await screen.findByRole("button", { name: "Run evaluation" }));
    emit?.({
      type: "draft_patch",
      node: "aggregator",
      issues: [
        {
          id: "issue-1",
          finding_kind: "unsupported_citation",
          severity: "CRITICAL",
          reason: "The cited passage does not entail the claim.",
          suggestion: "Cite a passage that entails the claim.",
          target_card_id: null,
        },
      ],
      handling_options: [],
      scores: {
        originality: 7,
        significance: 8,
        soundness: 6,
        clarity: 7,
        reproducibility: 5,
      },
    });
    await waitFor(() => expect(onConfirmabilityChange).toHaveBeenCalledWith(true));
  });

  it("does not offer PICK on a frozen Aggregator Head Revision view", async () => {
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        node: "aggregator",
        issues: [
          {
            id: "issue-1",
            finding_kind: "unsupported_citation",
            severity: "CRITICAL",
            reason: "The cited passage does not entail the claim.",
            suggestion: "Cite a passage that entails the claim.",
            target_card_id: null,
            source_node: "evidence_judge",
            cluster: "disagreement",
          },
        ],
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
        scores: null,
      },
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgeRunRevisionView
          sessionId="session-1"
          node={WorkflowNode.aggregator}
          stageRevisionId="rev-agg"
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Unsupported citation")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pick/i })).not.toBeInTheDocument();
  });
});
