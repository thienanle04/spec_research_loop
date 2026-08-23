import { describe, expect, it } from "vitest";

import {
  clustersAnswered,
  isExhaustedHint,
  parseTurns,
  unansweredCluster,
  withEditedTurn,
} from "./turns";

const idea = { role: "account" as const, kind: "idea" as const, text: "GPU kernel latency" };
const cluster = {
  role: "model" as const,
  preamble: "Need the budget.",
  questions: [{ text: "Training or inference?", options: ["Training", "Inference"] }],
};

describe("parseTurns", () => {
  it("returns no turns for blank narrative", () => {
    expect(parseTurns(undefined)).toEqual([]);
    expect(parseTurns({})).toEqual([]);
  });

  it("reads idea, cluster, and answers", () => {
    expect(
      parseTurns({
        turns: [
          idea,
          cluster,
          { role: "account", kind: "answers", answers: [{ option: "Training" }] },
        ],
      }),
    ).toEqual([
      idea,
      cluster,
      { role: "account", kind: "answers", answers: [{ option: "Training" }] },
    ]);
  });
});

describe("clustersAnswered", () => {
  it("is false while the latest cluster has no Account reply", () => {
    expect(clustersAnswered([idea, cluster])).toBe(false);
    expect(unansweredCluster([idea, cluster])).toEqual(cluster.questions);
  });

  it("is true when every visible cluster has a reply", () => {
    expect(
      clustersAnswered([
        idea,
        cluster,
        { role: "account", kind: "answers", answers: [{ option: "Training" }] },
        { role: "model", preamble: "Done.", questions: [] },
      ]),
    ).toBe(true);
  });
});

describe("isExhaustedHint", () => {
  it("is true only for exhausted: true", () => {
    expect(isExhaustedHint({ exhausted: true })).toBe(true);
    expect(isExhaustedHint({ exhausted: false, turns: [] })).toBe(false);
  });
});

describe("withEditedTurn", () => {
  it("truncates later turns after the edited reply", () => {
    const turns = [
      idea,
      cluster,
      { role: "account" as const, kind: "answers" as const, answers: [{ option: "Training" }] },
      { role: "model" as const, preamble: "Next", questions: [] },
    ];
    expect(withEditedTurn(turns, 0, { ...idea, text: "corrected" })).toEqual([
      { ...idea, text: "corrected" },
    ]);
  });
});
