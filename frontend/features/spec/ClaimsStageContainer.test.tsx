import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CardKind,
  WorkflowNode,
  type ClaimEvidenceCard,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";

import { ClaimsStageContainer } from "./ClaimsStageContainer";

const mocks = vi.hoisted(() => ({
  generate: vi.fn(),
  createCard: vi.fn(),
  replaceCards: vi.fn(),
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
  useGenerateClaimsApiSpecSessionsSessionIdClaimsGeneratePost: () => ({
    mutateAsync: mocks.generate,
    isPending: false,
  }),
  useCreateCardApiLoopSessionsSessionIdCardsPost: () => ({
    mutateAsync: mocks.createCard,
  }),
  useReplaceCardsApiLoopSessionsSessionIdCardsPut: () => ({
    mutateAsync: mocks.replaceCards,
  }),
}));

const oldClaim: ClaimEvidenceCard = {
  id: "old-claim",
  claim: "Old stale claim about memory bandwidth",
  baseline: "Prior GPU kernel",
  metric: "GB/s",
  evidence: "Old microbenchmark",
  rejection_condition: "No speedup",
};

const newClaims: ClaimEvidenceCard[] = [
  {
    id: "gen-a",
    claim: "New claim A after regenerate",
    baseline: "New baseline A",
    metric: "latency",
    evidence: "New evidence A",
    rejection_condition: "Reject A",
  },
  {
    id: "gen-b",
    claim: "New claim B after regenerate",
    baseline: "New baseline B",
    metric: "throughput",
    evidence: "New evidence B",
    rejection_condition: "Reject B",
  },
];

function claimSession(
  overrides: Partial<
    Pick<LoopSessionResponse, "working_draft_narrative" | "cards" | "version" | "working_draft_node">
  > = {},
): LoopSessionResponse {
  return {
    id: "session-1",
    title: "Claims test",
    version: 10,
    working_draft_node: WorkflowNode.claims,
    working_draft_narrative: overrides.working_draft_narrative ?? {
      cards: newClaims,
      saved: false,
    },
    node_heads: [],
    cards: overrides.cards ?? [],
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-21T00:00:00Z",
    updated_at: "2026-08-21T00:00:00Z",
    ...overrides,
  };
}

function staleSavedClaimCard() {
  return {
    id: "card-old",
    kind: CardKind.claim,
    body: {
      text: `Claim: ${oldClaim.claim}`,
      metadata: oldClaim,
    },
    created_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
  };
}

function savedClaimTexts(cards: LoopSessionResponse["cards"]): string[] {
  return cards
    .filter((card) => card.kind === CardKind.claim)
    .map((card) => {
      const metadata = card.body.metadata;
      if (metadata && typeof metadata === "object" && "claim" in metadata) {
        return String((metadata as { claim: unknown }).claim);
      }
      const text = card.body.text;
      return typeof text === "string" ? text : "";
    });
}

describe("ClaimsStageContainer", () => {
  it("titles the panel Claims on the claims Workflow Node", () => {
    const queryClient = new QueryClient();
    const session = claimSession();
    render(
      <QueryClientProvider client={queryClient}>
        <ClaimsStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Claims/Evidence")).toBeInTheDocument();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    let nextVersion = 11;
    mocks.createCard.mockImplementation(
      async ({ data }: { data: { expected_version: number; body: Record<string, unknown> } }) => {
        const version = data.expected_version + 1;
        nextVersion = version + 1;
        return {
          status: 201,
          data: {
            id: `created-${data.expected_version}`,
            kind: CardKind.claim,
            body: data.body,
            created_at: "2026-08-21T00:00:00Z",
            updated_at: "2026-08-21T00:00:00Z",
            version,
          },
        };
      },
    );
    mocks.replaceCards.mockImplementation(
      async ({
        data,
      }: {
        data: { expected_version: number; kind: CardKind; bodies: Record<string, unknown>[] };
      }) => ({
        status: 200,
        data: {
          version: data.expected_version + 1,
          cards: data.bodies.map((body, index) => ({
            id: `replaced-${data.kind}-${index}`,
            kind: data.kind,
            body,
            created_at: "2026-08-21T00:00:00Z",
            updated_at: "2026-08-21T00:00:00Z",
          })),
        },
      }),
    );
    mocks.generate.mockResolvedValue({
      status: 200,
      data: { version: 11, cards: newClaims },
    });
  });

  it("does not keep stale Claim Cards when saving after regenerate", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const session = claimSession({
      cards: [
        {
          id: "card-problem",
          kind: CardKind.problem,
          body: { text: "Keep this Card" },
          created_at: "2026-08-20T00:00:00Z",
          updated_at: "2026-08-20T00:00:00Z",
        },
        staleSavedClaimCard(),
      ],
    });
    queryClient.setQueryData(["/api/loop/sessions", session.id], {
      status: 200,
      data: session,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ClaimsStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    expect(screen.getByText("New claim A after regenerate")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Saved 1 Claim(s) in project context");
    await user.click(screen.getByRole("button", { name: "Save Claims" }));

    await waitFor(() => {
      const cached = queryClient.getQueryData(["/api/loop/sessions", session.id]) as {
        status: number;
        data: LoopSessionResponse;
      };
      expect(savedClaimTexts(cached.data.cards)).toEqual([
        "New claim A after regenerate",
        "New claim B after regenerate",
      ]);
    });
    const cached = queryClient.getQueryData(["/api/loop/sessions", session.id]) as {
      status: number;
      data: LoopSessionResponse;
    };
    expect(cached.data.cards.filter((card) => card.kind === CardKind.problem)).toHaveLength(1);
    expect(savedClaimTexts(cached.data.cards)).not.toContain(
      "Old stale claim about memory bandwidth",
    );
    expect(mocks.createCard).not.toHaveBeenCalled();
    expect(mocks.replaceCards).toHaveBeenCalledTimes(2);
    expect(mocks.replaceCards).toHaveBeenNthCalledWith(1, {
      sessionId: session.id,
      data: {
        kind: CardKind.claim,
        expected_version: 10,
        bodies: [
          expect.objectContaining({
            metadata: expect.objectContaining({ claim: "New claim A after regenerate" }),
          }),
          expect.objectContaining({
            metadata: expect.objectContaining({ claim: "New claim B after regenerate" }),
          }),
        ],
      },
    });
    expect(mocks.replaceCards).toHaveBeenNthCalledWith(2, {
      sessionId: session.id,
      data: {
        kind: CardKind.evidence,
        expected_version: 11,
        bodies: [
          expect.objectContaining({ text: "New evidence A" }),
          expect.objectContaining({ text: "New evidence B" }),
        ],
      },
    });
  });

  it("replaces previously saved Claim Cards after regenerate then save", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const session = claimSession({
      working_draft_narrative: { cards: [oldClaim], saved: true },
      cards: [staleSavedClaimCard()],
    });
    queryClient.setQueryData(["/api/loop/sessions", session.id], {
      status: 200,
      data: session,
    });

    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ClaimsStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Regenerate Claims" }));
    await waitFor(() => expect(mocks.generate).toHaveBeenCalledTimes(1));
    const generated = queryClient.getQueryData(["/api/loop/sessions", session.id]) as {
      status: number;
      data: LoopSessionResponse;
    };
    rerender(
      <QueryClientProvider client={queryClient}>
        <ClaimsStageContainer sessionId={session.id} session={generated.data} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("New claim A after regenerate")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save Claims" }));

    await waitFor(() => {
      const cached = queryClient.getQueryData(["/api/loop/sessions", session.id]) as {
        status: number;
        data: LoopSessionResponse;
      };
      expect(savedClaimTexts(cached.data.cards)).toEqual([
        "New claim A after regenerate",
        "New claim B after regenerate",
      ]);
    });
    expect(mocks.createCard).not.toHaveBeenCalled();
    expect(mocks.replaceCards).toHaveBeenCalledTimes(2);
    expect(mocks.replaceCards).toHaveBeenNthCalledWith(1, {
      sessionId: session.id,
      data: {
        kind: CardKind.claim,
        expected_version: 11,
        bodies: [
          expect.objectContaining({
            metadata: expect.objectContaining({ claim: "New claim A after regenerate" }),
          }),
          expect.objectContaining({
            metadata: expect.objectContaining({ claim: "New claim B after regenerate" }),
          }),
        ],
      },
    });
  });
});
