import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkflowNode } from "@/lib/api/generated/model";

import { AggregatorReportView } from "./AggregatorReportView";
import type { HandlingOption, JudgeIssue } from "./types";

const issue: JudgeIssue = {
  id: "issue-1",
  finding_kind: "unsupported_citation",
  severity: "CRITICAL",
  reason: "The cited passage does not entail the claim.",
  suggestion: "Cite a passage that entails the claim.",
  target_card_id: "card-1",
  source_node: "evidence_judge",
  cluster: "disagreement",
};

const option: HandlingOption = {
  id: "opt-1",
  finding_kind: "unsupported_citation",
  source_node: "evidence_judge",
  label: "Revise the claim",
  target_node: "claims",
  prose: "Cite a passage that entails the claim.",
};

describe("AggregatorReportView PICK", () => {
  it("picks a listed Handling Option from the working Aggregator Report", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(
      <AggregatorReportView
        issues={[issue]}
        scores={null}
        handlingOptions={[option]}
        canPick
        onPick={onPick}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Pick Revise the claim" }));
    expect(onPick).toHaveBeenCalledWith(option);
  });

  it("picks Other with Account prose and an allowed target Workflow Node", async () => {
    const onPickOther = vi.fn();
    const user = userEvent.setup();
    render(
      <AggregatorReportView
        issues={[issue]}
        scores={null}
        handlingOptions={[option]}
        canPick
        onPickOther={onPickOther}
      />,
    );
    await user.type(
      screen.getByLabelText("Other prose"),
      "Restate the gap against cited sources.",
    );
    await user.selectOptions(screen.getByLabelText("Other target Workflow Node"), WorkflowNode.gap);
    await user.click(screen.getByRole("button", { name: "Pick Other" }));
    expect(onPickOther).toHaveBeenCalledWith(
      "Restate the gap against cited sources.",
      WorkflowNode.gap,
    );
  });

  it("does not offer PICK on a frozen Aggregator Report", () => {
    render(
      <AggregatorReportView issues={[issue]} scores={null} handlingOptions={[option]} />,
    );
    expect(screen.queryByRole("button", { name: /pick/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Other prose")).not.toBeInTheDocument();
  });
});
