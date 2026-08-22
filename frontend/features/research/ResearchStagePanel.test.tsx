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
  status: "proposed",
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
    expect(screen.queryByText("What has prior research accomplished?")).not.toBeInTheDocument();
    expect(screen.queryByText("Supporting Citations")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regenerate Gap Candidate" }));
    expect(panel.onGenerate).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Save Gap Candidate" }));
    expect(panel.onSelectGap).toHaveBeenCalledWith(gap);
  });
});
