import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JudgeIssueList } from "./JudgeIssueList";
import type { JudgeIssue } from "./types";

const issue: JudgeIssue = {
  id: "issue-1",
  finding_kind: "unsupported_citation",
  severity: "CRITICAL",
  reason: "The cited passage does not entail the claim.",
  suggestion: "Cite a passage that entails the claim or revise the claim.",
  target_card_id: "card-1",
  source_node: "evidence_judge",
  cluster: "disagreement",
  grounds: {
    subject: "Brass instruments improve soil nitrogen fixation.",
    excerpts: [
      {
        citation_key: "large-language-models-as-optimizers-2023",
        passage: "",
      },
    ],
  },
};

describe("JudgeIssueList", () => {
  it("shows originating Judge and Judge Issue Grounds", () => {
    render(<JudgeIssueList issues={[issue]} />);
    expect(screen.getByLabelText("Originating Judge")).toHaveTextContent("Evidence Judge");
    expect(screen.getByText("Brass instruments improve soil nitrogen fixation.")).toBeInTheDocument();
    expect(screen.getByText("large-language-models-as-optimizers-2023")).toBeInTheDocument();
    expect(screen.getByText("No supporting passage")).toBeInTheDocument();
  });
});
