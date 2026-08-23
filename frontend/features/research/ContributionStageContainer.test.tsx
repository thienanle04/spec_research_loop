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
  createCard: vi.fn(),
  generate: vi.fn(),
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
  useCreateCardApiLoopSessionsSessionIdCardsPost: () => ({ mutateAsync: mocks.createCard }),
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
    mocks.createCard.mockImplementation(
      async ({ data }: { data: { expected_version: number; body: Record<string, unknown> } }) => ({
        status: 201,
        data: {
          id: `card-${data.expected_version}`,
          kind: "contribution",
          body: data.body,
          version: data.expected_version + 1,
          created_at: "2026-08-21T00:00:00Z",
          updated_at: "2026-08-21T00:00:00Z",
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

    await waitFor(() => expect(mocks.createCard).toHaveBeenCalledTimes(2));
    expect(mocks.createCard).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        data: expect.objectContaining({
          expected_version: 10,
          body: expect.objectContaining({ role: "primary" }),
        }),
      }),
    );
    expect(mocks.createCard).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        data: expect.objectContaining({
          expected_version: 11,
          body: expect.objectContaining({ role: "supporting" }),
        }),
      }),
    );
  });
});
