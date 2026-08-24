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

function answeredTurns(text = "GPU kernel latency"): Record<string, unknown> {
  return {
    exhausted: true,
    turns: [
      { role: "account", kind: "idea", text },
      { role: "model", preamble: "No further questions.", questions: [] },
    ],
  };
}

function unansweredTurns(): Record<string, unknown> {
  return {
    exhausted: false,
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

  it("shows Contribution Direction within the six navigable Loop Stages", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);
    const nav = screen.getByRole("navigation", { name: "Loop Stages" });

    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual([
      expect.stringContaining("Grilling"),
      expect.stringContaining("Related work"),
      expect.stringContaining("Claims/evidence"),
      expect.stringContaining("Experiment planning"),
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
    expect(within(nav).queryByRole("link", { name: /^Contribution/ })).not.toBeInTheDocument();
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

  it("prevents Confirm when the Working Draft has neither nonblank narrative text nor a nonblank owned Card", () => {
    search = new URLSearchParams(`stage=${LoopStage.grilling}`);
    render(<LoopSessionWorkbench sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
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
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
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
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
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
    search = new URLSearchParams(`stage=${LoopStage.related_work}`);
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

  it("shows empty Decision history and Produced Spec Version states", () => {
    render(<LoopSessionWorkbench sessionId="session-1" />);

    const history = screen.getByRole("region", { name: "Decision history" });
    expect(history).toHaveTextContent("Decision history");
    expect(history).toHaveTextContent("No Decisions");
    expect(history).toHaveTextContent(
      "Decision history does not include snapshot content, version diff, or revert",
    );
    expect(screen.queryByRole("button", { name: /revert/i })).not.toBeInTheDocument();

    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("No Produced Spec Version");
    expect(spec).not.toHaveTextContent("latest spec");
    expect(spec).not.toHaveTextContent("Draft Research Spec");
    expect(spec).not.toHaveTextContent("Final Spec");
  });

  it("shows Decision kind, Workflow Node, timestamp, and Stage Revision id", () => {
    decisionsHook.mockReturnValue({
      data: {
        status: 200,
        data: [
          {
            id: "decision-1",
            kind: "confirm",
            node: WorkflowNode.idea_interpretation,
            stage_revision_id: "revision-abc",
            created_at: "2026-08-16T10:00:00Z",
          },
        ],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const history = screen.getByRole("region", { name: "Decision history" });

    expect(history).toHaveTextContent("confirm");
    expect(history).toHaveTextContent("Idea interpretation");
    expect(history).toHaveTextContent("Aug 16, 2026, 10:00 AM UTC");
    expect(history).toHaveTextContent("revision-abc");
    expect(history).not.toHaveTextContent("No Decisions");
    expect(screen.queryByRole("button", { name: /diff|revert|snapshot/i })).not.toBeInTheDocument();
  });

  it("renders a Produced Spec Version read-only in Loop Stage order", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          produced_spec_version: {
            id: "spec-valid",
            created_at: "2026-08-16T12:00:00Z",
            document: {
              nodes: {
                contribution: {
                  narrative: { text: "A fused kernel scheduler" },
                  card_snapshot: [
                    {
                      id: "card-1",
                      kind: CardKind.contribution,
                      body: { text: "Schedule overlapping copies" },
                    },
                  ],
                },
                idea_interpretation: {
                  narrative: { text: "Latency in GPU kernels" },
                  card_snapshot: [],
                },
              },
            },
          },
          valid_spec_version_id: "spec-valid",
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    const text = spec.textContent ?? "";

    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("Valid Spec Version");
    expect(spec).not.toHaveTextContent("Stale");
    expect(spec).toHaveTextContent("Grilling");
    expect(spec).toHaveTextContent("Latency in GPU kernels");
    expect(spec).toHaveTextContent("Contribution");
    expect(spec).toHaveTextContent("A fused kernel scheduler");
    expect(spec).toHaveTextContent("Schedule overlapping copies");
    expect(text.indexOf("Grilling")).toBeGreaterThan(-1);
    expect(text.indexOf("Grilling")).toBeLessThan(text.indexOf("Contribution"));
    expect(spec).not.toHaveTextContent("latest spec");
    expect(spec).not.toHaveTextContent("Draft Research Spec");
    expect(spec).not.toHaveTextContent("Final Spec");
    expect(within(spec).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("renders a legacy Produced Spec Version Gap only once", () => {
    const gap = {
      statement: "Research loops need multi-benchmark verification.",
      status: "candidate",
    };
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          produced_spec_version: {
            id: "spec-valid",
            created_at: "2026-08-16T12:00:00Z",
            document: {
              nodes: {
                gap: {
                  narrative: { candidate: gap },
                  card_snapshot: [
                    {
                      id: "gap-card",
                      kind: CardKind.gap,
                      body: gap,
                    },
                  ],
                },
              },
            },
          },
          valid_spec_version_id: "spec-valid",
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    const occurrences = spec.textContent?.match(/Research loops need multi-benchmark verification\./g);

    expect(occurrences).toHaveLength(1);
    expect(spec.textContent).not.toMatch(/"candidate"\s*:/);
  });

  it("keeps unknown Produced Spec Version fields visible as JSON", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          produced_spec_version: {
            id: "spec-valid",
            created_at: "2026-08-16T12:00:00Z",
            document: {
              assembler: "v2",
              nodes: {
                idea_interpretation: {
                  narrative: { text: "Known idea", schema: "keep-me" },
                  card_snapshot: [
                    {
                      id: "card-1",
                      kind: CardKind.problem,
                      body: { text: "Bandwidth", extra: 3 },
                    },
                  ],
                  future_field: { score: 9 },
                },
              },
            },
          },
          valid_spec_version_id: "spec-valid",
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<LoopSessionWorkbench sessionId="session-1" />);
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Known idea");
    expect(spec).toHaveTextContent("Bandwidth");
    expect(spec).toHaveTextContent('"schema": "keep-me"');
    expect(spec).toHaveTextContent('"extra": 3');
    expect(spec).toHaveTextContent('"score": 9');
    expect(spec).toHaveTextContent('"assembler": "v2"');
  });

  it("marks a Produced Spec Version Stale when it is not the Valid Spec Version", () => {
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
    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("Valid Spec Version");
    expect(spec).toHaveTextContent("Earlier understanding");
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

  it("refreshes Decisions, Produced Spec Version, and dashboard queries after Confirm", async () => {
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
    expect(screen.getByRole("region", { name: "Produced Spec Version" })).toHaveTextContent(
      "No Produced Spec Version",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(screen.getByRole("region", { name: "Produced Spec Version" })).toHaveTextContent(
      "Confirmed interpretation",
    );
    expect(screen.getByRole("region", { name: "Produced Spec Version" })).toHaveTextContent(
      "Valid Spec Version",
    );
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["/api/loop/sessions/session-1/decisions"],
    });
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["/api/loop/sessions"],
    });
  });
});
