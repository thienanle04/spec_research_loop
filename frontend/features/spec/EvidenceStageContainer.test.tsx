import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CardKind,
  WorkflowNode,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";

import { EvidenceStageContainer } from "./EvidenceStageContainer";

const mocks = vi.hoisted(() => ({
  patchWorkingDraft: vi.fn(),
  patchCard: vi.fn(),
}));

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
    mutateAsync: mocks.patchCard,
    isPending: false,
  }),
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch: () => ({
    mutateAsync: mocks.patchWorkingDraft,
    isPending: false,
  }),
}));

function evidenceSession(): LoopSessionResponse {
  return {
    id: "session-1",
    title: "Evidence test",
    version: 10,
    working_draft_node: WorkflowNode.evidence,
    working_draft_narrative: {},
    node_heads: [],
    cards: [
      {
        id: "claim-1",
        kind: CardKind.claim,
        body: {
          text: "Claim: Tiling cuts DRAM traffic",
          metadata: {
            claim: "Tiling cuts DRAM traffic",
            baseline: "Untiled kernel",
            metric: "GB/s",
            evidence: "Roofline microbenchmark",
            rejection_condition: "No bandwidth drop",
          },
        },
        created_at: "2026-08-21T00:00:00Z",
        updated_at: "2026-08-21T00:00:00Z",
      },
    ],
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-21T00:00:00Z",
    updated_at: "2026-08-21T00:00:00Z",
  };
}

describe("EvidenceStageContainer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

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

  it("Mark as Verified patches narrative without moving Working Draft", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const session = evidenceSession();
    queryClient.setQueryData(["/api/loop/sessions", session.id], {
      status: 200,
      data: session,
    });
    mocks.patchWorkingDraft.mockResolvedValue({
      status: 200,
      data: {
        ...session,
        version: 11,
        working_draft_narrative: { evidence_saved: true },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <EvidenceStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Mark as Verified" }));

    await waitFor(() => expect(mocks.patchWorkingDraft).toHaveBeenCalledTimes(1));
    expect(mocks.patchWorkingDraft).toHaveBeenCalledWith({
      sessionId: session.id,
      data: {
        expected_version: 10,
        narrative: { evidence_saved: true },
      },
    });
    expect(mocks.patchWorkingDraft.mock.calls[0][0].data).not.toHaveProperty("node");
  });
});
