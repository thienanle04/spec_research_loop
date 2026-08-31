import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardKind, type SpecVersionResponse } from "@/lib/api/generated/model";

import { ProducedSpecVersionView } from "./ProducedSpecVersionView";

function produced(
  overrides: Partial<SpecVersionResponse> & { document?: Record<string, unknown> } = {},
): SpecVersionResponse {
  return {
    id: "spec-valid",
    created_at: "2026-08-16T12:00:00Z",
    document: {},
    ...overrides,
  };
}

describe("ProducedSpecVersionView", () => {
  it("shows the empty Produced Spec Version state", () => {
    render(<ProducedSpecVersionView produced={null} validSpecVersionId={null} />);
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("No Produced Spec Version");
    expect(spec).not.toHaveTextContent("latest spec");
    expect(spec).not.toHaveTextContent("Draft Research Spec");
    expect(spec).not.toHaveTextContent("Final Spec");
  });

  it("renders a Produced Spec Version read-only in Loop Stage order", () => {
    render(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              contribution: {
                narrative: { text: "A fused kernel scheduler" },
                card_snapshot: [
                  {
                    id: "card-1",
                    kind: CardKind.contribution,
                    body: { text: "Schedule overlapping copies" },
                  },
                ],
              },
              idea_interpretation: {
                narrative: { text: "Latency in GPU kernels" },
                card_snapshot: [],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    const text = spec.textContent ?? "";

    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("Valid Spec Version");
    expect(spec).not.toHaveTextContent("Stale");
    expect(spec).toHaveTextContent("Grilling");
    expect(spec).toHaveTextContent("Latency in GPU kernels");
    expect(spec).toHaveTextContent("Contribution");
    expect(spec).toHaveTextContent("A fused kernel scheduler");
    expect(spec).toHaveTextContent("Schedule overlapping copies");
    expect(text.indexOf("Grilling")).toBeGreaterThan(-1);
    expect(text.indexOf("Grilling")).toBeLessThan(text.indexOf("Contribution"));
    expect(spec).not.toHaveTextContent("latest spec");
    expect(spec).not.toHaveTextContent("Draft Research Spec");
    expect(spec).not.toHaveTextContent("Final Spec");
    expect(within(spec).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("renders a legacy Produced Spec Version Gap only once", () => {
    const gap = {
      statement: "Research loops need multi-benchmark verification.",
      status: "candidate",
    };
    render(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              gap: {
                narrative: { candidate: gap },
                card_snapshot: [
                  {
                    id: "gap-card",
                    kind: CardKind.gap,
                    body: gap,
                  },
                ],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    const occurrences = spec.textContent?.match(/Research loops need multi-benchmark verification\./g);

    expect(occurrences).toHaveLength(1);
    expect(spec.textContent).not.toMatch(/"candidate"\s*:/);
  });

  it("presents Related Work and Gap as concise reader-facing sections", () => {
    render(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              related_work: {
                narrative: {
                  search_queries: ["internal query"],
                  analyzed_result_count: 1,
                  selection_rule: "internal_ranking_rule",
                },
                card_snapshot: [],
                projection: {
                  citations: [
                    {
                      id: "citation-1",
                      citation_key: "smith2025",
                      title: "Grounded Research Loops",
                      year: 2025,
                      url: "https://example.com/study",
                      verification_status: "verified",
                    },
                  ],
                  related_work: [
                    {
                      id: "finding-1",
                      citation_id: "citation-1",
                      what_was_done: "Built a source-grounded research workflow.",
                      method_or_feedback: "Human confirmation after each stage.",
                      limitation: "Did not audit counter-evidence.",
                      evidence: {
                        limitation: {
                          passage: "The workflow did not include counter-evidence search.",
                          location: "Discussion",
                        },
                      },
                    },
                  ],
                },
              },
              gap: {
                narrative: {},
                card_snapshot: [
                  {
                    id: "gap-card",
                    kind: CardKind.gap,
                    body: {
                      statement: "Research workflows need a verified counter-evidence audit.",
                      supporting_citation_keys: ["smith2025"],
                      status: "candidate",
                      evidence_check: { ready: true },
                      search_audit: {
                        complete: true,
                        related_work_analyzed_count: 1,
                        counter_evidence_analyzed_count: 1,
                        counter_evidence_assessment: "No direct counter-evidence was found.",
                        claim_assessments: [
                          {
                            claim_id: "claim-1",
                            statement: "Counter-evidence is not audited.",
                            outcome: "no_direct_counter_evidence",
                            assessment: "The limitation remains unresolved.",
                            supporting_evidence: [],
                          },
                        ],
                        counter_evidence_results: [
                          {
                            result_key: "hidden-result-key",
                            title: "A Neighboring Workflow",
                            year: 2024,
                            impact: "no_direct_counter_evidence",
                            rationale: "It does not cover counter-evidence auditing.",
                            verification_status: "verified",
                          },
                        ],
                      },
                    },
                  },
                ],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("1 source-grounded study compared");
    expect(spec).toHaveTextContent("Grounded Research Loops");
    expect(spec).toHaveTextContent("What was done");
    expect(spec).toHaveTextContent("Remaining limitation");
    expect(spec).toHaveTextContent("Evidence-ready Gap");
    expect(spec).toHaveTextContent("Research workflows need a verified counter-evidence audit");
    expect(spec).toHaveTextContent("Counter-evidence assessment");
    expect(spec).toHaveTextContent("Gap claims");
    expect(spec).toHaveTextContent("Counter-evidence sources");
    expect(spec).not.toHaveTextContent("internal query");
    expect(spec).not.toHaveTextContent("internal_ranking_rule");
    expect(spec).not.toHaveTextContent("hidden-result-key");
    expect(spec).not.toHaveTextContent("verification_status");
  });

  it("explains when an older Spec Version has only a Related Work summary", () => {
    render(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              related_work: {
                narrative: { analyzed_result_count: 3, search_queries: ["hidden"] },
                card_snapshot: [],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
      />,
    );

    expect(screen.getByText("3 sources were analyzed for this Spec Version.")).toBeInTheDocument();
    expect(screen.getByText("The detailed comparison is unavailable in this older Spec Version.")).toBeInTheDocument();
    expect(screen.queryByText("hidden")).not.toBeInTheDocument();
  });

  it("keeps unknown Produced Spec Version fields visible as JSON", () => {
    render(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            assembler: "v2",
            nodes: {
              idea_interpretation: {
                narrative: { text: "Known idea", schema: "keep-me" },
                card_snapshot: [
                  {
                    id: "card-1",
                    kind: CardKind.problem,
                    body: { text: "Bandwidth", extra: 3 },
                  },
                ],
                future_field: { score: 9 },
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Known idea");
    expect(spec).toHaveTextContent("Bandwidth");
    expect(spec).toHaveTextContent('"schema": "keep-me"');
    expect(spec).toHaveTextContent('"extra": 3');
    expect(spec).toHaveTextContent('"score": 9');
    expect(spec).toHaveTextContent('"assembler": "v2"');
  });

  it("marks a Produced Spec Version Stale when it is not the Valid Spec Version", () => {
    render(
      <ProducedSpecVersionView
        produced={produced({
          id: "spec-old",
          document: {
            nodes: {
              idea_interpretation: {
                narrative: { text: "Earlier understanding" },
                card_snapshot: [],
              },
            },
          },
        })}
        validSpecVersionId={null}
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Stale");
    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("Valid Spec Version");
    expect(spec).toHaveTextContent("Earlier understanding");
  });
});
