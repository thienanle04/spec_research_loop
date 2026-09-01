import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GrillingTurns } from "./GrillingTurns";
import type { GrillingTurn } from "./turns";

const noop = () => undefined;

function renderTurns(
  turns: GrillingTurn[],
  overrides: Partial<Parameters<typeof GrillingTurns>[0]> = {},
) {
  return render(
    <GrillingTurns
      turns={turns}
      generating={false}
      preview=""
      locked={false}
      editingIndex={null}
      draftTurn={null}
      dirty={false}
      onEdit={noop}
      onCancel={noop}
      onSave={noop}
      onDraftChange={noop}
      {...overrides}
    />,
  );
}

describe("GrillingTurns", () => {
  it("pairs each question with its answer and shows preamble separately", () => {
    const turns: GrillingTurn[] = [
      { role: "account", kind: "idea", text: "Speed up GPU kernels" },
      {
        role: "model",
        preamble: "Clarifying the scope.",
        questions: [
          { text: "What workload?", options: ["Training", "Inference"] },
          { text: "Target metric?", options: ["Latency", "Throughput"] },
        ],
      },
      {
        role: "account",
        kind: "answers",
        answers: [{ option: "Training" }, { other: "p95 latency" }],
      },
      {
        role: "model",
        preamble: "",
        questions: [{ text: "Open question?", options: ["Yes"] }],
      },
    ];

    const { container } = renderTurns(turns);

    const history = screen.getByRole("list", { name: "Grilling history" });
    expect(history).toBeInTheDocument();
    expect(screen.getByText("Research idea")).toBeInTheDocument();
    expect(screen.getByText("Speed up GPU kernels")).toBeInTheDocument();
    const ideaText = screen.getByText("Speed up GPU kernels");
    const ideaCard = ideaText.closest("div");
    const ideaEdit = screen.getAllByRole("button", { name: "Edit" })[0];
    expect(ideaCard).toBeTruthy();
    expect(ideaCard?.contains(ideaEdit)).toBe(false);
    expect(ideaEdit.previousElementSibling?.contains(ideaText)).toBe(true);

    expect(screen.getByText("Clarifying the scope.")).toBeInTheDocument();
    expect(screen.getByText("What workload?")).toBeInTheDocument();
    expect(screen.getByText("Target metric?")).toBeInTheDocument();
    expect(screen.getByText("Training")).toBeInTheDocument();
    expect(screen.getByText("Other: p95 latency")).toBeInTheDocument();
    expect(screen.queryByText("Answers")).not.toBeInTheDocument();
    expect(screen.queryByText("Questions")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    // Regression: <legend> sits on the fieldset border and visually leaves the card.
    expect(container.querySelector("legend")).toBeNull();
    expect(screen.getByText(/Open cluster/)).toBeInTheDocument();
    expect(screen.queryByText("Open question?")).not.toBeInTheDocument();

    const text = history.textContent ?? "";
    expect(text.indexOf("Clarifying the scope.")).toBeLessThan(text.indexOf("What workload?"));
    expect(text.indexOf("What workload?")).toBeLessThan(text.indexOf("Training"));
    expect(text.indexOf("Training")).toBeLessThan(text.indexOf("Target metric?"));
    expect(text.indexOf("Target metric?")).toBeLessThan(text.indexOf("Other: p95 latency"));

    const answerCard = screen.getByText("Training").closest("div");
    const editForTraining = screen.getAllByRole("button", { name: "Edit" })[1];
    expect(answerCard).toBeTruthy();
    expect(answerCard?.contains(editForTraining)).toBe(false);
  });

  it("starts per-answer Edit on the answers turn", async () => {
    const onEdit = vi.fn();
    const turns: GrillingTurn[] = [
      {
        role: "model",
        preamble: "",
        questions: [
          { text: "What workload?", options: ["Training", "Inference"] },
          { text: "Target metric?", options: ["Latency"] },
        ],
      },
      {
        role: "account",
        kind: "answers",
        answers: [{ option: "Training" }, { option: "Latency" }],
      },
    ];

    renderTurns(turns, { onEdit });
    const editButtons = screen.getAllByRole("button", { name: "Edit" });
    expect(editButtons).toHaveLength(2);
    await userEvent.click(editButtons[1]);
    expect(onEdit).toHaveBeenCalledWith(1);
  });

  it("edits one answer with radios and Other", async () => {
    const onEdit = vi.fn();
    const onDraftChange = vi.fn();
    const turns: GrillingTurn[] = [
      {
        role: "model",
        preamble: "",
        questions: [{ text: "What workload?", options: ["Training", "Inference"] }],
      },
      {
        role: "account",
        kind: "answers",
        answers: [{ option: "Training" }],
      },
    ];
    const draftTurn: GrillingTurn = {
      role: "account",
      kind: "answers",
      answers: [{ option: "Training" }],
    };

    const { rerender } = renderTurns(turns, { onEdit, onDraftChange });
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledWith(1);

    rerender(
      <GrillingTurns
        turns={turns}
        generating={false}
        preview=""
        locked={false}
        editingIndex={1}
        draftTurn={draftTurn}
        dirty={false}
        onEdit={onEdit}
        onCancel={noop}
        onSave={noop}
        onDraftChange={onDraftChange}
      />,
    );

    expect(screen.getByRole("radio", { name: "Inference" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Inference" }));
    expect(onDraftChange).toHaveBeenCalledWith({
      role: "account",
      kind: "answers",
      answers: [{ option: "Inference" }],
    });
  });

  it("renders Account notes under their own label", () => {
    renderTurns([{ role: "account", kind: "note", text: "Skip for now" }]);
    const history = screen.getByRole("list", { name: "Grilling history" });
    expect(within(history).getByText("Account note")).toBeInTheDocument();
    expect(within(history).getByText("Skip for now")).toBeInTheDocument();
  });
});
