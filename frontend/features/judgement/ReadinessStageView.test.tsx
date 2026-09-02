import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { EXPORT_SCRATCH_AUTOSAVE_MS, ReadinessStageView } from "./ReadinessStageView";

const navTest = vi.hoisted(() => {
  const React = require("react") as typeof import("react");
  const NavContext = React.createContext<{
    search: URLSearchParams;
    replace: (href: string) => void;
  } | null>(null);

  function MemoryNav({ children }: { children: React.ReactNode }) {
    const [search, setSearch] = React.useState(() => new URLSearchParams());
    const replace = React.useCallback((href: string) => {
      const next = new URLSearchParams(String(href).split("?")[1] ?? "");
      navTest.search = next;
      setSearch(next);
    }, []);
    return React.createElement(NavContext.Provider, { value: { search, replace } }, children);
  }

  function useTestRouter() {
    const nav = React.useContext(NavContext);
    if (!nav) {
      throw new Error("MemoryNav required");
    }
    return { replace: nav.replace, push: () => undefined };
  }

  function useTestSearchParams() {
    const nav = React.useContext(NavContext);
    if (!nav) {
      throw new Error("MemoryNav required");
    }
    return nav.search;
  }

  return {
    search: new URLSearchParams() as URLSearchParams,
    MemoryNav,
    useTestRouter,
    useTestSearchParams,
  };
});

const mocks = vi.hoisted(() => ({
  customFetch: vi.fn(),
}));

vi.mock("@/lib/api/mutator", () => ({
  customFetch: (...args: unknown[]) => mocks.customFetch(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navTest.useTestRouter(),
  useSearchParams: () => navTest.useTestSearchParams(),
}));

vi.mock("./ExportScratchMarkdownEditor", () => ({
  ExportScratchMarkdownEditor: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (next: string) => void;
  }) => (
    <div>
      <textarea
        aria-label="Export Scratch markdown"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <div role="region" aria-label="Export Scratch preview">
        {value}
      </div>
    </div>
  ),
}));

function renderView(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <navTest.MemoryNav>{ui}</navTest.MemoryNav>
    </QueryClientProvider>,
  );
}

function session(state: "not_evaluated" | "blocked" | "ready"): LoopSessionResponse {
  return {
    id: "session-1",
    title: "Readiness test",
    version: 4,
    working_draft_node: WorkflowNode.aggregator,
    working_draft_narrative: {},
    node_heads: [],
    cards: [],
    stage_revisions: [],
    produced_spec_version: null,
    valid_spec_version_id: "spec-1",
    readiness: {
      state,
      notice: "This is not conference acceptance.",
    },
    export_scratch: {
      id: "scratch-1",
      spec_version_id: "spec-1",
      document: {
        markdown: "## 1. Problem Statement\n\n",
      },
      created_at: "2026-08-30T00:00:00Z",
      updated_at: "2026-08-30T00:00:00Z",
    },
    export_scratch_snapshots: [
      {
        id: "snap-1",
        spec_version_id: "spec-1",
        snapshot_n: 1,
        document: {
          markdown: "Original projection\n",
        },
        created_at: "2026-08-30T00:00:00Z",
      },
    ],
    spec_versions: [
      {
        id: "spec-1",
        created_at: "2026-08-30T00:00:00Z",
        valid: true,
      },
    ],
    clarification_review: {
      original_idea: "GPU kernel latency",
      gap: "The literature has not measured tiling DRAM traffic.",
      contribution: "A tiling schedule that cuts DRAM traffic",
      claims: ["Tiling cuts DRAM traffic by at least 20%"],
    },
    created_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
  };
}

describe("ReadinessStageView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navTest.search = new URLSearchParams();
    mocks.customFetch.mockImplementation(async (url: string) => {
      if (
        typeof url === "string" &&
        url.endsWith("/export-scratch")
      ) {
        return { status: 200, data: session("ready"), headers: new Headers() };
      }
      if (typeof url === "string" && url.includes("spec-artifact")) {
        return {
          status: 200,
          data: { spec_version_id: "spec-1", document: { nodes: {} } },
          headers: new Headers(),
        };
      }
      const isPdf = typeof url === "string" && url.includes("/pdf");
      return {
        status: 200,
        data: isPdf
          ? new Uint8Array([0x25, 0x50, 0x44, 0x46]).buffer
          : "## 1. Problem Statement\n",
        headers: {
          get: (name: string) =>
            name === "content-disposition"
              ? `attachment; filename="export-scratch-spec-1.${isPdf ? "pdf" : "md"}"`
              : name === "content-type"
                ? isPdf
                  ? "application/pdf"
                  : "text/markdown; charset=utf-8"
                : null,
        },
      };
    });
    vi.stubGlobal(
      "URL",
      class {
        static createObjectURL = vi.fn(() => "blob:export-scratch");
        static revokeObjectURL = vi.fn();
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("downloads Export Scratch markdown with one click when Readiness is ready", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export Scratch markdown" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch",
        expect.objectContaining({ method: "PATCH" }),
      );
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/markdown?spec_version_id=spec-1",
        expect.objectContaining({
          method: "POST",
        }),
      );
    });
    const patchIndex = mocks.customFetch.mock.calls.findIndex(
      (call) => call[0] === "/api/loop/sessions/session-1/export-scratch",
    );
    const markdownIndex = mocks.customFetch.mock.calls.findIndex((call) =>
      String(call[0]).includes("/export-scratch/markdown"),
    );
    expect(patchIndex).toBeGreaterThanOrEqual(0);
    expect(markdownIndex).toBeGreaterThan(patchIndex);
    expect(mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("spec-artifact"))).toBe(
      false,
    );
    expect(screen.getByRole("status", { name: "Export Scratch markdown" })).toHaveTextContent(
      "Export Scratch markdown downloaded.",
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.queryByText("Blocked")).not.toBeInTheDocument();
  });

  it("asks for Critical Export Confirmation on each blocked Export Spec download", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("blocked")} sessionId="session-1" />);
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export Scratch markdown" }));
    expect(mocks.customFetch).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Critical Export Confirmation" });
    expect(dialog).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm export" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch",
        expect.objectContaining({ method: "PATCH" }),
      );
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/markdown?spec_version_id=spec-1",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ critical_export_ack: true }),
        }),
      );
    });
    expect(mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("spec-artifact"))).toBe(
      false,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Export Scratch markdown" })).toHaveTextContent(
      "Export Scratch markdown downloaded.",
    );
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
  });

  it("downloads Export Scratch PDF from a distinct control when Readiness is ready", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Export Scratch markdown" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Download PDF" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch",
        expect.objectContaining({ method: "PATCH" }),
      );
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/pdf?spec_version_id=spec-1",
        expect.objectContaining({
          method: "POST",
        }),
      );
    });
    expect(mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("markdown"))).toBe(
      false,
    );
    expect(mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("spec-artifact"))).toBe(
      false,
    );
    expect(screen.getByRole("status", { name: "Download PDF" })).toHaveTextContent(
      "Export Scratch PDF downloaded.",
    );
  });

  it("asks for Critical Export Confirmation on each blocked PDF download", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("blocked")} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Download PDF" }));
    expect(mocks.customFetch).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Critical Export Confirmation" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm export" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch",
        expect.objectContaining({ method: "PATCH" }),
      );
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/pdf?spec_version_id=spec-1",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ critical_export_ack: true }),
        }),
      );
    });
    expect(mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("markdown"))).toBe(
      false,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Download PDF" })).toHaveTextContent(
      "Export Scratch PDF downloaded.",
    );
    expect(screen.getByText("Blocked")).toBeInTheDocument();
  });

  it("exports Spec Artifact JSON with one click when Readiness is ready", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Spec Artifact JSON" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/spec-artifact",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(
      mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("export-scratch/markdown")),
    ).toBe(false);
    expect(screen.getByRole("status", { name: "Spec Artifact JSON" })).toHaveTextContent(
      "Spec Artifact JSON downloaded.",
    );
  });

  it("asks for Critical Export Confirmation on blocked Spec Artifact JSON", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("blocked")} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Spec Artifact JSON" }));
    expect(
      mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("spec-artifact")),
    ).toBe(false);
    expect(screen.getByRole("dialog", { name: "Critical Export Confirmation" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm export" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/spec-artifact",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ critical_export_ack: true }),
        }),
      );
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
  });

  it("hides the Export Scratch editor until Edit Export Scratch", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Edit Export Scratch" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Export Scratch markdown" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Export Scratch preview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Export Scratch overlay" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save Export Scratch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save Snapshot" })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Export Scratch Snapshots" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm export" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    expect(screen.getByRole("textbox", { name: "Export Scratch markdown" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Export Scratch preview" })).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Export Scratch editor" }).querySelector(".flex-1"),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Snapshot" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit Export Scratch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save Export Scratch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Spec Version" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Export Scratch Snapshots" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export Scratch markdown" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "Export Scratch overlay" }),
    ).toHaveTextContent(/Export Scratch, not the Research Spec/);
  });

  it("closes the editor on Done without patching an unchanged Export Scratch", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(mocks.customFetch).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: "Export Scratch markdown" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit Export Scratch" })).toBeInTheDocument();
  });

  it("patches a dirty Export Scratch on Done then closes the editor", async () => {
    const user = userEvent.setup();
    const draft = session("ready");
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        ...draft,
        version: 5,
        export_scratch: {
          ...draft.export_scratch,
          document: {
            markdown: "Edited overlay body",
          },
        },
      },
    });
    renderView(<ReadinessStageView session={draft} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    const source = screen.getByRole("textbox", { name: "Export Scratch markdown" });
    await user.clear(source);
    await user.type(source, "Edited overlay body");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
    expect(screen.queryByRole("textbox", { name: "Export Scratch markdown" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit Export Scratch" })).toBeInTheDocument();
  });

  it("keeps the editor open when Done patch fails", async () => {
    const user = userEvent.setup();
    mocks.customFetch.mockResolvedValue({
      status: 409,
      data: { detail: "Loop Session was changed by another request" },
    });
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    const source = screen.getByRole("textbox", { name: "Export Scratch markdown" });
    await user.clear(source);
    await user.type(source, "Edited overlay body");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Export Scratch overlay was not saved");
    });
    expect(screen.getByRole("textbox", { name: "Export Scratch markdown" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("shows the Export Scratch banner only while editing and saves overlay edits", async () => {
    const user = userEvent.setup();
    const draft = session("ready");
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: {
        ...draft,
        version: 5,
        export_scratch: {
          ...draft.export_scratch,
          document: {
            markdown: "Edited overlay body",
          },
        },
      },
    });
    renderView(<ReadinessStageView session={draft} sessionId="session-1" />);
    expect(screen.queryByRole("status", { name: "Export Scratch overlay" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    expect(
      screen.getByRole("status", { name: "Export Scratch overlay" }),
    ).toHaveTextContent(/Export Scratch, not the Research Spec/);
    expect(screen.queryByRole("button", { name: "Save Export Scratch" })).not.toBeInTheDocument();
    const source = screen.getByRole("textbox", { name: "Export Scratch markdown" });
    await user.clear(source);
    await user.type(source, "Edited overlay body");
    await waitFor(
      () => {
        expect(mocks.customFetch).toHaveBeenCalledWith(
          "/api/loop/sessions/session-1/export-scratch",
          expect.objectContaining({ method: "PATCH" }),
        );
      },
      { timeout: EXPORT_SCRATCH_AUTOSAVE_MS + 1500 },
    );
    const body = JSON.parse(
      (mocks.customFetch.mock.calls.find(
        (call) =>
          call[0] === "/api/loop/sessions/session-1/export-scratch",
      )?.[1] as { body: string }).body,
    );
    expect(body.expected_version).toBe(4);
    expect(body.document.markdown).toBe("Edited overlay body");
    expect(screen.getByRole("textbox", { name: "Export Scratch markdown" })).toHaveValue(
      "Edited overlay body",
    );
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("lists Spec Versions and loads a selected Export Scratch without changing Readiness", async () => {
    const user = userEvent.setup();
    const draft = session("ready");
    const older = {
      ...draft,
      spec_versions: [
        { id: "spec-0", created_at: "2026-08-29T00:00:00Z", valid: false },
        { id: "spec-1", created_at: "2026-08-30T00:00:00Z", valid: true },
      ],
      export_scratch: {
        ...draft.export_scratch!,
        spec_version_id: "spec-0",
        document: {
          markdown: "Older gap body",
        },
      },
      clarification_review: {
        original_idea: "GPU kernel latency",
        gap: "Older gap body",
        contribution: "Older contribution",
        claims: ["Older claim"],
      },
      readiness: draft.readiness,
    };
    mocks.customFetch.mockResolvedValue({ status: 200, data: older });
    renderView(
      <ReadinessStageView
        session={{
          ...draft,
          spec_versions: older.spec_versions,
        }}
        sessionId="session-1"
      />,
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
    const picker = screen.getByRole("combobox", { name: "Spec Version" });
    await user.selectOptions(picker, "spec-0");
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1?spec_version_id=spec-0",
        expect.objectContaining({ method: "GET" }),
      );
    });
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "Spec Version not Valid" }),
    ).toHaveTextContent(/not Valid/);
    expect(
      mocks.customFetch.mock.calls.some(
        (call) => call[0] === "/api/loop/sessions/session-1/export-scratch",
      ),
    ).toBe(false);
    expect(screen.queryByRole("textbox", { name: "Export Scratch markdown" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    expect(screen.getByRole("textbox", { name: "Export Scratch markdown" })).toHaveValue(
      "Older gap body",
    );
  });

  it("shows derived Clarification Review for the selected Spec Version", () => {
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    const panel = screen.getByRole("region", { name: "Clarification Review" });
    expect(panel).toHaveTextContent("GPU kernel latency");
    expect(panel).toHaveTextContent("This Spec Version in brief");
    expect(panel).toHaveTextContent(
      "The literature has not measured tiling DRAM traffic. A tiling schedule that cuts DRAM traffic. Tiling cuts DRAM traffic by at least 20%.",
    );
    expect(screen.queryByRole("combobox", { name: "Claims" })).not.toBeInTheDocument();
  });

  it("lists Export Scratch Snapshots and loads one into the buffer", async () => {
    const user = userEvent.setup();
    const draft = session("ready");
    const restored = {
      ...draft,
      version: 5,
      export_scratch: {
        ...draft.export_scratch!,
        document: {
          markdown: "Original projection",
        },
      },
    };
    mocks.customFetch.mockResolvedValue({ status: 200, data: restored });
    renderView(<ReadinessStageView session={draft} sessionId="session-1" />);
    const list = screen.getByRole("list", { name: "Export Scratch Snapshots" });
    expect(list).toHaveTextContent("Snapshot 1");
    await user.click(screen.getByRole("button", { name: "Load Snapshot 1" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/snapshots/snap-1/restore",
        expect.objectContaining({ method: "POST" }),
      );
    });
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    expect(screen.getByRole("textbox", { name: "Export Scratch markdown" })).toHaveValue(
      "Original projection",
    );
  });

  it("saves a Snapshot and shows diffs against previous and original", async () => {
    const user = userEvent.setup();
    const draft = session("ready");
    mocks.customFetch.mockImplementation(async (url: string, init?: { method?: string }) => {
      if (typeof url === "string" && url.includes("/export-scratch/diff?against=previous")) {
        return {
          status: 200,
          data: {
            spec_version_id: "spec-1",
            against: "previous",
            before: "Original projection",
            after: "Snapshot-saved problem statement rewrite",
          },
        };
      }
      if (typeof url === "string" && url.includes("/export-scratch/diff?against=original")) {
        return {
          status: 200,
          data: {
            spec_version_id: "spec-1",
            against: "original",
            before: "Original projection",
            after: "Snapshot-saved problem statement rewrite",
          },
        };
      }
      if (
        typeof url === "string" &&
        url.endsWith("/export-scratch/snapshots") &&
        init?.method === "POST"
      ) {
        return {
          status: 200,
          data: {
            ...draft,
            version: 6,
            export_scratch_snapshots: [
              ...(draft.export_scratch_snapshots ?? []),
              {
                id: "snap-2",
                spec_version_id: "spec-1",
                snapshot_n: 2,
                document: draft.export_scratch!.document,
                created_at: "2026-08-30T01:00:00Z",
              },
            ],
          },
        };
      }
      return { status: 200, data: draft };
    });
    renderView(<ReadinessStageView session={draft} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    await user.click(screen.getByRole("button", { name: "Save Snapshot" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/snapshots",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(screen.queryByRole("list", { name: "Export Scratch Snapshots" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Diff versus previous Snapshot" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("list", { name: "Export Scratch Snapshots" })).toHaveTextContent(
      "Snapshot 2",
    );
    await waitFor(() => {
      expect(
        screen.getByRole("region", { name: "Diff versus previous Snapshot" }),
      ).toHaveTextContent("Snapshot-saved problem statement rewrite");
      expect(
        screen.getByRole("region", { name: "Diff versus Snapshot 1" }),
      ).toHaveTextContent("Snapshot-saved problem statement rewrite");
    });
    expect(
      mocks.customFetch.mock.calls.some(
        (call) => call[0] === "/api/loop/sessions/session-1/export-scratch",
      ),
    ).toBe(false);
    expect(screen.getByRole("button", { name: "Edit Export Scratch" })).toBeInTheDocument();
  });

  it("patches a dirty Export Scratch before saving a Snapshot", async () => {
    const user = userEvent.setup();
    const draft = session("ready");
    mocks.customFetch.mockImplementation(async (url: string, init?: { method?: string }) => {
      if (typeof url === "string" && url.endsWith("/export-scratch") && init?.method === "PATCH") {
        return {
          status: 200,
          data: {
            ...draft,
            version: 5,
            export_scratch: {
              ...draft.export_scratch!,
              document: { markdown: "Edited overlay body" },
            },
          },
        };
      }
      if (
        typeof url === "string" &&
        url.endsWith("/export-scratch/snapshots") &&
        init?.method === "POST"
      ) {
        return {
          status: 200,
          data: {
            ...draft,
            version: 6,
            export_scratch: {
              ...draft.export_scratch!,
              document: { markdown: "Edited overlay body" },
            },
            export_scratch_snapshots: [
              ...(draft.export_scratch_snapshots ?? []),
              {
                id: "snap-2",
                spec_version_id: "spec-1",
                snapshot_n: 2,
                document: { markdown: "Edited overlay body" },
                created_at: "2026-08-30T01:00:00Z",
              },
            ],
          },
        };
      }
      return { status: 200, data: draft };
    });
    renderView(<ReadinessStageView session={draft} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    const source = screen.getByRole("textbox", { name: "Export Scratch markdown" });
    await user.clear(source);
    await user.type(source, "Edited overlay body");
    await user.click(screen.getByRole("button", { name: "Save Snapshot" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch",
        expect.objectContaining({ method: "PATCH" }),
      );
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/snapshots",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const patchIndex = mocks.customFetch.mock.calls.findIndex(
      (call) => call[0] === "/api/loop/sessions/session-1/export-scratch",
    );
    const snapshotIndex = mocks.customFetch.mock.calls.findIndex(
      (call) => call[0] === "/api/loop/sessions/session-1/export-scratch/snapshots",
    );
    expect(snapshotIndex).toBeGreaterThan(patchIndex);
    const snapshotBody = JSON.parse(
      (mocks.customFetch.mock.calls[snapshotIndex]?.[1] as { body: string }).body,
    );
    expect(snapshotBody.expected_version).toBe(5);
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("keeps the Spec Version picker off the Export Scratch editor", async () => {
    const user = userEvent.setup();
    const draft = session("ready");
    renderView(
      <ReadinessStageView
        session={{
          ...draft,
          spec_versions: [
            { id: "spec-0", created_at: "2026-08-29T00:00:00Z", valid: false },
            { id: "spec-1", created_at: "2026-08-30T00:00:00Z", valid: true },
          ],
        }}
        sessionId="session-1"
      />,
    );
    expect(screen.getByRole("combobox", { name: "Spec Version" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    expect(screen.queryByRole("combobox", { name: "Spec Version" })).not.toBeInTheDocument();
    expect(navTest.search.get("export_scratch")).toBe("1");
    expect(navTest.search.get("spec_version")).toBe("spec-1");
  });

  it("stops autosave after a version conflict", async () => {
    const user = userEvent.setup();
    mocks.customFetch.mockResolvedValue({
      status: 409,
      data: { detail: "Loop Session was changed by another request" },
    });
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    await user.click(screen.getByRole("button", { name: "Edit Export Scratch" }));
    const source = screen.getByRole("textbox", { name: "Export Scratch markdown" });
    await user.clear(source);
    await user.type(source, "First conflict body");
    await waitFor(
      () => {
        expect(screen.getByRole("alert")).toHaveTextContent("Export Scratch overlay was not saved");
        expect(screen.getByRole("status", { name: "Export Scratch autosave" })).toHaveTextContent(
          "Error",
        );
      },
      { timeout: EXPORT_SCRATCH_AUTOSAVE_MS + 1500 },
    );
    const patchesAfterConflict = mocks.customFetch.mock.calls.filter(
      (call) => call[0] === "/api/loop/sessions/session-1/export-scratch",
    ).length;
    await user.type(source, " more");
    await new Promise((resolve) => setTimeout(resolve, EXPORT_SCRATCH_AUTOSAVE_MS + 400));
    const patchesAfterMoreTyping = mocks.customFetch.mock.calls.filter(
      (call) => call[0] === "/api/loop/sessions/session-1/export-scratch",
    ).length;
    expect(patchesAfterMoreTyping).toBe(patchesAfterConflict);
  });
});
