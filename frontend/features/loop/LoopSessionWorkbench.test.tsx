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

function heads(
  overrides: Partial<Record<WorkflowNode, NodeHeadStatus>> = {},
): LoopSessionResponse["node_heads"] {
  return Object.values(WorkflowNode).map((node) => ({
    node,
    status: overrides[node] ?? NodeHeadStatus.empty,
    stage_revision_id: null,
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
    prepareHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });
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
    expect(screen.getByText("Working Draft: Idea interpretation")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Loop Stages" })).toBeInTheDocument();
  });

  it("puts back navigation and the title editor on a session strip", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);

    const strip = screen.getByRole("banner", { name: "Loop Session" });
    expect(within(strip).getByRole("link", { name: "All Loop Sessions" })).toHaveAttribute(
      "href",
      "/sessions",
    );
    expect(within(strip).getByText("Title editor for session-1")).toBeInTheDocument();
  });

  it("shows a stage rail, workspace, and action column", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(screen.getByRole("navigation", { name: "Loop Stages" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Grilling overview" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Stage actions" })).toBeInTheDocument();
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

    expect(screen.getByRole("region", { name: "Spec Draft overview" })).toHaveTextContent(
      "The Produced Spec Version will appear here after you confirm feasibility.",
    );
    expect(screen.queryByRole("region", { name: "Produced Spec Version" })).not.toBeInTheDocument();
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

    expect(claimsEvidence).toHaveAttribute("href", "/sessions/session-1?stage=claims_evidence");
    await userEvent.click(claimsEvidence);
    expect(prepare).not.toHaveBeenCalled();
    expect(patch).not.toHaveBeenCalled();
  });

  it("warns instead of continuing when the current work has not been confirmed", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    const prepare = vi.fn();
    prepareHook.mockReturnValue({ mutateAsync: prepare, error: null });
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const overview = screen.getByRole("region", { name: "Grilling overview" });

    await userEvent.click(within(overview).getByRole("button", { name: "Continue" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "This work has not been confirmed. Select Confirm to save it before continuing.",
    );
    expect(prepare).not.toHaveBeenCalled();
    expect(within(overview).queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(within(overview).queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
  });

  it("offers Recompute and Edit confirmed work from Node Heads", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
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
    const overview = screen.getByRole("region", { name: "Grilling overview" });

    expect(within(overview).queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(within(overview).getByRole("button", { name: "Recompute" })).toBeInTheDocument();
    expect(within(overview).getByRole("button", { name: "Edit Idea interpretation" })).toBeInTheDocument();
  });

  it("offers Edit confirmed work when every Workflow Node is current", () => {
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
    const overview = screen.getByRole("region", { name: "Grilling overview" });

    expect(within(overview).queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(within(overview).queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(within(overview).getByRole("button", { name: "Edit Idea interpretation" })).toBeInTheDocument();
    expect(within(overview).getByRole("button", { name: "Edit Idea decomposition" })).toBeInTheDocument();
  });

  it("does not offer Continue, Recompute, or Edit on an unavailable Loop Stage", () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const overview = screen.getByRole("region", { name: "Related work overview" });

    expect(within(overview).queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    expect(within(overview).queryByRole("button", { name: "Recompute" })).not.toBeInTheDocument();
    expect(within(overview).queryByRole("button", { name: /Edit / })).not.toBeInTheDocument();
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
    prepareHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const overview = screen.getByRole("region", { name: "Related work overview" });
    expect(screen.queryByText(/Working Draft narrative editor/)).not.toBeInTheDocument();
    await userEvent.click(within(overview).getByRole("button", { name: "Continue" }));

    expect(mutateAsync).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.related_work, expected_version: 4 },
    });
    expect(setQueryData).toHaveBeenCalledWith(["/sessions/session-1"], {
      status: 200,
      data: prepared,
    });
    expect(screen.getByText("Working Draft: Research inputs")).toBeInTheDocument();
    expect(screen.getByText("Working Draft narrative editor for session-1")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });
    expect(within(nav).getByRole("link", { name: /Related work/ })).toHaveTextContent("Editing");
  });

  it("recomputes stale work through recompute-prepare with the current aggregate version", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 3,
          working_draft_node: WorkflowNode.idea_interpretation,
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
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 200,
      data: session({
        version: 4,
        working_draft_node: WorkflowNode.idea_decomposition,
        node_heads: heads({
          [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
          [WorkflowNode.idea_decomposition]: NodeHeadStatus.stale,
        }),
      }),
    });
    prepareHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Recompute" }));

    expect(mutateAsync).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.grilling, expected_version: 3 },
    });
    expect(screen.getByText("Working Draft: Idea decomposition")).toBeInTheDocument();
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
    expect(screen.getByText("Working Draft: Idea interpretation")).toBeInTheDocument();
    expect(screen.getByText("kept interpretation")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Loop Stages" })).toHaveTextContent("Editing");
  });

  it("preserves local Loop Session state and recovers from a version conflict", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    const refetch = vi.fn().mockResolvedValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          title: "Server title",
          working_draft_node: WorkflowNode.idea_interpretation,
          working_draft_narrative: answeredTurns("Server idea"),
        }),
      },
    });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 1,
          working_draft_narrative: answeredTurns("Local idea"),
          node_heads: heads({
            [WorkflowNode.idea_interpretation]: NodeHeadStatus.current,
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
    prepareHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("version conflict");
    expect(screen.getByText("Working Draft: Idea interpretation")).toBeInTheDocument();
    expect(setQueryData).not.toHaveBeenCalled();
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Load current Loop Session" }));
    expect(refetch).toHaveBeenCalled();
    expect(setQueryData).toHaveBeenCalledWith(["/sessions/session-1"], {
      status: 200,
      data: session({
        version: 2,
        title: "Server title",
        working_draft_node: WorkflowNode.idea_interpretation,
        working_draft_narrative: answeredTurns("Server idea"),
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
    prepareHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("not current");
    expect(screen.getByText("Working Draft: Idea decomposition")).toBeInTheDocument();
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("explains an already-current Loop Stage without changing local edits", async () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          version: 2,
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
    const mutateAsync = vi.fn().mockRejectedValue(
      new ApiError(409, "current", {
        code: "stage_already_current",
        detail: "Every Workflow Node in this Loop Stage is current",
      }),
    );
    prepareHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already current");
    expect(screen.getByText("Working Draft: Idea interpretation")).toBeInTheDocument();
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("falls back from an absent or invalid stage query to the Working Draft Loop Stage", () => {
    search = new URLSearchParams("stage=not-a-stage");
    render(<LoopSessionWorkbench sessionId="session-1" />);

    expect(replace).toHaveBeenCalledWith("/sessions/session-1?stage=grilling", { scroll: false });
  });

  it("lists Workflow Nodes and Node Head states for the selected Loop Stage", () => {
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
    const overview = screen.getByRole("region", { name: "Grilling overview" });

    expect(within(overview).getByText("Idea interpretation")).toBeInTheDocument();
    expect(within(overview).getByText(/Node Head: Current/)).toBeInTheDocument();
    expect(within(overview).getByText("Idea decomposition")).toBeInTheDocument();
    expect(within(overview).getByText(/Node Head: Empty/)).toBeInTheDocument();
  });

  it("explains unavailable stages from incomplete upstream Node Heads", () => {
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const overview = screen.getByRole("region", { name: "Related work overview" });

    expect(overview).toHaveTextContent("Unavailable");
    expect(overview).toHaveTextContent("Idea interpretation");
    expect(overview).toHaveTextContent("Idea decomposition");
  });

  it("shows Readiness as Not evaluated with no percentage", () => {
    search = new URLSearchParams(`stage=${LoopStage.readiness}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const overview = screen.getByRole("region", { name: "Readiness overview" });

    expect(overview).toHaveTextContent("Not evaluated");
    expect(overview).not.toHaveTextContent("%");
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
    expect(screen.getByText("Working Draft: Idea decomposition")).toBeInTheDocument();
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

  it("offers Continue after Confirm instead of silently calling recompute-prepare", async () => {
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
    const confirmMutate = vi.fn().mockResolvedValue({ status: 200, data: confirmed });
    const prepareMutate = vi.fn();
    confirmHook.mockReturnValue({ mutateAsync: confirmMutate, error: null });
    prepareHook.mockReturnValue({ mutateAsync: prepareMutate, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(confirmMutate).toHaveBeenCalledTimes(1);
    expect(prepareMutate).not.toHaveBeenCalled();
    expect(
      screen.getByText("Saved. Select Continue to proceed to the next step."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(prepareMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.related_work, expected_version: 9 },
    });
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
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(patchMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { node: WorkflowNode.related_work, expected_version: 9 },
    });
    expect(prepareMutate).not.toHaveBeenCalled();
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
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved. Select Continue to proceed to the next step.",
    );

    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(prepareMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.claims_evidence, expected_version: 13 },
    });
    expect(replace).toHaveBeenCalledWith(
      `/sessions/session-1?stage=${LoopStage.claims_evidence}`,
    );
  });

  it("restores Continue after reloading a just-confirmed Contribution Direction", async () => {
    search = new URLSearchParams(`stage=${LoopStage.contribution}`);
    const confirmedAt = "2026-08-24T11:48:05.482568Z";
    const confirmed = session({
      version: 52,
      working_draft_node: WorkflowNode.contribution,
      updated_at: confirmedAt,
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
      ...confirmed,
      version: 53,
      working_draft_node: WorkflowNode.claims,
    });
    const prepareMutate = vi.fn().mockResolvedValue({ status: 200, data: prepared });
    getHook.mockReturnValue({
      data: { status: 200, data: confirmed },
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
          created_at: confirmedAt,
        }],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    prepareHook.mockReturnValue({ mutateAsync: prepareMutate, error: null });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(prepareMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      data: { stage: LoopStage.claims_evidence, expected_version: 52 },
    });
    expect(replace).toHaveBeenCalledWith(
      `/sessions/session-1?stage=${LoopStage.claims_evidence}`,
    );
  });

  it("does not restore Continue when the Working Draft changed after Confirm", () => {
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
    expect(screen.getByText("Working Draft: Idea interpretation")).toBeInTheDocument();
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
    const overview = screen.getByRole("region", { name: "Readiness overview" });
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });
    const readiness = within(nav).getByRole("link", { name: /Readiness/ });

    expect(overview).toHaveTextContent("Not evaluated");
    expect(overview).not.toHaveTextContent("%");
    expect(overview).not.toHaveTextContent("Complete");
    expect(readiness).toHaveTextContent("Not evaluated");
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
