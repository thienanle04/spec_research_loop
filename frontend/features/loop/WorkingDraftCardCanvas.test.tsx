import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import { CardKind, WorkflowNode, type CardResponse, type LoopSessionResponse } from "@/lib/api/generated/model";

import { WorkingDraftCardCanvas } from "./WorkingDraftCardCanvas";
import { LoopSessionSaveProvider } from "./loop-session-save";

const getHook = vi.fn();
const createHook = vi.fn();
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
  useCreateCardApiLoopSessionsSessionIdCardsPost: (...args: unknown[]) => createHook(...args),
  usePatchCardApiLoopSessionsSessionIdCardsCardIdPatch: (...args: unknown[]) => patchHook(...args),
}));

function card(overrides: Partial<CardResponse> = {}): CardResponse {
  return {
    id: "card-1",
    kind: CardKind.problem,
    body: { text: "Memory bandwidth" },
    created_at: "2026-08-15T10:00:00Z",
    updated_at: "2026-08-15T10:00:00Z",
    ...overrides,
  };
}

function session(overrides: Partial<LoopSessionResponse> = {}): LoopSessionResponse {
  return {
    id: "session-1",
    title: "GPU kernels",
    version: 1,
    working_draft_node: WorkflowNode.idea_decomposition,
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

function renderCanvas() {
  return render(
    <LoopSessionSaveProvider>
      <WorkingDraftCardCanvas sessionId="session-1" />
    </LoopSessionSaveProvider>,
  );
}

describe("WorkingDraftCardCanvas", () => {
  beforeEach(() => {
    setQueryData.mockReset();
    getHook.mockReset();
    createHook.mockReset();
    patchHook.mockReset();
    createHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });
    patchHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });
  });

  it("offers only Card kinds owned by the Working Draft Workflow Node", () => {
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderCanvas();

    expect(screen.getByRole("button", { name: "Add Problem" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Research question" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Constraint" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Open question" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add Gap" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add Claim" })).not.toBeInTheDocument();
  });

  it("offers no Card kinds when the Working Draft Workflow Node owns none", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({ working_draft_node: WorkflowNode.idea_interpretation }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderCanvas();

    expect(screen.queryByRole("button", { name: /^Add / })).not.toBeInTheDocument();
  });

  it("keeps every offered Card kind repeatable", async () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({ cards: [card()] }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderCanvas();
    await userEvent.click(screen.getByRole("button", { name: "Add Problem" }));
    await userEvent.click(screen.getByRole("button", { name: "Add Problem" }));

    expect(screen.getAllByRole("textbox", { name: "Problem Card" })).toHaveLength(1);
    expect(screen.getAllByRole("textbox", { name: "New Problem Card" })).toHaveLength(2);
  });

  it("cancels empty Card creation before persistence", async () => {
    const mutateAsync = vi.fn();
    createHook.mockReturnValue({ mutateAsync, error: null });
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderCanvas();
    await userEvent.click(screen.getByRole("button", { name: "Add Problem" }));
    const draft = screen.getByRole("textbox", { name: "New Problem Card" });
    await userEvent.type(draft, "   ");
    await userEvent.click(screen.getByRole("button", { name: "Cancel new Problem Card" }));

    expect(screen.queryByRole("textbox", { name: "New Problem Card" })).not.toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("persists a new Card after non-empty text", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 201,
      data: {
        ...card({ id: "card-new", body: { text: "GPU kernels" } }),
        version: 2,
      },
    });
    createHook.mockReturnValue({ mutateAsync, error: null });
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderCanvas();
    await userEvent.click(screen.getByRole("button", { name: "Add Problem" }));
    await userEvent.type(screen.getByRole("textbox", { name: "New Problem Card" }), "GPU kernels");

    await vi.waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        sessionId: "session-1",
        data: {
          expected_version: 1,
          kind: CardKind.problem,
          body: { text: "GPU kernels" },
        },
      }),
    );
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("retries a new Card after explicit conflict approval", async () => {
    const refetch = vi.fn().mockResolvedValue({
      data: { status: 200, data: session({ version: 2, cards: [] }) },
    });
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
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
        status: 201,
        data: {
          ...card({ id: "card-new", body: { text: "My problem" } }),
          version: 3,
        },
      });
    createHook.mockReturnValue({ mutateAsync, error: null });

    renderCanvas();
    await userEvent.click(screen.getByRole("button", { name: "Add Problem" }));
    await userEvent.type(screen.getByRole("textbox", { name: "New Problem Card" }), "My problem");

    expect(await screen.findByText("My problem", { selector: "dd" })).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Keep my Card" }));

    expect(mutateAsync).toHaveBeenCalledTimes(2);
    expect(mutateAsync.mock.calls[1][0].data).toEqual({
      expected_version: 2,
      kind: CardKind.problem,
      body: { text: "My problem" },
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("lets persisted Cards stay editable and offers no delete or archive action", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({ cards: [card()] }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderCanvas();

    expect(screen.getByRole("textbox", { name: "Problem Card" })).toHaveValue("Memory bandwidth");
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /archive/i })).not.toBeInTheDocument();
  });

  it("autosaves Card body.text while preserving unknown fields", async () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          cards: [card({ body: { extra: 7, schema: "keep-me", text: "old problem" } })],
        }),
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 200,
      data: {
        ...card({ body: { extra: 7, schema: "keep-me", text: "GPU kernels" } }),
        version: 2,
      },
    });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    renderCanvas();
    const editor = screen.getByRole("textbox", { name: "Problem Card" });
    await userEvent.clear(editor);
    await userEvent.type(editor, "GPU kernels");

    await vi.waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        sessionId: "session-1",
        cardId: "card-1",
        data: {
          expected_version: 1,
          body: { extra: 7, schema: "keep-me", text: "GPU kernels" },
        },
      }),
    );
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("preserves local and server Card text and retries only after explicit approval", async () => {
    const refetch = vi.fn().mockResolvedValue({
      data: {
        status: 200,
        data: session({
          version: 2,
          cards: [card({ body: { extra: "server-only", text: "Server problem" } })],
        }),
      },
    });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: session({
          cards: [card({ body: { extra: "old", text: "Original" } })],
        }),
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
        data: {
          ...card({ body: { extra: "server-only", text: "My problem" } }),
          version: 3,
        },
      });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    renderCanvas();
    const editor = screen.getByRole("textbox", { name: "Problem Card" });
    await userEvent.clear(editor);
    await userEvent.type(editor, "My problem");

    expect(await screen.findByText("My problem", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Server problem", { selector: "dd" })).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Keep my Card" }));

    expect(mutateAsync).toHaveBeenCalledTimes(2);
    expect(mutateAsync.mock.calls[1][0].data).toEqual({
      expected_version: 2,
      body: { extra: "server-only", text: "My problem" },
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("on grilling layout seeds one problem and research-question slot and only Adds many kinds", async () => {
    getHook.mockReturnValue({
      data: { status: 200, data: session() },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(
      <LoopSessionSaveProvider>
        <WorkingDraftCardCanvas layout="grilling" sessionId="session-1" />
      </LoopSessionSaveProvider>,
    );

    expect(screen.queryByRole("button", { name: "Add Problem" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add Research question" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Constraint" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Open question" })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    expect(screen.getByRole("textbox", { name: "New Problem Card" })).toBeInTheDocument();
  });
});
