import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GroundingStatus, VerificationStatus, WorkflowNode, type CitationResponse, type RelatedWorkFindingResponse } from "@/lib/api/generated/model";

import { ResearchStagePanel } from "./ResearchStagePanel";
import { emptyResearchInputs, type GapCandidate } from "./types";

const citation: CitationResponse = {
  id: "citation-1",
  session_id: "session-1",
  stage_revision_id: null,
  citation_key: "smith-2025",
  title: "Verified research loops",
  authors: ["Smith"],
  year: 2025,
  doi: "10.1000/research",
  verification_status: VerificationStatus.verified,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const finding: RelatedWorkFindingResponse = {
  id: "finding-1",
  session_id: "session-1",
  stage_revision_id: null,
  citation_id: citation.id,
  what_was_done: "Evaluated a research loop.",
  method_or_feedback: "Textual feedback",
  limitation: "Used one benchmark.",
  supporting_passage: "The evaluation used one benchmark.",
  grounding_status: GroundingStatus.grounded,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const gap: GapCandidate = {
  statement: "Research loops need multi-benchmark verification.",
  supporting_citation_keys: [citation.citation_key],
  status: "candidate",
  search_audit: {
    assessed_statement: "Research loops need multi-benchmark verification.",
    related_work_queries: ["research loop verification"],
    counter_evidence_queries: ["research loop competing methods"],
    providers: ["fixture"],
    related_work_candidate_count: 8,
    related_work_analyzed_count: 5,
    counter_evidence_candidate_count: 7,
    counter_evidence_analyzed_count: 5,
    counter_evidence_outcome: "no_direct_counter_evidence",
    counter_evidence_assessment: "The checked sources do not directly resolve the limitation.",
    counter_evidence_results: [
      {
        result_key: "counter-1",
        title: "A competing research loop benchmark",
        authors: ["Lee"],
        year: 2024,
        venue: "FixtureConf",
        doi: "10.1000/counter",
        url: null,
        provider: "fixture",
        provider_source_id: "counter-1",
        abstract: "Compares research loops on one benchmark.",
        retrieval_score: 0.8,
        reranker_score: 0.9,
        discovery_queries: ["research loop competing methods"],
        verification_status: "verified",
        verification_messages: ["Identifier and title match the scholarly provider"],
        content_basis: "abstract",
        evidence_passage: "Compares research loops on one benchmark.",
        evidence_location: "Abstract",
        grounding_status: "grounded",
        relevance_status: "relevant",
        support_status: "supported",
        impact: "no_direct_counter_evidence",
        rationale: "The study does not evaluate multi-benchmark verification.",
      },
    ],
    claim_assessments: [
      {
        claim_id: "c1",
        kind: "unresolved_limitation",
        statement: "Research loops need multi-benchmark verification.",
        supporting_citation_keys: [citation.citation_key],
        supporting_evidence: [
          {
            citation_key: citation.citation_key,
            passage: "The evaluation used one benchmark.",
            location: "Abstract",
          },
        ],
        counter_evidence_result_keys: ["counter-1"],
        outcome: "no_direct_counter_evidence",
        assessment: "The checked source does not evaluate multiple benchmarks.",
      },
    ],
    readiness_messages: [],
    completed_at: "2026-08-24T00:00:00Z",
    complete: true,
  },
  evidence_check: {
    verified_citation_keys: [citation.citation_key],
    grounded_citation_keys: [citation.citation_key],
    eligible_citation_keys: [citation.citation_key],
    ready: true,
    messages: [],
  },
};

function props(node: WorkflowNode) {
  return {
    node,
    inputs: emptyResearchInputs(),
    citations: [citation],
    findings: [finding],
    gapCandidate: gap,
    selectedGap: null,
    running: false,
    progress: 0,
    progressMessage: null,
    warnings: [],
    error: null,
    saveError: null,
    onInputsChange: vi.fn(),
    onGenerate: vi.fn(),
    onAbort: vi.fn(),
    onSelectGap: vi.fn(),
  };
}

describe("ResearchStagePanel", () => {
  it("renders and edits structured Research Inputs", async () => {
    const user = userEvent.setup();
    const panel = props(WorkflowNode.research_inputs);
    render(<ResearchStagePanel {...panel} />);

    await user.type(screen.getByPlaceholderText("Add a keyword or search concept"), "verification");
    await user.click(screen.getByRole("button", { name: "Add keyword" }));

    expect(panel.onInputsChange).toHaveBeenCalledWith(
      expect.objectContaining({ keywords: ["verification"] }),
    );
    expect(screen.queryByLabelText("Research goal")).not.toBeInTheDocument();
    expect(screen.queryByText("Seed DOI or URL (one per line)")).not.toBeInTheDocument();
    expect(screen.queryByText("Earliest publication year")).not.toBeInTheDocument();
    expect(screen.queryByText("Search Plan")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate keyword suggestions" }));
    expect(panel.onGenerate).toHaveBeenCalledTimes(1);
  });

  it("lets the Account select preferred sources", async () => {
    const user = userEvent.setup();
    const panel = props(WorkflowNode.research_inputs);
    function StatefulPanel() {
      const [inputs, setInputs] = useState(emptyResearchInputs);
      return (
        <ResearchStagePanel
          {...panel}
          inputs={inputs}
          onInputsChange={(next) => {
            panel.onInputsChange(next);
            setInputs(next);
          }}
        />
      );
    }
    render(<StatefulPanel />);

    await user.click(screen.getByLabelText("Peer-reviewed papers"));

    expect(panel.onInputsChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        preferred_sources: expect.objectContaining({ peer_reviewed_papers: false }),
      }),
    );
  });

  it("renders partial search state and source-linked related-work findings", () => {
    render(
      <ResearchStagePanel
        {...props(WorkflowNode.related_work)}
        running
        progress={55}
        progressMessage="Analyzed Citation 1 of 2"
      />,
    );

    expect(screen.getByText("Analyzed Citation 1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Study" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "What was done?" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Method or feedback" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Remaining limitation" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Source" })).toBeInTheDocument();
    expect(screen.getByText("Evaluated a research loop.")).toBeInTheDocument();
    expect(screen.getByText("Textual feedback")).toBeInTheDocument();
    expect(screen.getByText("Used one benchmark.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `Open source: ${citation.title}` })).toHaveAttribute(
      "href",
      "https://doi.org/10.1000/research",
    );
    expect(screen.queryByRole("columnheader", { name: "Relevance" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Evidence · Source excerpt")).toHaveLength(3);
  });

  it("supports editing and saving the single Gap Candidate", async () => {
    const user = userEvent.setup();
    const panel = props(WorkflowNode.gap);
    render(<ResearchStagePanel {...panel} />);

    expect(screen.getByLabelText("Gap Candidate summary")).toHaveValue(gap.statement);
    expect(screen.getByText("Counter-evidence assessment")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "A competing research loop benchmark" })).toHaveAttribute(
      "href",
      "https://doi.org/10.1000/counter",
    );
    expect(screen.getByText("The study does not evaluate multi-benchmark verification.")).toBeInTheDocument();
    expect(screen.getByText(/Support: supported/)).toBeInTheDocument();
    expect(screen.getByText(/The evaluation used one benchmark/)).toBeInTheDocument();
    expect(screen.queryByText("What has prior research accomplished?")).not.toBeInTheDocument();
    expect(screen.queryByText("Supporting Citations")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regenerate Gap Candidate" }));
    expect(panel.onGenerate).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Save Gap Candidate" }));
    expect(panel.onSelectGap).toHaveBeenCalledWith(gap);
  });

  it("warns but allows saving when the Gap search audit is inconclusive", async () => {
    const user = userEvent.setup();
    const panel = props(WorkflowNode.gap);
    const insufficient: GapCandidate = {
      ...gap,
      status: "insufficient_evidence",
      search_audit: {
        ...gap.search_audit,
        counter_evidence_outcome: "inconclusive",
        counter_evidence_analyzed_count: 0,
        counter_evidence_results: [],
        claim_assessments: gap.search_audit.claim_assessments.map((claim) => ({
          ...claim,
          counter_evidence_result_keys: [],
          outcome: "inconclusive",
        })),
      },
    };

    render(
      <ResearchStagePanel
        {...panel}
        gapCandidate={insufficient}
        warnings={[
          "Split 2 composite Related Work limitation(s) into atomic claim candidates.",
          "Atomic Gap claim support used structured-output recovery: schema validation failed.",
          "Backfilled 5 counter-evidence source(s).",
        ]}
      />,
    );

    expect(screen.getByText("Potential Gap — further validation needed")).toBeInTheDocument();
    expect(screen.getByText(/Treat this as a potential Gap/)).toBeInTheDocument();
    expect(screen.queryByText(/structured-output recovery/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Backfilled 5/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", {
        name: "Source-grounded limitations awaiting counter-evidence audit",
      }),
    ).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save Gap Candidate" });
    expect(save).toBeEnabled();
    await user.click(save);
    expect(panel.onSelectGap).toHaveBeenCalledWith(insufficient);
  });

  it("marks the literature audit stale after editing the Gap statement", async () => {
    const user = userEvent.setup();
    render(<ResearchStagePanel {...props(WorkflowNode.gap)} />);

    const summary = screen.getByLabelText("Gap Candidate summary");
    await user.clear(summary);
    await user.type(summary, "A materially edited Gap statement.");

    expect(screen.getByText("Evidence needs review")).toBeInTheDocument();
    expect(
      screen.getByText(/This summary was edited after the literature review/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Gap Candidate" })).toBeEnabled();
  });
});
