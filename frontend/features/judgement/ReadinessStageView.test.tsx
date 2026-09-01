import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { ReadinessStageView } from "./ReadinessStageView";

const mocks = vi.hoisted(() => ({
  customFetch: vi.fn(),
}));

vi.mock("@/lib/api/mutator", () => ({
  customFetch: (...args: unknown[]) => mocks.customFetch(...args),
}));

function renderView(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
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
        sections: [
          { id: "problem_statement", title: "Problem Statement", body: "" },
          { id: "research_question", title: "Research Question", body: "" },
          { id: "related_work", title: "Related Work", body: "" },
          { id: "research_gap", title: "Research Gap", body: "" },
          { id: "contribution", title: "Proposed Approach & Contribution", body: "" },
          { id: "claims", title: "Claims", body: "" },
          { id: "evidence", title: "Evidence", body: "" },
          { id: "experiment_plan", title: "Experiment Plan", body: "" },
          { id: "constraints", title: "Constraints", body: "" },
          { id: "required_resources", title: "Required Resources", body: "" },
          { id: "potential_bottlenecks", title: "Potential Bottlenecks", body: "" },
          { id: "mitigation_strategies", title: "Mitigation Strategies", body: "" },
          { id: "open_issues", title: "Open Issues", body: "" },
        ],
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
          sections: [
            { id: "problem_statement", title: "Problem Statement", body: "Original projection" },
            { id: "research_question", title: "Research Question", body: "" },
            { id: "related_work", title: "Related Work", body: "" },
            { id: "research_gap", title: "Research Gap", body: "" },
            { id: "contribution", title: "Proposed Approach & Contribution", body: "" },
            { id: "claims", title: "Claims", body: "" },
            { id: "evidence", title: "Evidence", body: "" },
            { id: "experiment_plan", title: "Experiment Plan", body: "" },
            { id: "constraints", title: "Constraints", body: "" },
            { id: "required_resources", title: "Required Resources", body: "" },
            { id: "potential_bottlenecks", title: "Potential Bottlenecks", body: "" },
            { id: "mitigation_strategies", title: "Mitigation Strategies", body: "" },
            { id: "open_issues", title: "Open Issues", body: "" },
          ],
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
    mocks.customFetch.mockResolvedValue({
      status: 200,
      data: "## 1. Problem Statement\n",
      headers: {
        get: (name: string) =>
          name === "content-disposition"
            ? 'attachment; filename="export-scratch-spec-1.md"'
            : null,
      },
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
    await user.click(screen.getByRole("button", { name: "Export Spec" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/markdown?spec_version_id=spec-1",
        {
          method: "POST",
        },
      );
    });
    expect(mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("spec-artifact"))).toBe(
      false,
    );
    expect(screen.getByRole("status", { name: "Export Spec" })).toHaveTextContent(
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
    await user.click(screen.getByRole("button", { name: "Export Spec" }));
    expect(mocks.customFetch).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Critical Export Confirmation" });
    expect(dialog).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm export" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/markdown?spec_version_id=spec-1",
        {
          method: "POST",
          body: JSON.stringify({ critical_export_ack: true }),
        },
      );
    });
    expect(mocks.customFetch.mock.calls.some((call) => String(call[0]).includes("spec-artifact"))).toBe(
      false,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Export Spec" })).toHaveTextContent(
      "Export Scratch markdown downloaded.",
    );
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
  });

  it("renders a table of contents of the thirteen Export Scratch titles", () => {
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    const toc = screen.getByRole("navigation", { name: "Export Scratch" });
    const titles = [
      "Problem Statement",
      "Research Question",
      "Related Work",
      "Research Gap",
      "Proposed Approach & Contribution",
      "Claims",
      "Evidence",
      "Experiment Plan",
      "Constraints",
      "Required Resources",
      "Potential Bottlenecks",
      "Mitigation Strategies",
      "Open Issues",
    ];
    const items = toc.querySelectorAll("li");
    expect([...items].map((item) => item.textContent)).toEqual(titles);
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm export" })).not.toBeInTheDocument();
  });

  it("shows a persistent Export Scratch banner and saves overlay edits", async () => {
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
            sections: draft.export_scratch!.document.sections.map((section) =>
              section.id === "problem_statement"
                ? { ...section, body: "Edited overlay body" }
                : section,
            ),
          },
        },
      },
    });
    renderView(<ReadinessStageView session={draft} sessionId="session-1" />);
    expect(
      screen.getByRole("status", { name: "Export Scratch overlay" }),
    ).toHaveTextContent(/Export Scratch, not the Research Spec/);
    expect(screen.getByText(/reopen a Workflow Node/)).toBeInTheDocument();
    const problem = screen.getByRole("textbox", { name: "Problem Statement" });
    await user.clear(problem);
    await user.type(problem, "Edited overlay body");
    await user.click(screen.getByRole("button", { name: "Save Export Scratch" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
    const body = JSON.parse(
      (mocks.customFetch.mock.calls.find(
        (call) =>
          call[0] === "/api/loop/sessions/session-1/export-scratch",
      )?.[1] as { body: string }).body,
    );
    expect(body.expected_version).toBe(4);
    expect(body.document.sections[0].body).toBe("Edited overlay body");
    expect(screen.getByRole("textbox", { name: "Problem Statement" })).toHaveValue(
      "Edited overlay body",
    );
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
          sections: draft.export_scratch!.document.sections.map((section) =>
            section.id === "research_gap"
              ? { ...section, body: "Older gap body" }
              : section,
          ),
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
    expect(screen.getByRole("textbox", { name: "Research Gap" })).toHaveValue("Older gap body");
  });

  it("shows derived Clarification Review for the selected Spec Version", () => {
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    const panel = screen.getByRole("region", { name: "Clarification Review" });
    expect(panel).toHaveTextContent("GPU kernel latency");
    expect(panel).toHaveTextContent("The literature has not measured tiling DRAM traffic.");
    expect(panel).toHaveTextContent("A tiling schedule that cuts DRAM traffic");
    expect(panel).toHaveTextContent("Tiling cuts DRAM traffic by at least 20%");
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
          sections: draft.export_scratch!.document.sections.map((section) =>
            section.id === "problem_statement"
              ? { ...section, body: "Original projection" }
              : section,
          ),
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
    expect(screen.getByRole("textbox", { name: "Problem Statement" })).toHaveValue(
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
            sections: [
              {
                id: "problem_statement",
                title: "Problem Statement",
                before: "Original projection",
                after: "Snapshot-saved problem statement rewrite",
              },
            ],
          },
        };
      }
      if (typeof url === "string" && url.includes("/export-scratch/diff?against=original")) {
        return {
          status: 200,
          data: {
            spec_version_id: "spec-1",
            against: "original",
            sections: [
              {
                id: "problem_statement",
                title: "Problem Statement",
                before: "Original projection",
                after: "Snapshot-saved problem statement rewrite",
              },
            ],
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
    await user.click(screen.getByRole("button", { name: "Save Snapshot" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith(
        "/api/loop/sessions/session-1/export-scratch/snapshots",
        expect.objectContaining({ method: "POST" }),
      );
    });
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
  });
});
