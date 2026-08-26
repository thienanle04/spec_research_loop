import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CardKind,
  ContributionDirectionKind,
  WorkflowNode,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";

import { ContributionStageContainer } from "./ContributionStageContainer";

const mocks = vi.hoisted(() => ({
  generate: vi.fn(),
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
  useGenerateContributionDirectionsApiSpecSessionsSessionIdContributionDirectionsGeneratePost: () => ({
    mutateAsync: mocks.generate,
    isPending: false,
  }),
  useReplaceCardsApiLoopSessionsSessionIdCardsPut: () => ({ mutateAsync: mocks.replaceCards }),
}));

const directions = [
  {
    id: "direction-a",
    title: "Focus on the optimization method",
    description: "Improve search and selection.",
    kind: ContributionDirectionKind.proposed,
  },
  {
    id: "direction-b",
    title: "Focus on verification",
    description: "Improve claim checking.",
    kind: ContributionDirectionKind.proposed,
  },
  {
    id: "combine",
    title: "Combine directions",
    description: "Choose primary and supporting contributions.",
    kind: ContributionDirectionKind.combine,
  },
  {
    id: "other",
    title: "Other",
    description: "Write another direction.",
    kind: ContributionDirectionKind.other,
  },
];

function contributionSession(
  overrides: Partial<Pick<LoopSessionResponse, "working_draft_narrative" | "cards">> = {},
): LoopSessionResponse {
  return {
    id: "session-1",
    title: "Contribution test",
    version: 10,
    working_draft_node: WorkflowNode.contribution,
    working_draft_narrative: overrides.working_draft_narrative ?? { directions },
    node_heads: [],
    cards: overrides.cards ?? [],
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-21T00:00:00Z",
    updated_at: "2026-08-21T00:00:00Z",
  };
}

describe("ContributionStageContainer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.replaceCards.mockImplementation(
      async ({ data }: { data: { expected_version: number; bodies: Record<string, unknown>[] } }) => ({
        status: 200,
        data: {
          version: data.expected_version + 1,
          cards: data.bodies.map((body, index) => ({
            id: `card-${index}`,
            kind: "contribution",
            body,
            created_at: "2026-08-21T00:00:00Z",
            updated_at: "2026-08-21T00:00:00Z",
          })),
        },
      }),
    );
    mocks.generate.mockResolvedValue({
      status: 200,
      data: { version: 11, directions },
    });
  });

  it("waits for the Account to generate directions", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const session = contributionSession({ working_draft_narrative: {} });

    render(
      <QueryClientProvider client={queryClient}>
        <ContributionStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    expect(mocks.generate).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Generate contribution directions" }),
    );
    expect(mocks.generate).toHaveBeenCalledWith({
      sessionId: session.id,
      data: { expected_version: 10 },
    });
  });

  it("restores a saved direction without regenerating", () => {
    const queryClient = new QueryClient();
    const session = contributionSession({
      cards: [
        {
          id: "card-saved",
          kind: CardKind.contribution,
          body: {
            text: "Focus on the optimization method. Improve search and selection.",
            direction_id: "direction-a",
            role: "primary",
          },
          created_at: "2026-08-21T00:00:00Z",
          updated_at: "2026-08-21T00:00:00Z",
        },
      ],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ContributionStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/Focus on the optimization method/)).toBeChecked();
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it("saves one primary and supporting Contribution Card for Combine", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const session = contributionSession();
    queryClient.setQueryData(["/api/loop/sessions", session.id], {
      status: 200,
      data: session,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ContributionStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/Other/)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Combine directions/));
    await user.click(
      within(screen.getByRole("group", { name: "Primary contribution" })).getByLabelText(
        "Focus on the optimization method",
      ),
    );
    await user.click(
      within(screen.getByRole("group", { name: "Supporting contributions" })).getByLabelText(
        "Focus on verification",
      ),
    );
    await user.click(screen.getByRole("button", { name: "Save contribution direction" }));

    await waitFor(() => expect(mocks.replaceCards).toHaveBeenCalledTimes(1));
    expect(mocks.replaceCards).toHaveBeenCalledWith({
      sessionId: session.id,
      data: {
        kind: CardKind.contribution,
        expected_version: 10,
        bodies: [
          expect.objectContaining({ role: "primary", direction_id: "direction-a" }),
          expect.objectContaining({ role: "supporting", direction_id: "direction-b" }),
        ],
      },
    });
  });

  it("clears the saved choice after regeneration and replaces it with the new choice", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const session = contributionSession({
      cards: [
        {
          id: "card-saved",
          kind: CardKind.contribution,
          body: {
            text: "Focus on the optimization method. Improve search and selection.",
            direction_id: "direction-a",
            role: "primary",
          },
          created_at: "2026-08-21T00:00:00Z",
          updated_at: "2026-08-21T00:00:00Z",
        },
      ],
    });
    queryClient.setQueryData(["/api/loop/sessions", session.id], {
      status: 200,
      data: session,
    });

    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ContributionStageContainer sessionId={session.id} session={session} />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/Focus on the optimization method/)).toBeChecked();
    await user.click(
      screen.getByRole("button", { name: "Regenerate contribution directions" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Focus on the optimization method/)).not.toBeChecked(),
    );

    await user.click(screen.getByLabelText(/Focus on verification/));
    await user.click(screen.getByRole("button", { name: "Save contribution direction" }));

    await waitFor(() => expect(mocks.replaceCards).toHaveBeenCalledTimes(1));
    expect(mocks.replaceCards).toHaveBeenCalledWith({
      sessionId: session.id,
      data: {
        kind: CardKind.contribution,
        expected_version: 11,
        bodies: [
          expect.objectContaining({ role: "primary", direction_id: "direction-b" }),
        ],
      },
    });

    const cached = queryClient.getQueryData(["/api/loop/sessions", session.id]) as {
      status: number;
      data: LoopSessionResponse;
    };
    const savedContributions = cached.data.cards.filter(
      (card) => card.kind === CardKind.contribution,
    );
    expect(savedContributions).toHaveLength(1);
    expect(savedContributions[0].body.direction_id).toBe("direction-b");

    rerender(
      <QueryClientProvider client={queryClient}>
        <ContributionStageContainer sessionId={session.id} session={cached.data} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByLabelText(/Focus on verification/)).toBeChecked());
    expect(screen.getByLabelText(/Focus on the optimization method/)).not.toBeChecked();
    expect(screen.getByText("Saved 1 Contribution Card. Confirm when ready.")).toBeInTheDocument();
  });
});
