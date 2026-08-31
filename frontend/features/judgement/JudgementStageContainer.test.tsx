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
    expect(within(heads).getByText("Gap Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Contribution Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Evidence Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Experiment Judge")).toBeInTheDocument();
    expect(within(heads).getByText("Conference Judge")).toBeInTheDocument();
    expect(within(heads).getAllByText("empty")).toHaveLength(5);
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
    expect(await screen.findByText("Evidence Judge")).toBeInTheDocument();
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
    expect(await screen.findByText("Contribution Judge")).toBeInTheDocument();
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
    expect(await screen.findByText("Experiment Judge")).toBeInTheDocument();
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
    await user.click(await screen.findByRole("button", { name: "Run pending Judges" }));
    const heads = screen.getByRole("list", { name: "Judge Node Heads" });
    emit?.({
      type: "progress",
      node: "gap_judge",
      message: "Starting Gap Judge",
      pct: 0,
    });
    const gap = within(heads).getByText("Gap Judge").closest("li");
    await waitFor(() =>
      expect(within(gap as HTMLElement).getByText("running")).toBeInTheDocument(),
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
      expect(within(gap as HTMLElement).getByText("current")).toBeInTheDocument(),
    );
    expect(within(gap as HTMLElement).getByText(/1 CRITICAL/)).toBeInTheDocument();
    emit?.({
      type: "progress",
      node: "contribution_judge",
      message: "Starting Contribution Judge",
      pct: 0,
    });
    const contribution = within(heads).getByText("Contribution Judge").closest("li");
    await waitFor(() =>
      expect(within(contribution as HTMLElement).getByText("running")).toBeInTheDocument(),
    );
    emit?.({
      type: "draft_patch",
      node: "contribution_judge",
      issues: [],
    });
    emit?.({ type: "done", node: "contribution_judge", version: 5 });
    await waitFor(() =>
      expect(within(contribution as HTMLElement).getByText("current")).toBeInTheDocument(),
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
    const conference = within(heads).getByText("Conference Judge").closest("li");
    await waitFor(() =>
      expect(within(conference as HTMLElement).getByText("current")).toBeInTheDocument(),
    );
    expect(within(conference as HTMLElement).getByText("7/10")).toBeInTheDocument();
    expect(within(gap as HTMLElement).getByText("current")).toBeInTheDocument();
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
    await user.click(await screen.findByRole("button", { name: "Run pending Judges" }));
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

  it("generates one Judge from a compact head click and shows running then current counts", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    let finish: (() => void) | undefined;
    mocks.streamStart.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, emptyIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    expect(mocks.streamStart).not.toHaveBeenCalled();
    await user.click(await screen.findByRole("button", { name: "Generate Gap Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "gap_judge",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
    const heads = screen.getByRole("list", { name: "Judge Node Heads" });
    const gap = within(heads).getByText("Gap Judge").closest("li");
    expect(gap).not.toBeNull();
    expect(within(gap as HTMLElement).getByText("running")).toBeInTheDocument();
    finish?.();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Generate Gap Judge" })).toBeInTheDocument(),
    );

    mocks.streamStart.mockImplementation(async (options: { onEvent?: (event: unknown) => void }) => {
      options.onEvent?.({
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
          {
            id: "issue-2",
            finding_kind: "gap_untestable",
            severity: "MAJOR",
            reason: "No evaluation protocol exists.",
            suggestion: "Add a measurable test.",
            target_card_id: null,
          },
        ],
      });
      options.onEvent?.({ type: "done", node: "gap_judge", version: 5 });
    });
    await user.click(screen.getByRole("button", { name: "Generate Gap Judge" }));
    const gapAfter = within(heads).getByText("Gap Judge").closest("li");
    await waitFor(() =>
      expect(within(gapAfter as HTMLElement).getByText("current")).toBeInTheDocument(),
    );
    expect(within(gapAfter as HTMLElement).getByText(/1 CRITICAL/)).toBeInTheDocument();
    expect(within(gapAfter as HTMLElement).getByText(/1 MAJOR/)).toBeInTheDocument();
  });

  it("shows Conference criterion scores on the compact head after generate", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    mocks.streamStart.mockImplementation(async (options: { onEvent?: (event: unknown) => void }) => {
      options.onEvent?.({
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
      options.onEvent?.({ type: "done", node: "conference_judge", version: 5 });
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, emptyIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Generate Conference Judge" }));
    const heads = screen.getByRole("list", { name: "Judge Node Heads" });
    const conference = within(heads).getByText("Conference Judge").closest("li");
    expect(conference).not.toBeNull();
    await waitFor(() => expect(within(conference as HTMLElement).getByText("current")).toBeInTheDocument());
    expect(within(conference as HTMLElement).getByText("7/10")).toBeInTheDocument();
    expect(within(conference as HTMLElement).queryByText("CRITICAL")).not.toBeInTheDocument();
  });

  it("regenerates a current compact Judge without leaving Aggregator Working Draft and replaces the report", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    let workingReportReplaced = false;
    mocks.customFetch.mockImplementation(async (path: unknown) => {
      if (typeof path === "string" && path.endsWith("/nodes/aggregator")) {
        if (workingReportReplaced) {
          return {
            status: 200,
            data: {
              node: "aggregator",
              issues: [
                {
                  id: "issue-agg",
                  finding_kind: "claim_broader_than_experiment",
                  severity: "MAJOR",
                  reason: "The claim outruns the experiment plan.",
                  suggestion: "Narrow the claim.",
                  target_card_id: null,
                  source_node: "evidence_judge",
                  cluster: "disagreement",
                },
              ],
              handling_options: [
                {
                  id: "opt-2",
                  finding_kind: "claim_broader_than_experiment",
                  source_node: "evidence_judge",
                  label: "Narrow the experiment",
                  target_node: "experiment_plan",
                  prose: "Match the experiment to the claim.",
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
          };
        }
        return {
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
        };
      }
      if (typeof path === "string" && path.endsWith("/nodes/conference_judge")) {
        return {
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
        };
      }
      return { status: 200, data: { node: "gap_judge", issues: [], scores: null } };
    });
    mocks.streamStart.mockImplementation(async (options: { onEvent?: (event: unknown) => void }) => {
      options.onEvent?.({
        type: "draft_patch",
        node: "evidence_judge",
        issues: [
          {
            id: "issue-new",
            finding_kind: "claim_broader_than_experiment",
            severity: "MAJOR",
            reason: "The claim outruns the experiment plan.",
            suggestion: "Narrow the claim.",
            target_card_id: null,
          },
        ],
      });
      options.onEvent?.({ type: "done", node: "evidence_judge", version: 5 });
      options.onEvent?.({
        type: "draft_patch",
        node: "aggregator",
        issues: [
          {
            id: "issue-agg",
            finding_kind: "claim_broader_than_experiment",
            severity: "MAJOR",
            reason: "The claim outruns the experiment plan.",
            suggestion: "Narrow the claim.",
            target_card_id: null,
            source_node: "evidence_judge",
            cluster: "disagreement",
          },
        ],
        handling_options: [
          {
            id: "opt-2",
            finding_kind: "claim_broader_than_experiment",
            source_node: "evidence_judge",
            label: "Narrow the experiment",
            target_node: "experiment_plan",
            prose: "Match the experiment to the claim.",
          },
        ],
        scores: {
          originality: 7,
          significance: 8,
          soundness: 6,
          clarity: 7,
          reproducibility: 5,
        },
      });
      options.onEvent?.({ type: "done", node: "aggregator", version: 6 });
      workingReportReplaced = true;
    });
    const dashboard = session(WorkflowNode.aggregator, currentIndependentJudgesHeads());
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer sessionId="session-1" session={dashboard} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Revise the claim")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate Evidence Judge" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate Gap Judge" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run pending Judges" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regenerate Evidence Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: "evidence_judge",
        expectedVersion: 4,
        staleReaccept: false,
      }),
    );
    expect(dashboard.working_draft_node).toBe(WorkflowNode.aggregator);
    await waitFor(() => expect(screen.getByText("Narrow the experiment")).toBeInTheDocument());
    expect(screen.queryByText("Revise the claim")).not.toBeInTheDocument();
    expect(screen.getByText("Claim broader than experiment")).toBeInTheDocument();
  });

  it("shows Conference criterion scores on the compact head after regenerate", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    mocks.customFetch.mockImplementation(async (path: unknown) => {
      if (typeof path === "string" && path.endsWith("/nodes/conference_judge")) {
        return {
          status: 200,
          data: {
            node: "conference_judge",
            issues: [],
            scores: {
              originality: 6,
              significance: 6,
              soundness: 6,
              clarity: 6,
              reproducibility: 6,
            },
          },
        };
      }
      return { status: 200, data: { node: "aggregator", issues: [], handling_options: [], scores: null } };
    });
    mocks.streamStart.mockImplementation(async (options: { onEvent?: (event: unknown) => void }) => {
      options.onEvent?.({
        type: "draft_patch",
        node: "conference_judge",
        issues: [
          {
            id: "issue-noise",
            finding_kind: "unsupported_citation",
            severity: "CRITICAL",
            reason: "Must not appear on the compact Conference head.",
            suggestion: "Ignore.",
            target_card_id: null,
          },
        ],
        scores: {
          originality: 7,
          significance: 8,
          soundness: 6,
          clarity: 9,
          reproducibility: 5,
        },
      });
      options.onEvent?.({ type: "done", node: "conference_judge", version: 5 });
    });
    render(
      <QueryClientProvider client={queryClient}>
        <JudgementStageContainer
          sessionId="session-1"
          session={session(WorkflowNode.aggregator, currentIndependentJudgesHeads())}
        />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Regenerate Conference Judge" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        node: "conference_judge",
        staleReaccept: false,
      }),
    );
    const heads = screen.getByRole("list", { name: "Judge Node Heads" });
    const conference = within(heads).getByText("Conference Judge").closest("li");
    expect(conference).not.toBeNull();
    await waitFor(() => expect(within(conference as HTMLElement).getByText("7/10")).toBeInTheDocument());
    expect(within(conference as HTMLElement).getByText("current")).toBeInTheDocument();
    expect(within(conference as HTMLElement).queryByText("CRITICAL")).not.toBeInTheDocument();
    expect(within(conference as HTMLElement).queryByText("Unsupported citation")).not.toBeInTheDocument();
  });

  it("asks for Stale re-accept when generating a Stale Judge", async () => {
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
    await user.click(await screen.findByRole("button", { name: "Regenerate Gap Judge" }));
    expect(mocks.streamStart).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Stale Workflow Node" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        node: "gap_judge",
        staleReaccept: true,
      }),
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
    await user.click(await screen.findByRole("button", { name: "Run pending Judges" }));
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
