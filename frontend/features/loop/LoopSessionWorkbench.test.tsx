import * as React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import { readSseStream } from "@/lib/api/sse";
import {
  CardKind,
  LoopStage,
  NodeHeadStatus,
  WorkflowNode,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";

import { LoopSessionWorkbench } from "./LoopSessionWorkbench";
import { sessionHref } from "./catalog";
import type { SaveStatus } from "./mutation-queue";

const replace = vi.fn();
const getHook = vi.fn();
const decisionsHook = vi.fn();
const prepareHook = vi.fn();
const patchHook = vi.fn();
const confirmHook = vi.fn();
const setQueryData = vi.fn();
const getQueryData = vi.fn();
const invalidateQueries = vi.fn();
const queueFlush = vi.fn(async () => undefined);
const queueEnqueue = vi.fn(async (mutation: () => Promise<unknown>) => mutation());
const saveStatus = { current: "idle" as SaveStatus };
let search = new URLSearchParams();

vi.mock("@/lib/api/sse", () => ({
  readSseStream: vi.fn(async (_path: string, onEvent: (data: unknown) => void) => {
    onEvent({ type: "done", version: 5 });
  }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/sessions/session-1",
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => search,
}));

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQueryClient: () => ({ setQueryData, getQueryData, invalidateQueries }),
  };
});

vi.mock("./LoopSessionTitleEditor", () => ({
  LoopSessionTitleEditor: ({ sessionId }: { sessionId: string }) => (
    <p>Title editor for {sessionId}</p>
  ),
}));

vi.mock("./WorkingDraftNarrativeEditor", () => ({
  WorkingDraftNarrativeEditor: ({ sessionId }: { sessionId: string }) => (
    <p>Working Draft narrative editor for {sessionId}</p>
  ),
}));

vi.mock("./WorkingDraftCardCanvas", () => ({
  WorkingDraftCardCanvas: ({ sessionId }: { sessionId: string }) => (
    <p>Working Draft Card canvas for {sessionId}</p>
  ),
}));

vi.mock("@/features/research", () => ({
  ResearchStageContainer: ({
    sessionId,
    onRunningChange,
    onConfirmabilityChange,
  }: {
    sessionId: string;
    onRunningChange?: (running: boolean) => void;
    onConfirmabilityChange?: (confirmable: boolean) => void;
  }) => {
    React.useEffect(() => {
      onRunningChange?.(false);
      onConfirmabilityChange?.(true);
    }, [onConfirmabilityChange, onRunningChange]);
    return <p>Working Draft narrative editor for {sessionId}</p>;
  },
  ContributionStageContainer: ({
    sessionId,
    onRunningChange,
    onConfirmabilityChange,
  }: {
    sessionId: string;
    onRunningChange?: (running: boolean) => void;
    onConfirmabilityChange?: (confirmable: boolean) => void;
  }) => {
    React.useEffect(() => {
      onRunningChange?.(false);
      onConfirmabilityChange?.(true);
    }, [onConfirmabilityChange, onRunningChange]);
    return <p>Contribution Direction editor for {sessionId}</p>;
  },
}));

vi.mock("./loop-session-save", () => ({
  LoopSessionSaveProvider: ({ children }: { children: React.ReactNode }) => children,
  useLoopSessionSave: () => ({
    queue: { flush: queueFlush, enqueue: queueEnqueue },
    status: saveStatus.current,
    setStatus: vi.fn(),
  }),
}));

vi.mock("@/lib/api/generated/endpoints", () => ({
  getGetSessionApiLoopSessionsSessionIdGetQueryKey: (id: string) => [`/sessions/${id}`],
  getListDecisionsApiLoopSessionsSessionIdDecisionsGetQueryKey: (id: string) => [
    `/api/loop/sessions/${id}/decisions`,
  ],
  getListSessionsApiLoopSessionsGetQueryKey: () => ["/api/loop/sessions"],
  useGetSessionApiLoopSessionsSessionIdGet: (...args: unknown[]) => getHook(...args),
  useListDecisionsApiLoopSessionsSessionIdDecisionsGet: (...args: unknown[]) =>
    decisionsHook(...args),
  useRecomputePrepareApiLoopSessionsSessionIdRecomputePreparePost: (...args: unknown[]) =>
    prepareHook(...args),
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch: (...args: unknown[]) =>
    patchHook(...args),
  useConfirmApiLoopSessionsSessionIdConfirmPost: (...args: unknown[]) => confirmHook(...args),
}));

function path(stage: LoopStage, node?: WorkflowNode): string {
  return sessionHref("session-1", node ? { stage, node } : { stage });
}

function heads(
  overrides: Partial<Record<WorkflowNode, NodeHeadStatus>> = {},
): LoopSessionResponse["node_heads"] {
  return Object.values(WorkflowNode).map((node) => ({
    node,
    status: overrides[node] ?? NodeHeadStatus.empty,
    stage_revision_id: null,
    head_revision: null,
  }));
}

function session(overrides: Partial<LoopSessionResponse> = {}): LoopSessionResponse {
  return {
    id: "session-1",
    title: "GPU kernels",
    version: 1,
    working_draft_node: WorkflowNode.idea_interpretation,
    working_draft_narrative: {},
    node_heads: heads(),
    cards: [],
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-15T10:00:00Z",
    updated_at: "2026-08-16T10:00:00Z",
    ...overrides,
  };
}

function completeFrame(text = "GPU kernel latency"): Record<string, string> {
  return {
    intent: `You want to study ${text}.`,
    problem: `Restated ${text}`,
    research_question: `How should we study ${text}?`,
  };
}

function answeredTurns(text = "GPU kernel latency"): Record<string, unknown> {
  return {
    exhausted: true,
    frame: completeFrame(text),
    turns: [
      { role: "account", kind: "idea", text },
      { role: "model", preamble: "No further questions.", questions: [] },
    ],
  };
}

function unansweredTurns(frame?: Record<string, string>): Record<string, unknown> {
  return {
    exhausted: false,
    ...(frame ? { frame } : {}),
    turns: [
      { role: "account", kind: "idea", text: "GPU kernel latency" },
      {
        role: "model",
        preamble: "Need the budget.",
        questions: [{ text: "Training or inference?", options: ["Training", "Inference"] }],
      },
    ],
  };
}

function stagePath() {
  return screen.getByRole("navigation", { name: "Stage path" });
}

describe("LoopSessionWorkbench", () => {
  beforeEach(() => {
    replace.mockReset();
    getHook.mockReset();
    decisionsHook.mockReset();
    prepareHook.mockReset();
    patchHook.mockReset();
    confirmHook.mockReset();
    setQueryData.mockReset();
    getQueryData.mockReset();
    invalidateQueries.mockReset();
    queueFlush.mockReset();
    queueEnqueue.mockReset();
    queueFlush.mockResolvedValue(undefined);
    queueEnqueue.mockImplementation(async (mutation: () => Promise<unknown>) => mutation());
    saveStatus.current = "idle";
    search = new URLSearchParams();
    vi.mocked(readSseStream).mockClear();
    vi.mocked(readSseStream).mockImplementation(async (_path, onEvent) => {
      onEvent({ type: "done", version: 5 });
    });
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    decisionsHook.mockReturnValue({
      data: { status: 200, data: [] },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    prepareHook.mockReturnValue({ mutateAsync: vi.fn(), error: null, isPending: false });
    patchHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });
    confirmHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });
  });

  it("loads Working Draft, Node Heads, Cards, and Spec Version pointers through the generated client", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          cards: [
            {
              id: "card-1",
              kind: CardKind.problem,
              body: { text: "Memory bandwidth" },
              created_at: "2026-08-15T10:00:00Z",
              updated_at: "2026-08-15T10:00:00Z",
            },
          ],
          produced_spec_version: {
            id: "spec-1",
            document: {},
            created_at: "2026-08-16T10:00:00Z",
          },
          valid_spec_version_id: null,
        }),
      },
      isLoading: false,
      isError: false,
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(getHook).toHaveBeenCalledWith("session-1");
    expect(screen.getByText("Title editor for session-1")).toBeInTheDocument();
    expect(screen.queryByText(/^Working Draft:/)).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Loop Stages" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Produced Spec Version" })).not.toBeInTheDocument();
  });

  it("puts back navigation and the title editor on a session strip", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);

    const strip = screen.getByRole("banner", { name: "Loop Session" });
    expect(within(strip).getByRole("link", { name: "← Back to Loop Sessions" })).toHaveAttribute(
      "href",
      "/sessions",
    );
    expect(within(strip).getByText("Title editor for session-1")).toBeInTheDocument();
  });

  it("shows a stage rail and workspace without a Stage actions column", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.getByRole("navigation", { name: "Loop Stages" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Stage path" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /overview$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Stage actions" })).not.toBeInTheDocument();
  });

  it("highlights the Loop Stage selected by the stage query", () => {
    search = new URLSearchParams(`stage=${LoopStage.gap}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });

    expect(within(nav).getByRole("link", { name: /Gap/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /Grilling/ })).not.toHaveAttribute("aria-current");
  });

  it("does not show Decision history or an always-on Produced Spec Version", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.queryByRole("region", { name: "Decision history" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Produced Spec Version" })).not.toBeInTheDocument();
  });

  it("opens Spec Draft as a workspace placeholder without Produced Spec Version", () => {
    search = new URLSearchParams(`stage=${LoopStage.spec_draft}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.queryByRole("region", { name: "Spec Draft overview" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("The Produced Spec Version will appear here after you confirm feasibility."),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Produced Spec Version" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
  });

  it("shows a Stale Produced Spec Version on Spec Draft and keeps Continue disabled", () => {
    search = new URLSearchParams(`stage=${LoopStage.spec_draft}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          produced_spec_version: {
            id: "spec-old",
            created_at: "2026-08-16T12:00:00Z",
            document: {
              nodes: {
                idea_interpretation: {
                  narrative: { text: "Earlier understanding" },
                  card_snapshot: [],
                },
              },
            },
          },
          valid_spec_version_id: null,
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Stale");
    expect(spec).toHaveTextContent("Earlier understanding");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("enables Continue to Independent judges when Spec Draft has a Valid Spec Version", async () => {
    search = new URLSearchParams(`stage=${LoopStage.spec_draft}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 20,
          produced_spec_version: {
            id: "spec-valid",
            created_at: "2026-08-16T12:00:00Z",
            document: {
              nodes: {
                idea_interpretation: {
                  narrative: { text: "Latency in GPU kernels" },
                  card_snapshot: [],
                },
              },
            },
          },
          valid_spec_version_id: "spec-valid",
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
            [WorkflowNode.related_work]: NodeHeadStatus.current,
            [WorkflowNode.gap]: NodeHeadStatus.current,
            [WorkflowNode.contribution]: NodeHeadStatus.current,
            [WorkflowNode.claims]: NodeHeadStatus.current,
            [WorkflowNode.evidence]: NodeHeadStatus.current,
            [WorkflowNode.experiment_plan]: NodeHeadStatus.current,
            [WorkflowNode.feasibility]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const prepared = session({
      version: 21,
      working_draft_node: WorkflowNode.gap_judge,
    });
    const prepareMutate = vi.fn().mockResolvedValue({ status: 200, data: prepared });
    prepareHook.mockReturnValue({ mutateAsync: prepareMutate, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Valid Spec Version");
    expect(spec).toHaveTextContent("Latency in GPU kernels");
    expect(spec).not.toHaveTextContent("Stale");
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(prepareMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.independent_judges, expected_version: 20 },
    });
    expect(replace).toHaveBeenCalledWith(
      path(LoopStage.independent_judges, WorkflowNode.gap_judge),
      { scroll: false },
    );
  });

  it("shows Gap, Contribution, and Spec Draft on the Loop Stage rail", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });

    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual([
      expect.stringContaining("Grilling"),
      expect.stringContaining("Related work"),
      expect.stringContaining("Gap"),
      expect.stringContaining("Contribution"),
      expect.stringContaining("Claims/evidence"),
      expect.stringContaining("Experiment planning"),
      expect.stringContaining("Spec Draft"),
      expect.stringContaining("Independent judges"),
      expect.stringContaining("Readiness"),
    ]);
  });

  it("shows completion, Editing, and availability as independent signals", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.idea_interpretation,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });
    const grilling = within(nav).getByRole("link", { name: /Grilling/ });
    const relatedWork = within(nav).getByRole("link", { name: /Related work/ });

    expect(grilling).toHaveTextContent("Complete");
    expect(grilling).toHaveTextContent("Editing");
    expect(relatedWork).toHaveTextContent("Needs work");
    expect(relatedWork).not.toHaveTextContent("Unavailable");
    expect(relatedWork).not.toHaveTextContent("Editing");
  });

  it("selects a Loop Stage only through the query string and issues no mutations", async () => {
    const prepare = vi.fn();
    const patch = vi.fn();
    prepareHook.mockReturnValue({ mutateAsync: prepare, error: null });
    patchHook.mockReturnValue({ mutateAsync: patch, error: null });
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const claimsEvidence = screen.getByRole("link", { name: /Claims\/evidence/ });

    expect(claimsEvidence).toHaveAttribute(
      "href",
      path(LoopStage.claims_evidence, WorkflowNode.claims),
    );
    await userEvent.click(claimsEvidence);
    expect(prepare).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
  });

  it("exposes one sub-tab per Workflow Node including single-node Loop Stages", () => {
    const stages: { stage: LoopStage; labels: string[] }[] = [
      {
        stage: LoopStage.grilling,
        labels: ["Idea interpretation", "Idea decomposition"],
      },
      {
        stage: LoopStage.related_work,
        labels: ["Research inputs", "Related work"],
      },
      {
        stage: LoopStage.claims_evidence,
        labels: ["Claims", "Evidence"],
      },
      {
        stage: LoopStage.experiment_planning,
        labels: ["Experiment plan", "Feasibility"],
      },
      {
        stage: LoopStage.gap,
        labels: ["Gap"],
      },
      {
        stage: LoopStage.contribution,
        labels: ["Contribution direction"],
      },
      {
        stage: LoopStage.independent_judges,
        labels: [
          "Gap Judge",
          "Contribution Judge",
          "Evidence Judge",
          "Experiment Judge",
          "Conference Judge",
          "Aggregator",
        ],
      },
    ];

    for (const { stage, labels } of stages) {
      search = new URLSearchParams(`stage=${stage}`);
      const view = render(<LoopSessionWorkbench sessionId="session-1" />);
      const tabs = screen.getByRole("tablist", { name: "Workflow Nodes" });
      expect(within(tabs).getAllByRole("tab").map((tab) => tab.textContent)).toEqual(
        labels.map((label) => expect.stringContaining(label)),
      );
      view.unmount();
    }
  });

  it("shows a Spec Draft tab on the stage path and no Workflow Node tabs on Readiness", () => {
    search = new URLSearchParams(`stage=${LoopStage.spec_draft}`);
    const specDraft = render(<LoopSessionWorkbench sessionId="session-1" />);
    const specTabs = screen.getByRole("tablist", { name: "Workflow Nodes" });
    expect(within(specTabs).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Spec Draft",
    ]);
    expect(within(specTabs).getByRole("tab", { name: "Spec Draft" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    specDraft.unmount();

    search = new URLSearchParams(`stage=${LoopStage.readiness}`);
    const readiness = render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByRole("tablist", { name: "Workflow Nodes" })).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Stage path" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" }).querySelector("svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" }).querySelector("svg")).toBeInTheDocument();
    readiness.unmount();
  });

  it("selecting a current sibling tab browses without patching Working Draft", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}&node=${WorkflowNode.idea_interpretation}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 6,
          working_draft_node: WorkflowNode.idea_interpretation,
          working_draft_narrative: answeredTurns("kept interpretation"),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn();
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("tab", { name: /Idea decomposition/ }));

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith(
      path(LoopStage.grilling, WorkflowNode.idea_decomposition),
      { scroll: false },
    );
  });

  it("shows a Stage Revision when viewing a current sibling that is not the Working Draft", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}&node=${WorkflowNode.idea_decomposition}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.idea_interpretation,
          working_draft_narrative: answeredTurns("kept interpretation"),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }).map((head) =>
            head.node === WorkflowNode.idea_decomposition
              ? {
                  ...head,
                  head_revision: {
                    narrative: { text: "Problem and research question cards" },
                    card_snapshot: [
                      {
                        id: "card-1",
                        kind: CardKind.problem,
                        body: { text: "Memory bandwidth" },
                      },
                    ],
                  },
                }
              : head,
          ),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const revision = screen.getByRole("region", { name: "Idea decomposition Stage Revision" });
    expect(revision).toHaveTextContent("Memory bandwidth");
    expect(screen.queryByText("Working Draft Card canvas for session-1")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit Idea decomposition" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Idea decomposition/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("does not patch when the selected tab is already the viewed node", async () => {
    const mutateAsync = vi.fn();
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("tab", { name: /Idea interpretation/ }));

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole("tab", { name: /Idea interpretation/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows an empty Stage Revision when browsing an empty sibling", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}&node=${WorkflowNode.idea_decomposition}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 3,
          working_draft_node: WorkflowNode.idea_interpretation,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.empty,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn();
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText("No Stage Revision yet.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Idea decomposition/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("explains unavailable upstream when browsing a later Workflow Node", () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}&node=${WorkflowNode.related_work}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 4,
          working_draft_node: WorkflowNode.research_inputs,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
            [WorkflowNode.related_work]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn();
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText(/Upstream Workflow Nodes are not current/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Related work/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows Edit on the Stage Revision header when viewing confirmed work", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.research_inputs,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const revision = screen.getByRole("region", { name: "Idea interpretation Stage Revision" });

    expect(within(revision).getByRole("button", { name: "Edit Idea interpretation" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit Idea decomposition" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("shows Confirm below the Working Draft while editing a confirmable draft", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_narrative: unansweredTurns(completeFrame()),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("advances after Confirm without a Continue button", async () => {
    search = new URLSearchParams(`stage=${LoopStage.contribution}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 12,
          working_draft_node: WorkflowNode.contribution,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
            [WorkflowNode.related_work]: NodeHeadStatus.current,
            [WorkflowNode.gap]: NodeHeadStatus.current,
            [WorkflowNode.contribution]: NodeHeadStatus.empty,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const confirmed = session({
      version: 13,
      working_draft_node: WorkflowNode.contribution,
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        [WorkflowNode.related_work]: NodeHeadStatus.current,
        [WorkflowNode.gap]: NodeHeadStatus.current,
        [WorkflowNode.contribution]: NodeHeadStatus.current,
      }),
    });
    const prepared = session({
      version: 14,
      working_draft_node: WorkflowNode.claims,
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        [WorkflowNode.related_work]: NodeHeadStatus.current,
        [WorkflowNode.gap]: NodeHeadStatus.current,
        [WorkflowNode.contribution]: NodeHeadStatus.current,
      }),
    });
    const confirmMutate = vi.fn().mockResolvedValue({ status: 200, data: confirmed });
    const prepareMutate = vi.fn().mockResolvedValue({ status: 200, data: prepared });
    confirmHook.mockReturnValue({ mutateAsync: confirmMutate, error: null });
    prepareHook.mockReturnValue({ mutateAsync: prepareMutate, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(prepareMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.claims_evidence, expected_version: 13 },
    });
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("Saved. Select Continue to proceed to the next step."),
    ).not.toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith(
      path(LoopStage.claims_evidence, WorkflowNode.claims),
      { scroll: false },
    );
  });

  it("prepares empty Related work when the Account selects it", async () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 4,
          working_draft_node: WorkflowNode.idea_decomposition,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const prepared = session({
      version: 5,
      working_draft_node: WorkflowNode.research_inputs,
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.empty,
      }),
    });
    const mutateAsync = vi.fn().mockResolvedValue({ status: 200, data: prepared });
    prepareHook.mockReturnValue({ mutateAsync, error: null, isPending: false });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        sessionId: "session-1",
        data: { stage: LoopStage.related_work, expected_version: 4 },
      });
    });
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
  });

  it("has no Working Draft save status on the stage path and still disables Confirm while saving", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    saveStatus.current = "saving";
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_narrative: answeredTurns(),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    const { rerender } = render(<LoopSessionWorkbench sessionId="session-1" />);
    const pathNav = stagePath();

    expect(within(pathNav).queryByText("Saving…")).not.toBeInTheDocument();
    expect(within(pathNav).queryByText("Saved")).not.toBeInTheDocument();
    expect(within(pathNav).queryByRole("status", { name: "Working Draft save" })).not.toBeInTheDocument();
    expect(within(pathNav).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();

    saveStatus.current = "conflict";
    rerender(<LoopSessionWorkbench sessionId="session-1" />);
    expect(within(stagePath()).queryByText("Resolve conflict")).not.toBeInTheDocument();
  });

  it("does not offer Edit or Confirm on Spec Draft or Readiness", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.idea_interpretation,
          working_draft_narrative: answeredTurns(),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    search = new URLSearchParams(`stage=${LoopStage.spec_draft}`);
    const { rerender } = render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();

    search = new URLSearchParams(`stage=${LoopStage.readiness}`);
    rerender(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
  });

  it("does not auto-prepare Grilling while the Working Draft is unconfirmed", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    const prepare = vi.fn();
    prepareHook.mockReturnValue({ mutateAsync: prepare, error: null, isPending: false });
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(prepare).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
  });

  it("does not auto-prepare a Stale Working Draft already on that node", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    const prepare = vi.fn();
    prepareHook.mockReturnValue({ mutateAsync: prepare, error: null, isPending: false });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.idea_decomposition,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.stale,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
    expect(prepare).not.toHaveBeenCalled();
  });

  it("does not offer Start, Recompute, or Edit on an unavailable Loop Stage", () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    const prepare = vi.fn();
    prepareHook.mockReturnValue({ mutateAsync: prepare, error: null, isPending: false });
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
    expect(prepare).not.toHaveBeenCalled();
  });

  it("starts empty work through recompute-prepare and applies the server Loop Session", async () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 4,
          working_draft_node: WorkflowNode.idea_decomposition,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const prepared = session({
      version: 5,
      working_draft_node: WorkflowNode.research_inputs,
      working_draft_narrative: { text: "from snapshot" },
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.empty,
      }),
    });
    const mutateAsync = vi.fn().mockResolvedValue({ status: 200, data: prepared });
    prepareHook.mockReturnValue({ mutateAsync, error: null, isPending: false });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByText(/Working Draft narrative editor/)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        sessionId: "session-1",
        data: { stage: LoopStage.related_work, expected_version: 4 },
      });
    });
    expect(setQueryData).toHaveBeenCalledWith(["/sessions/session-1"], {
      status: 200,
      data: prepared,
    });
    expect(screen.getByText("Working Draft narrative editor for session-1")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });
    expect(within(nav).getByRole("link", { name: /Related work/ })).toHaveTextContent("Editing");
  });

  it("recomputes a Stale node when selected from another Loop Stage", async () => {
    search = new URLSearchParams(
      `stage=${LoopStage.grilling}&node=${WorkflowNode.idea_decomposition}`,
    );
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 3,
          working_draft_node: WorkflowNode.research_inputs,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.stale,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 200,
      data: session({
        version: 4,
        working_draft_node: WorkflowNode.idea_decomposition,
        node_heads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.stale,
          [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        }),
      }),
    });
    prepareHook.mockReturnValue({ mutateAsync, error: null, isPending: false });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        sessionId: "session-1",
        data: { stage: LoopStage.grilling, expected_version: 3 },
      });
    });
    expect(screen.queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Idea decomposition/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("does not auto-prepare a current Node Head in a mixed Stale Loop Stage", () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    const prepare = vi.fn();
    prepareHook.mockReturnValue({ mutateAsync: prepare, error: null, isPending: false });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.contribution,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
            [WorkflowNode.related_work]: NodeHeadStatus.stale,
            [WorkflowNode.gap]: NodeHeadStatus.current,
            [WorkflowNode.contribution]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(prepare).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Research inputs/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("reopens a chosen current Workflow Node through the Working Draft mutation", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 6,
          working_draft_node: WorkflowNode.research_inputs,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const reopened = session({
      version: 7,
      working_draft_node: WorkflowNode.idea_interpretation,
      working_draft_narrative: answeredTurns("kept interpretation"),
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
      }),
    });
    const mutateAsync = vi.fn().mockResolvedValue({ status: 200, data: reopened });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByText(/Working Draft narrative editor/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit Idea interpretation" }));

    expect(mutateAsync).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: {
        expected_version: 6,
        node: WorkflowNode.idea_interpretation,
      },
    });
    expect(screen.getByText("kept interpretation")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Loop Stages" })).toHaveTextContent("Editing");
  });

  it("preserves local Loop Session state and recovers from a version conflict", async () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    const refetch = vi.fn().mockResolvedValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          title: "Server title",
          working_draft_node: WorkflowNode.research_inputs,
          working_draft_narrative: answeredTurns("Server idea"),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.empty,
          }),
        }),
      },
    });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 1,
          working_draft_node: WorkflowNode.idea_decomposition,
          working_draft_narrative: answeredTurns("Local idea"),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch,
    });
    const mutateAsync = vi.fn().mockRejectedValue(
      new ApiError(409, "changed", {
        code: "version_conflict",
        detail: "Loop Session was changed by another request",
        current_version: 2,
      }),
    );
    prepareHook.mockReturnValue({ mutateAsync, error: null, isPending: false });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("version conflict");
    expect(setQueryData).not.toHaveBeenCalled();
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Load current Loop Session" }));
    expect(refetch).toHaveBeenCalled();
    expect(setQueryData).toHaveBeenCalledWith(["/sessions/session-1"], {
      status: 200,
      data: session({
        version: 2,
        title: "Server title",
        working_draft_node: WorkflowNode.research_inputs,
        working_draft_narrative: answeredTurns("Server idea"),
        node_heads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          [WorkflowNode.research_inputs]: NodeHeadStatus.empty,
        }),
      }),
    });
  });

  it("explains incomplete upstream work without changing local edits", async () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          working_draft_node: WorkflowNode.idea_decomposition,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockRejectedValue(
      new ApiError(409, "upstream", {
        code: "upstream_not_current",
        detail: "Upstream Node Heads of this Loop Stage must be current",
      }),
    );
    prepareHook.mockReturnValue({ mutateAsync, error: null, isPending: false });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("not current");
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("explains an already-current Loop Stage without changing local edits", async () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          working_draft_node: WorkflowNode.idea_decomposition,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockRejectedValue(
      new ApiError(409, "current", {
        code: "stage_already_current",
        detail: "Every Workflow Node in this Loop Stage is current",
      }),
    );
    prepareHook.mockReturnValue({ mutateAsync, error: null, isPending: false });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("already current");
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("falls back from an absent or invalid stage query to the Working Draft Loop Stage", () => {
    search = new URLSearchParams("stage=not-a-stage");
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(replace).toHaveBeenCalledWith(
      path(LoopStage.grilling, WorkflowNode.idea_interpretation),
      { scroll: false },
    );
  });

  it("lists Workflow Nodes for the selected Loop Stage without Node Head states", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.empty,
          }),
        }),
      },
      isLoading: false,
      isError: false,
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const tabs = screen.getByRole("tablist", { name: "Workflow Nodes" });

    expect(within(tabs).getByRole("tab", { name: "Idea interpretation" })).toBeInTheDocument();
    expect(within(tabs).getByRole("tab", { name: "Idea decomposition" })).toBeInTheDocument();
    expect(tabs).not.toHaveTextContent("Current");
    expect(tabs).not.toHaveTextContent("Empty");
    expect(tabs).not.toHaveTextContent("Stale");
    expect(tabs).not.toHaveTextContent("Working Draft");
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Back" }).querySelector("svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" }).querySelector("svg")).toBeInTheDocument();
  });

  it("explains unavailable stages from incomplete upstream Node Heads", () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });

    expect(within(nav).getByRole("link", { name: /Related work/ })).toHaveTextContent("Unavailable");
    expect(screen.queryByRole("region", { name: "Related work overview" })).not.toBeInTheDocument();
  });

  it("shows Readiness as Not evaluated with no percentage", () => {
    search = new URLSearchParams(`stage=${LoopStage.readiness}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });
    const readiness = within(nav).getByRole("link", { name: /Readiness/ });

    expect(readiness).toHaveTextContent("Not evaluated");
    expect(readiness).not.toHaveTextContent("%");
    expect(screen.queryByRole("region", { name: "Readiness overview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /readiness criteria met/i })).not.toBeInTheDocument();
  });

  it("shows loading and failure states", () => {
    getHook.mockReturnValueOnce({ isLoading: true, isError: false });
    const { rerender } = render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByText("Loading Loop Session…")).toBeInTheDocument();

    getHook.mockReturnValueOnce({ isLoading: false, isError: true, refetch: vi.fn() });
    rerender(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not load");
  });

  it("lets the Account Send the research idea on empty interpretation", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Your idea" })).toBeInTheDocument();
    expect(screen.queryByText("Working Draft narrative editor for session-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Working Draft Card canvas for session-1")).not.toBeInTheDocument();
  });

  it("does not open the Working Draft editor merely by selecting another Loop Stage", () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByText(/Working Draft narrative editor/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Working Draft Card canvas/)).not.toBeInTheDocument();
    expect(screen.getByText(/Upstream Workflow Nodes are not current/)).toBeInTheDocument();
  });

  it("does not offer Confirm before the Idea Frame exists", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("enables Confirm under the Idea Frame when the frame is complete even with open questions", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_narrative: unansweredTurns(completeFrame()),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByText("Intent")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    expect(
      screen.getByText("Unanswered Grilling Questions are not saved as answers."),
    ).toBeInTheDocument();
  });

  it("confirms the Working Draft after flushing saves and applies the interpretation handoff", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 3,
          working_draft_narrative: answeredTurns(),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const confirmed = session({
      version: 4,
      working_draft_node: WorkflowNode.idea_decomposition,
      working_draft_narrative: {},
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
      }),
    });
    const mutateAsync = vi.fn().mockResolvedValue({ status: 200, data: confirmed });
    confirmHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByText("may become Stale")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(queueFlush).toHaveBeenCalled();
    expect(mutateAsync).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: {
        node: WorkflowNode.idea_interpretation,
        expected_version: 3,
      },
    });
    expect(screen.getByRole("tab", { name: /Idea decomposition/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => expect(readSseStream).toHaveBeenCalled());
    expect(readSseStream).toHaveBeenCalledWith(
      "/api/idea/sessions/session-1/generate",
      expect.any(Function),
      undefined,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: 4 }),
      },
    );
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(screen.getByText("Working Draft Card canvas for session-1")).toBeInTheDocument();
  });

  it("sends cluster answers for interpretation and keeps Send disabled until every question is answered", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          working_draft_narrative: unansweredTurns(),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Training" }));
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(readSseStream).toHaveBeenCalled());
    expect(readSseStream).toHaveBeenCalledWith(
      "/api/idea/sessions/session-1/generate",
      expect.any(Function),
      undefined,
      {
        method: "POST",
        body: JSON.stringify({
          expected_version: 2,
          answers: [{ option: "Training" }],
        }),
      },
    );
  });

  it("sends an Account note to skip an unanswered cluster", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          working_draft_narrative: unansweredTurns(),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.type(screen.getByLabelText("Account note"), "Skip. Focus on tiling.");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(readSseStream).toHaveBeenCalled());
    expect(readSseStream).toHaveBeenCalledWith(
      "/api/idea/sessions/session-1/generate",
      expect.any(Function),
      undefined,
      {
        method: "POST",
        body: JSON.stringify({
          expected_version: 2,
          note: "Skip. Focus on tiling.",
        }),
      },
    );
  });

  it("saves an edited research idea as a JSON working-draft patch", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          working_draft_narrative: unansweredTurns(),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 200,
      data: session({
        version: 3,
        working_draft_narrative: {
          ...unansweredTurns(),
          turns: [{ role: "account", kind: "idea", text: "Tiling GPU kernels" }],
        },
      }),
    });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const ideaField = screen.getByLabelText("Edit idea");
    await userEvent.clear(ideaField);
    await userEvent.type(ideaField, "Tiling GPU kernels");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const payload = mutateAsync.mock.calls[0]?.[0] as {
      sessionId: string;
      data: { expected_version: number; narrative: Record<string, unknown> };
    };
    expect(() => JSON.stringify(payload.data)).not.toThrow();
    expect(payload).toEqual({
      sessionId: "session-1",
      data: {
        expected_version: 2,
        narrative: {
          turns: [{ role: "account", kind: "idea", text: "Tiling GPU kernels" }],
          exhausted: false,
        },
      },
    });
  });

  it("shows the exhausted hint on interpretation without gating Confirm", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_narrative: answeredTurns("idea"),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(
      screen.getByText("The model thinks questioning is exhausted. Confirm is still your Decision."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
  });

  it("disables Confirm while autosaves are pending or failed and aborts after a flush failure", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_narrative: answeredTurns(),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn();
    confirmHook.mockReturnValue({ mutateAsync, error: null });

    saveStatus.current = "saving";
    const { rerender } = render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();

    saveStatus.current = "failed";
    rerender(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();

    saveStatus.current = "idle";
    queueFlush.mockRejectedValueOnce(new Error("offline"));
    rerender(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("warns that current descendant Loop Stages may become Stale when reconfirming", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.idea_interpretation,
          working_draft_narrative: answeredTurns("changed understanding"),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const warning = screen.getByRole("note");
    expect(warning).toHaveTextContent("Grilling");
    expect(warning).toHaveTextContent("Related work");
    expect(warning).toHaveTextContent("may become Stale");
    expect(warning).toHaveTextContent("changes content");
  });

  it("does not warn on a first confirmation or when no descendant is current", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_narrative: answeredTurns("first idea"),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.empty,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByText("may become Stale")).not.toBeInTheDocument();
  });

  it("prepares the rest of the Loop Stage after Confirm when the next Workflow Node is empty", async () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 8,
          working_draft_node: WorkflowNode.research_inputs,
          working_draft_narrative: { text: "papers to read" },
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.empty,
            [WorkflowNode.related_work]: NodeHeadStatus.empty,
            [WorkflowNode.gap]: NodeHeadStatus.empty,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const confirmed = session({
      version: 9,
      working_draft_node: WorkflowNode.research_inputs,
      working_draft_narrative: { text: "papers to read" },
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        [WorkflowNode.related_work]: NodeHeadStatus.empty,
        [WorkflowNode.gap]: NodeHeadStatus.empty,
      }),
    });
    const prepared = session({
      version: 10,
      working_draft_node: WorkflowNode.related_work,
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        [WorkflowNode.related_work]: NodeHeadStatus.empty,
        [WorkflowNode.gap]: NodeHeadStatus.empty,
      }),
    });
    const confirmMutate = vi.fn().mockResolvedValue({ status: 200, data: confirmed });
    const prepareMutate = vi.fn().mockResolvedValue({ status: 200, data: prepared });
    confirmHook.mockReturnValue({ mutateAsync: confirmMutate, error: null });
    prepareHook.mockReturnValue({ mutateAsync: prepareMutate, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(confirmMutate).toHaveBeenCalledTimes(1);
    expect(prepareMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.related_work, expected_version: 9 },
    });
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith(
      path(LoopStage.related_work, WorkflowNode.related_work),
      { scroll: false },
    );
  });

  it("continues from reconfirmed Research Inputs to current Related Work", async () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    const currentHeads = heads({
      [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
      [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
      [WorkflowNode.research_inputs]: NodeHeadStatus.current,
      [WorkflowNode.related_work]: NodeHeadStatus.current,
      [WorkflowNode.gap]: NodeHeadStatus.empty,
    });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 8,
          working_draft_node: WorkflowNode.research_inputs,
          node_heads: currentHeads,
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const confirmed = session({
      version: 9,
      working_draft_node: WorkflowNode.research_inputs,
      node_heads: currentHeads,
    });
    const reopenedRelatedWork = session({
      version: 10,
      working_draft_node: WorkflowNode.related_work,
      node_heads: currentHeads,
    });
    const confirmMutate = vi.fn().mockResolvedValue({ status: 200, data: confirmed });
    const prepareMutate = vi.fn();
    const patchMutate = vi
      .fn()
      .mockResolvedValue({ status: 200, data: reopenedRelatedWork });
    confirmHook.mockReturnValue({ mutateAsync: confirmMutate, error: null });
    prepareHook.mockReturnValue({ mutateAsync: prepareMutate, error: null });
    patchHook.mockReturnValue({ mutateAsync: patchMutate, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(patchMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { node: WorkflowNode.related_work, expected_version: 9 },
    });
    expect(prepareMutate).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith(
      path(LoopStage.related_work, WorkflowNode.related_work),
      { scroll: false },
    );
  });

  it("continues from confirmed Contribution Direction to Claims/evidence", async () => {
    search = new URLSearchParams(`stage=${LoopStage.contribution}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 12,
          working_draft_node: WorkflowNode.contribution,
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
            [WorkflowNode.related_work]: NodeHeadStatus.current,
            [WorkflowNode.gap]: NodeHeadStatus.current,
            [WorkflowNode.contribution]: NodeHeadStatus.empty,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const confirmed = session({
      version: 13,
      working_draft_node: WorkflowNode.contribution,
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        [WorkflowNode.related_work]: NodeHeadStatus.current,
        [WorkflowNode.gap]: NodeHeadStatus.current,
        [WorkflowNode.contribution]: NodeHeadStatus.current,
      }),
    });
    const prepared = session({
      version: 14,
      working_draft_node: WorkflowNode.claims,
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
        [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
        [WorkflowNode.research_inputs]: NodeHeadStatus.current,
        [WorkflowNode.related_work]: NodeHeadStatus.current,
        [WorkflowNode.gap]: NodeHeadStatus.current,
        [WorkflowNode.contribution]: NodeHeadStatus.current,
      }),
    });
    const confirmMutate = vi.fn().mockResolvedValue({ status: 200, data: confirmed });
    const prepareMutate = vi.fn().mockResolvedValue({ status: 200, data: prepared });
    confirmHook.mockReturnValue({ mutateAsync: confirmMutate, error: null });
    prepareHook.mockReturnValue({ mutateAsync: prepareMutate, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(prepareMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.claims_evidence, expected_version: 13 },
    });
    expect(replace).toHaveBeenCalledWith(
      path(LoopStage.claims_evidence, WorkflowNode.claims),
      { scroll: false },
    );
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
  });

  it("does not show Continue on a current Contribution Loop Stage", () => {
    search = new URLSearchParams(`stage=${LoopStage.contribution}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 53,
          working_draft_node: WorkflowNode.contribution,
          updated_at: "2026-08-24T11:49:00Z",
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
            [WorkflowNode.idea_decomposition]: NodeHeadStatus.current,
            [WorkflowNode.research_inputs]: NodeHeadStatus.current,
            [WorkflowNode.related_work]: NodeHeadStatus.current,
            [WorkflowNode.gap]: NodeHeadStatus.current,
            [WorkflowNode.contribution]: NodeHeadStatus.current,
          }),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    decisionsHook.mockReturnValue({
      data: {
        status: 200,
        data: [{
          id: "decision-contribution",
          kind: "confirm",
          node: WorkflowNode.contribution,
          stage_revision_id: "revision-contribution",
          created_at: "2026-08-24T11:48:05Z",
        }],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
  });

  it("explains a Confirm version conflict without changing local Working Draft content", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 1,
          working_draft_narrative: answeredTurns("Local idea"),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockRejectedValue(
      new ApiError(409, "changed", {
        code: "version_conflict",
        detail: "Loop Session was changed by another request",
        current_version: 2,
      }),
    );
    confirmHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("version conflict");
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("keeps Readiness as Not evaluated when every Workflow Node is current", () => {
    search = new URLSearchParams(`stage=${LoopStage.readiness}`);
    const current = Object.fromEntries(
      Object.values(WorkflowNode).map((node) => [node, NodeHeadStatus.current]),
    ) as Partial<Record<WorkflowNode, NodeHeadStatus>>;
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_node: WorkflowNode.feasibility,
          node_heads: heads(current),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });
    const readiness = within(nav).getByRole("link", { name: /Readiness/ });

    expect(screen.queryByRole("region", { name: "Readiness overview" })).not.toBeInTheDocument();
    expect(readiness).toHaveTextContent("Not evaluated");
    expect(readiness).not.toHaveTextContent("%");
    expect(readiness).not.toHaveTextContent("Complete");
  });

  it("refreshes Decisions and dashboard queries after Confirm", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 3,
          working_draft_narrative: answeredTurns(),
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const confirmed = session({
      version: 4,
      working_draft_node: WorkflowNode.idea_decomposition,
      working_draft_narrative: {},
      node_heads: heads({
        [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
      }),
      produced_spec_version: {
        id: "spec-new",
        created_at: "2026-08-16T13:00:00Z",
        document: {
          nodes: {
            idea_interpretation: {
              narrative: { text: "Confirmed interpretation" },
              card_snapshot: [],
            },
          },
        },
      },
      valid_spec_version_id: "spec-new",
    });
    const mutateAsync = vi.fn().mockResolvedValue({ status: 200, data: confirmed });
    confirmHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.queryByRole("region", { name: "Produced Spec Version" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(screen.queryByRole("region", { name: "Produced Spec Version" })).not.toBeInTheDocument();
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["/api/loop/sessions/session-1/decisions"],
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["/api/loop/sessions"],
    });
  });
});
