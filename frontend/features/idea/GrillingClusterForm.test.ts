import { describe, expect, it } from "vitest";

import { OTHER, answersComplete, unansweredIndices } from "./GrillingClusterForm";

const questions = [
  { text: "Training or inference?", options: ["Training", "Inference"] },
  { text: "Budget?", options: ["Small", "Large"] },
];

describe("unansweredIndices", () => {
  it("lists every blank pick", () => {
    expect(unansweredIndices(questions, ["", ""], ["", ""])).toEqual([0, 1]);
  });

  it("treats Other without text as unanswered", () => {
    expect(unansweredIndices(questions, [OTHER, "Large"], ["  ", ""])).toEqual([0]);
  });

  it("is complete when every pick is an option or Other text", () => {
    expect(answersComplete(questions, ["Training", OTHER], ["", "grant"])).toBe(true);
  });
});
