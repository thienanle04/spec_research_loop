import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CardKind, WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { ResearchStageContainer } from "./ResearchStageContainer";

const mocks = vi.hoisted(() => ({
  scheduled: [] as Array<() => Promise<unknown>>,
  patchWorkingDraft: vi.fn(),
  streamStart: vi.fn(),
}));

vi.mock("../loop/loop-session-save", () => ({
  useLoopSessionSave: () => ({
    queue: {
      schedule: (mutation: () => Promise<unknown>) => {
        mocks.scheduled.push(mutation);
        return Promise.resolve(undefined);
      },
      enqueue: (mutation: () => Promise<unknown>) => mutation(),
      flush: () => Promise.resolve(),
    },
    status: "idle",
  }),
}));

vi.mock("./useResearchStream", () => ({
  useResearchStream: () => ({
    running: false,
    progress: 0,
    progressMessage: null,
    warnings: [],
    error: null,
    start: mocks.streamStart,
    abort: vi.fn(),
  }),
}));

vi.mock("@/lib/api/generated/endpoints", () => ({
  getGetSessionApiLoopSessionsSessionIdGetQueryKey: (sessionId: string) => [
    "/api/loop/sessions",
    sessionId,
  ],
  getListCitationsApiResearchSessionsSessionIdCitationsGetQueryKey: (
    sessionId: string,
  ) => ["/api/research/citations", sessionId],
  getListFindingsApiResearchSessionsSessionIdFindingsGetQueryKey: (
    sessionId: string,
  ) => ["/api/research/findings", sessionId],
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch: () => ({
    mutateAsync: mocks.patchWorkingDraft,
  }),
  useListCitationsApiResearchSessionsSessionIdCitationsGet: () => ({
    data: { status: 200, data: [] },
  }),
  useListFindingsApiResearchSessionsSessionIdFindingsGet: () => ({
    data: { status: 200, data: [] },
  }),
  useCreateCardApiLoopSessionsSessionIdCardsPost: () => ({ mutateAsync: vi.fn() }),
  usePatchCardApiLoopSessionsSessionIdCardsCardIdPatch: () => ({ mutateAsync: vi.fn() }),
}));

function session(
  version: number,
  narrative: Record<string, unknown> = {},
  node: WorkflowNode = WorkflowNode.research_inputs,
  cards: LoopSessionResponse["cards"] = [],
): LoopSessionResponse {
  return {
    id: "session-1",
    title: "Autosave test",
    version,
    working_draft_node: node,
    working_draft_narrative: narrative,
    node_heads: [],
    cards,
    produced_spec_version: null,
    valid_spec_version_id: null,
    created_at: "2026-08-19T00:00:00Z",
    updated_at: "2026-08-19T00:00:00Z",
  };
}

describe("ResearchStageContainer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.scheduled.length = 0;
    mocks.patchWorkingDraft.mockImplementation(
      async ({ data }: { data: { expected_version: number; narrative: Record<string, unknown> } }) => ({
        status: 200,
        data: session(data.expected_version + 1, data.narrative),
      }),
    );
  });

  it("reads the latest Loop Session version when each queued autosave starts", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const narrative = {
      keywords: ["claim verification"],
      preferred_sources: {
        peer_reviewed_papers: true,
        official_proceedings: true,
        author_materials: true,
        sourced_surveys: true,
      },
    };
    render(
      <QueryClientProvider client={queryClient}>
        <ResearchStageContainer sessionId="session-1" session={session(1, narrative)} />
      </QueryClientProvider>,
    );
    const peerReviewed = screen.getByLabelText("Peer-reviewed papers");

    fireEvent.click(peerReviewed);
    fireEvent.click(peerReviewed);
    expect(mocks.scheduled).toHaveLength(2);

    await mocks.scheduled[0]();
    await mocks.scheduled[1]();

    expect(mocks.patchWorkingDraft).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ data: expect.objectContaining({ expected_version: 1 }) }),
    );
    expect(mocks.patchWorkingDraft).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ data: expect.objectContaining({ expected_version: 2 }) }),
    );
  });

  it("keeps saved keywords and only regenerates after the Account clicks", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const legacyNarrative = {
      keywords: [
        "paper",
        "source",
        "e85393f1-11bb-43f0-a8f1-81018daaa6ea",
        "llm-generated",
        "summaries",
        "contain",
        "plausible",
        "statements",
      ],
      preferred_sources: {
        peer_reviewed_papers: true,
        official_proceedings: true,
        author_materials: true,
        sourced_surveys: true,
      },
    };

    render(
      <QueryClientProvider client={queryClient}>
        <ResearchStageContainer
          sessionId="session-1"
          session={session(1, legacyNarrative)}
        />
      </QueryClientProvider>,
    );

    expect(mocks.streamStart).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Regenerate keyword suggestions" }),
    );
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: WorkflowNode.research_inputs,
        expectedVersion: 1,
      }),
    );
  });

  it("does not generate a Gap until the Account clicks Generate", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ResearchStageContainer
          sessionId="session-1"
          session={session(4, {}, WorkflowNode.gap)}
        />
      </QueryClientProvider>,
    );

    expect(mocks.streamStart).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Generate Gap Candidate" }));
    expect(mocks.streamStart).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        node: WorkflowNode.gap,
        expectedVersion: 4,
      }),
    );
  });

  it("shows unverified LLM discovery leads after Related Work search", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const relatedNarrative = {
      discovery_leads_status: "unverified_search_leads",
      discovery_leads: {
        tool_discovery_keywords: ["iterative prompt optimization"],
        supporting_context_keywords: ["scientific information extraction"],
        tools_and_frameworks: ["DSPy", "TextGrad"],
        techniques: ["automatic prompt optimization"],
        candidate_work_titles: ["DSPy: Compiling Declarative Language Model Calls"],
        aliases: ["textual gradient optimization"],
      },
      tool_coverage: [
        {
          tool: "DSPy",
          status: "matched_citation",
          citation_key: "dspy-2024",
          article_title: "DSPy framework paper",
        },
        {
          tool: "TextGrad",
          status: "not_found",
          citation_key: null,
          article_title: null,
        },
      ],
    };

    render(
      <QueryClientProvider client={queryClient}>
        <ResearchStageContainer
          sessionId="session-1"
          session={session(1, relatedNarrative, WorkflowNode.related_work)}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByText("LLM discovery leads")).toBeInTheDocument();
    expect(screen.getByText("DSPy · cited")).toHaveAttribute(
      "title",
      "DSPy framework paper",
    );
    expect(screen.getByText("TextGrad · not found")).toBeInTheDocument();
    expect(screen.getByText("Tool-generation keywords:")).toBeInTheDocument();
    expect(screen.getByText("iterative prompt optimization")).toBeInTheDocument();
    expect(screen.getByText("Ranking-context keywords:")).toBeInTheDocument();
    expect(screen.getByText("scientific information extraction")).toBeInTheDocument();
  });

  it("clears the saved Gap and its audit as soon as regeneration starts", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const oldCandidate = {
      statement: "Old Gap Candidate.",
      search_audit: {
        counter_evidence_results: [{ title: "Old counter-evidence article" }],
      },
    };
    const oldSession = session(4, { candidate: oldCandidate }, WorkflowNode.gap, [
      {
        id: "old-gap-card",
        kind: CardKind.gap,
        body: oldCandidate,
        created_at: "2026-08-21T00:00:00Z",
        updated_at: "2026-08-21T00:00:00Z",
      },
    ]);
    const sessionKey = ["/api/loop/sessions", "session-1"];
    queryClient.setQueryData(sessionKey, { status: 200, data: oldSession });

    render(
      <QueryClientProvider client={queryClient}>
        <ResearchStageContainer sessionId="session-1" session={oldSession} />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Regenerate Gap Candidate" }));

    const cached = queryClient.getQueryData(sessionKey) as {
      data: LoopSessionResponse;
    };
    expect(cached.data.working_draft_narrative).toEqual({});
    expect(cached.data.cards).toEqual([]);
  });

  it("clears Related Work articles and comparison rows before searching again", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const citationKey = ["/api/research/citations", "session-1"];
    const findingKey = ["/api/research/findings", "session-1"];
    queryClient.setQueryData(citationKey, {
      status: 200,
      data: [{ id: "old-citation", title: "Old article" }],
    });
    queryClient.setQueryData(findingKey, {
      status: 200,
      data: [{ id: "old-finding", citation_id: "old-citation" }],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ResearchStageContainer
          sessionId="session-1"
          session={session(4, {}, WorkflowNode.related_work)}
        />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Search and analyze" }));

    expect(queryClient.getQueryData(citationKey)).toMatchObject({ data: [] });
    expect(queryClient.getQueryData(findingKey)).toMatchObject({ data: [] });
  });

  it("restores the saved Gap without regenerating on access", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const generated = {
      statement: "Original generated Gap.",
      supporting_citation_keys: ["smith-2025"],
      status: "candidate",
      search_audit: {
        related_work_queries: ["claim verification"],
        counter_evidence_queries: ["claim verification competing methods"],
        providers: ["fixture"],
        related_work_candidate_count: 5,
        related_work_analyzed_count: 5,
        counter_evidence_candidate_count: 5,
        counter_evidence_analyzed_count: 5,
        counter_evidence_outcome: "no_direct_counter_evidence",
        counter_evidence_assessment: "No direct counter-evidence was found.",
        counter_evidence_results: [],
        completed_at: "2026-08-24T00:00:00Z",
        complete: true,
      },
      evidence_check: {
        verified_citation_keys: ["smith-2025"],
        grounded_citation_keys: ["smith-2025"],
        eligible_citation_keys: ["smith-2025"],
        ready: true,
        messages: [],
      },
    };
    const saved = { ...generated, statement: "Edited and saved Gap." };

    render(
      <QueryClientProvider client={queryClient}>
        <ResearchStageContainer
          sessionId="session-1"
          session={session(5, { candidate: generated }, WorkflowNode.gap, [
            {
              id: "gap-card",
              kind: CardKind.gap,
              body: saved,
              created_at: "2026-08-21T00:00:00Z",
              updated_at: "2026-08-21T00:00:00Z",
            },
          ])}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText("Gap Candidate summary")).toHaveValue(
      "Edited and saved Gap.",
    );
    expect(mocks.streamStart).not.toHaveBeenCalled();
  });
});
