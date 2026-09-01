import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
    export_scratch_snapshots: [],
    created_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
  };
}

describe("ReadinessStageView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.customFetch.mockResolvedValue({ status: 200, data: { spec_version_id: "spec-1" } });
  });

  it("exports Spec Artifact with one click when Readiness is ready", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export Spec Artifact" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith("/api/loop/sessions/session-1/spec-artifact", {
        method: "POST",
      });
    });
    expect(screen.getByRole("status", { name: "Spec Artifact export" })).toHaveTextContent(
      "Spec Artifact exported.",
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.queryByText("Blocked")).not.toBeInTheDocument();
  });

  it("asks for Critical Export Confirmation on each blocked Spec Artifact export", async () => {
    const user = userEvent.setup();
    renderView(<ReadinessStageView session={session("blocked")} sessionId="session-1" />);
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export Spec Artifact" }));
    expect(mocks.customFetch).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Critical Export Confirmation" });
    expect(dialog).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm export" }));
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith("/api/loop/sessions/session-1/spec-artifact", {
        method: "POST",
        body: JSON.stringify({ critical_export_ack: true }),
      });
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Spec Artifact export" })).toHaveTextContent(
      "Spec Artifact exported.",
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
});
