import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoopSessionTitleEditor } from "./LoopSessionTitleEditor";

const getHook = vi.fn();
const patchHook = vi.fn();
const setQueryData = vi.fn();
const invalidateQueries = vi.fn();

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQueryClient: () => ({ setQueryData, invalidateQueries }),
  };
});

vi.mock("@/lib/api/generated/endpoints", () => ({
  getGetSessionApiLoopSessionsSessionIdGetQueryKey: (id: string) => [`/sessions/${id}`],
  getListSessionsApiLoopSessionsGetQueryKey: () => ["/sessions"],
  useGetSessionApiLoopSessionsSessionIdGet: (...args: unknown[]) => getHook(...args),
  usePatchSessionApiLoopSessionsSessionIdPatch: (...args: unknown[]) => patchHook(...args),
}));

describe("LoopSessionTitleEditor", () => {
  beforeEach(() => {
    setQueryData.mockReset();
    invalidateQueries.mockReset();
    getHook.mockReset();
    patchHook.mockReset();
  });

  it("patches the title without expected_version and shows Saved", async () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: { id: "one", title: "Original", version: 1, updated_at: "t0" },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    const mutateAsync = vi.fn().mockResolvedValue({
      status: 200,
      data: { id: "one", title: "My title", version: 1, updated_at: "t1" },
    });
    patchHook.mockReturnValue({ mutateAsync, error: null });

    render(<LoopSessionTitleEditor sessionId="one" />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const input = screen.getByRole("textbox", { name: "Loop Session title" });
    await userEvent.clear(input);
    await userEvent.type(input, "My title");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(mutateAsync.mock.calls[0][0]).toEqual({
      sessionId: "one",
      data: { title: "My title" },
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(setQueryData).toHaveBeenCalled();
  });

  it("keeps the editor open and shows Save failed when the patch fails", async () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: { id: "one", title: "Original", version: 1 },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    patchHook.mockReturnValue({
      mutateAsync: vi.fn().mockRejectedValue(new Error("offline")),
      error: new Error("offline"),
    });

    render(<LoopSessionTitleEditor sessionId="one" />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const input = screen.getByRole("textbox", { name: "Loop Session title" });
    await userEvent.clear(input);
    await userEvent.type(input, "My title");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Save failed")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Loop Session title" })).toHaveValue("My title");
    expect(screen.queryByText("Title conflict")).not.toBeInTheDocument();
  });

  it("shows the saved title until Edit or the title is clicked", async () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: { id: "one", title: "Original", version: 1 },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    patchHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });

    render(<LoopSessionTitleEditor sessionId="one" />);

    expect(screen.queryByRole("textbox", { name: "Loop Session title" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Original" }));
    expect(screen.getByRole("textbox", { name: "Loop Session title" })).toHaveValue("Original");
  });

  it("cancels title edits and returns to the saved heading", async () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: { id: "one", title: "Original", version: 1 },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    patchHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });

    render(<LoopSessionTitleEditor sessionId="one" />);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const input = screen.getByRole("textbox", { name: "Loop Session title" });
    await userEvent.clear(input);
    await userEvent.type(input, "Scratch title");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Original" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("shows loading and failure states", () => {
    getHook.mockReturnValueOnce({ isLoading: true, isError: false });
    patchHook.mockReturnValue({ mutateAsync: vi.fn(), error: null });
    const { rerender } = render(<LoopSessionTitleEditor sessionId="one" />);
    expect(screen.getByText("Loading Loop Session…")).toBeInTheDocument();

    getHook.mockReturnValueOnce({ isLoading: false, isError: true, refetch: vi.fn() });
    rerender(<LoopSessionTitleEditor sessionId="one" />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not load");
  });
});
