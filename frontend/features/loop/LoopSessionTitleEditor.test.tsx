import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";

import { LoopSessionTitleEditor } from "./LoopSessionTitleEditor";
import { LoopSessionSaveProvider } from "./loop-session-save";

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

  it("preserves local and server titles and retries only after explicit conflict resolution", async () => {
    const refetch = vi.fn().mockResolvedValue({
      data: {
        status: 200,
        data: { id: "one", title: "Server title", version: 2 },
      },
    });
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: { id: "one", title: "Original", version: 1 },
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
        data: { id: "one", title: "My title", version: 3 },
      });
    patchHook.mockReturnValue({ mutateAsync });

    render(
      <LoopSessionSaveProvider>
        <LoopSessionTitleEditor sessionId="one" />
      </LoopSessionSaveProvider>,
    );
    const input = screen.getByRole("textbox", { name: "Loop Session title" });
    await userEvent.clear(input);
    await userEvent.type(input, "My title");
    await userEvent.click(screen.getByRole("button", { name: "Save title" }));

    expect(await screen.findByText("My title", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Server title", { selector: "dd" })).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Keep my title" }));

    expect(mutateAsync).toHaveBeenCalledTimes(2);
    expect(mutateAsync.mock.calls[1][0].data.expected_version).toBe(2);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("keeps the local title while retrying a failed conflict refresh", async () => {
    let refetchFailed = false;
    const refetch = vi
      .fn()
      .mockImplementationOnce(async () => {
        refetchFailed = true;
        throw new Error("offline");
      })
      .mockResolvedValueOnce({
        data: {
          status: 200,
          data: { id: "one", title: "Server title", version: 2 },
        },
      });
    getHook.mockImplementation(() => ({
      data: {
        status: 200,
        data: { id: "one", title: "Original", version: 1 },
      },
      isLoading: false,
      isError: refetchFailed,
      refetch,
    }));
    patchHook.mockReturnValue({
      mutateAsync: vi.fn().mockRejectedValue(
        new ApiError(409, "changed", {
          code: "version_conflict",
          detail: "changed",
          current_version: 2,
        }),
      ),
    });

    render(
      <LoopSessionSaveProvider>
        <LoopSessionTitleEditor sessionId="one" />
      </LoopSessionSaveProvider>,
    );
    const input = screen.getByRole("textbox", { name: "Loop Session title" });
    await userEvent.clear(input);
    await userEvent.type(input, "My local title");
    await userEvent.click(screen.getByRole("button", { name: "Save title" }));

    expect(await screen.findByText("My local title", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Could not load the current server title.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep my title" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Retry loading server title" }));

    expect(await screen.findByText("Server title", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep my title" })).toBeEnabled();
  });

  it("edits the title inline without a permanent title editor panel", () => {
    getHook.mockReturnValue({
      data: {
        status: 200,
        data: { id: "one", title: "Original", version: 1 },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    patchHook.mockReturnValue({ mutateAsync: vi.fn() });

    render(
      <LoopSessionSaveProvider>
        <LoopSessionTitleEditor sessionId="one" />
      </LoopSessionSaveProvider>,
    );

    expect(screen.getByRole("textbox", { name: "Loop Session title" })).toBeInTheDocument();
    expect(
      screen.queryByText("Rename this Loop Session without overwriting newer changes"),
    ).not.toBeInTheDocument();
  });

  it("shows loading and failure states", () => {
    getHook.mockReturnValueOnce({ isLoading: true, isError: false });
    patchHook.mockReturnValue({ mutateAsync: vi.fn() });
    const { rerender } = render(
      <LoopSessionSaveProvider>
        <LoopSessionTitleEditor sessionId="one" />
      </LoopSessionSaveProvider>,
    );
    expect(screen.getByText("Loading Loop Session…")).toBeInTheDocument();

    getHook.mockReturnValueOnce({ isLoading: false, isError: true, refetch: vi.fn() });
    rerender(
      <LoopSessionSaveProvider>
        <LoopSessionTitleEditor sessionId="one" />
      </LoopSessionSaveProvider>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("could not load");
  });
});
