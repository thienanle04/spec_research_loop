import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { EvidenceStageContainer } from "./EvidenceStageContainer";

vi.mock("../loop/loop-session-save", () => ({
  useLoopSessionSave: () => ({
    queue: { enqueue: (mutation: () => Promise<unknown>) => mutation() },
    status: "idle",
  }),
}));

vi.mock("@/lib/api/generated/endpoints", () => ({
  getGetSessionApiLoopSessionsSessionIdGetQueryKey: (sessionId: string) => [
    "/api/loop/sessions",
    sessionId,
  ],
  usePatchCardApiLoopSessionsSessionIdCardsCardIdPatch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

describe("EvidenceStageContainer", () => {
  it("titles the panel Evidence on the evidence Workflow Node", () => {
    const session: LoopSessionResponse = {
      id: "session-1",
      title: "Evidence test",
      version: 10,
      working_draft_node: WorkflowNode.evidence,
      working_draft_narrative: {},
      node_heads: [],
      cards: [],
      produced_spec_version: null,
      valid_spec_version_id: null,
      created_at: "2026-08-21T00:00:00Z",
      updated_at: "2026-08-21T00:00:00Z",
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <EvidenceStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.queryByText("Claims & Evidence")).not.toBeInTheDocument();
  });
});
