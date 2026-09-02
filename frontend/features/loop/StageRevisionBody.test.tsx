import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkflowNode } from "@/lib/api/generated/model";

import { StageRevisionBody } from "./StageRevisionBody";

describe("StageRevisionBody", () => {
  it("renders Idea Frame and History chrome for interpretation Node Head", () => {
    render(
      <StageRevisionBody
        node={WorkflowNode.idea_interpretation}
        payload={{
          narrative: {
            frame: {
              intent: "You want faster kernels.",
              problem: "GPU launches are slow",
              research_question: "Can we fuse launches?",
            },
            turns: [
              { role: "account", kind: "idea", text: "Speed up GPU kernels" },
              {
                role: "model",
                preamble: "Clarifying the scope.",
                questions: [{ text: "What workload?", options: ["Training", "Inference"] }],
              },
              { role: "account", kind: "answers", answers: [{ option: "Training" }] },
              {
                role: "model",
                preamble: "Skipped cluster.",
                questions: [{ text: "Open question?", options: ["Yes", "No"] }],
              },
            ],
          },
          card_snapshot: [],
        }}
        showLeftovers={false}
        showNodeLabel={false}
      />,
    );

    expect(screen.getByText("Idea Frame")).toBeInTheDocument();
    expect(screen.getByText("You want faster kernels.")).toBeInTheDocument();
    expect(screen.getByText("History")).toBeInTheDocument();
    expect(screen.getByText("Speed up GPU kernels")).toBeInTheDocument();
    expect(screen.getByText("What workload?")).toBeInTheDocument();
    expect(screen.getByText("Training")).toBeInTheDocument();
    expect(screen.queryByText("Open question?")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByText("Confirm freezes")).not.toBeInTheDocument();
  });
});
