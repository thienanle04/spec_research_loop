import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { ReadinessStageView } from "./ReadinessStageView";

const mocks = vi.hoisted(() => ({
  customFetch: vi.fn(),
}));

vi.mock("@/lib/api/mutator", () => ({
  customFetch: (...args: unknown[]) => mocks.customFetch(...args),
}));

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
    render(<ReadinessStageView session={session("ready")} sessionId="session-1" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export Spec Artifact" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.customFetch).toHaveBeenCalledWith("/api/loop/sessions/session-1/spec-artifact", {
        method: "POST",
      });
    });
    expect(screen.getByRole("status")).toHaveTextContent("Spec Artifact exported.");
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.queryByText("Blocked")).not.toBeInTheDocument();
  });

  it("asks for Critical Export Confirmation on each blocked Spec Artifact export", async () => {
    const user = userEvent.setup();
    render(<ReadinessStageView session={session("blocked")} sessionId="session-1" />);
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
    expect(screen.getByRole("status")).toHaveTextContent("Spec Artifact exported.");
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
  });
});
