import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { WorkingDraftNarrativeEditor } from "./WorkingDraftNarrativeEditor";
import { LoopSessionSaveProvider } from "./loop-session-save";

const getHook = vi.fn();
const patchHook = vi.fn();
const setQueryData = vi.fn();

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQueryClient: () => ({ setQueryData }),
  };
});

vi.mock("@/lib/api/generated/endpoints", () => ({
  getGetSessionApiLoopSessionsSessionIdGetQueryKey: (id: string) => [`/sessions/${id}`],
  useGetSessionApiLoopSessionsSessionIdGet: (...args: unknown[]) => getHook(...args),
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch: (...args: unknown[]) =>
    patchHook(...args),
}));

function session(overrides: Partial<LoopSessionResponse> = {}): LoopSessionResponse {
  return {
    id: "session-1",
    title: "GPU kernels",
    version: 1,
    working_draft_node: WorkflowNode.idea_interpretation,
    working_draft_narrative: {},
    node_heads: [],
    cards: [],
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-15T10:00:00Z",
    updated_at: "2026-08-16T10:00:00Z",
    ...overrides,
  };
}

describe("WorkingDraftNarrativeEditor", () => {
  beforeEach(() => {
    setQueryData.mockReset();
    getHook.mockReset();
    patchHook.mockReset();
  });

  it("autosaves narrative.text while preserving unknown fields", async () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          working_draft_narrative: { extra: 7, schema: "keep-me", text: "old idea" },
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 200,
      data: session({
        version: 2,
        working_draft_narrative: { extra: 7, schema: "keep-me", text: "GPU kernels" },
      }),
    });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(
      <LoopSessionSaveProvider>
        <WorkingDraftNarrativeEditor sessionId="session-1" />
      </LoopSessionSaveProvider>,
    );
    const editor = screen.getByRole("textbox", { name: "Working Draft narrative" });
    expect(screen.getByText(/Correct the grilling transcript/i)).toBeInTheDocument();
    await userEvent.clear(editor);
    await userEvent.type(editor, "GPU kernels");

    await vi.waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        sessionId: "session-1",
        data: {
          expected_version: 1,
          narrative: { extra: 7, schema: "keep-me", text: "GPU kernels" },
        },
      }),
    );
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("preserves local and server Working Draft text and retries only after explicit approval", async () => {
    const refetch = vi.fn().mockResolvedValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          working_draft_narrative: { extra: "server-only", text: "Server idea" },
        }),
      },
    });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({ working_draft_narrative: { extra: "old", text: "Original" } }),
      },
      isLoading: false,
      isError: false,
      refetch,
    });
    const mutateAsync = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(409, "changed", {
          code: "version_conflict",
          detail: "changed",
          current_version: 2,
        }),
      )
      .mockResolvedValueOnce({
        status: 200,
        data: session({
          version: 3,
          working_draft_narrative: { extra: "server-only", text: "My idea" },
        }),
      });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(
      <LoopSessionSaveProvider>
        <WorkingDraftNarrativeEditor sessionId="session-1" />
      </LoopSessionSaveProvider>,
    );
    const editor = screen.getByRole("textbox", { name: "Working Draft narrative" });
    await userEvent.clear(editor);
    await userEvent.type(editor, "My idea");

    expect(await screen.findByText("My idea", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Server idea", { selector: "dd" })).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Keep my Working Draft" }));

    expect(mutateAsync).toHaveBeenCalledTimes(2);
    expect(mutateAsync.mock.calls[1][0].data).toEqual({
      expected_version: 2,
      narrative: { extra: "server-only", text: "My idea" },
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("shows Save failed and does not treat the edit as durable", async () => {
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    patchHook.mockReturnValue({
      mutateAsync: vi.fn().mockRejectedValue(new ApiError(500, "offline")),
      error: new ApiError(500, "offline"),
    });

    render(
      <LoopSessionSaveProvider>
        <WorkingDraftNarrativeEditor sessionId="session-1" />
      </LoopSessionSaveProvider>,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Working Draft narrative" }), "idea");

    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("flushes a pending Working Draft autosave when the editor unmounts", async () => {
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 200,
      data: session({ version: 2, working_draft_narrative: { text: "idea" } }),
    });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    const { unmount } = render(
      <LoopSessionSaveProvider>
        <WorkingDraftNarrativeEditor sessionId="session-1" />
      </LoopSessionSaveProvider>,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Working Draft narrative" }), "idea");
    unmount();
    await vi.waitFor(() => expect(mutateAsync).toHaveBeenCalled());
  });
});
