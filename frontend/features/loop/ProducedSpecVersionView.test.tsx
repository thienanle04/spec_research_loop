import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import { CardKind, type SpecVersionResponse, WorkflowNode } from "@/lib/api/generated/model";

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

function renderSpec(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("ProducedSpecVersionView", () => {
  it("shows the empty Produced Spec Version state", () => {
    renderSpec(
      <ProducedSpecVersionView produced={null} validSpecVersionId={null} sessionId="session-1" />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("No Produced Spec Version");
    expect(spec).not.toHaveTextContent("latest spec");
    expect(spec).not.toHaveTextContent("Draft Research Spec");
    expect(spec).not.toHaveTextContent("Final Spec");
  });

  it("renders a Produced Spec Version read-only in Loop Stage order", () => {
    renderSpec(
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
        sessionId="session-1"
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
    expect(spec).toHaveTextContent("Schedule overlapping copies");
    expect(text.indexOf("Grilling")).toBeGreaterThan(-1);
    expect(text.indexOf("Grilling")).toBeLessThan(text.indexOf("Contribution"));
    expect(spec).not.toHaveTextContent("latest spec");
    expect(spec).not.toHaveTextContent("Draft Research Spec");
    expect(spec).not.toHaveTextContent("Final Spec");
    expect(within(spec).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("renders experiment plan without research inputs on Spec Draft", () => {
    renderSpec(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              [WorkflowNode.research_inputs]: {
                stage_revision_id: "rev-inputs",
                narrative: {
                  keywords: ["claim verification"],
                  preferred_sources: {
                    peer_reviewed_papers: true,
                    official_proceedings: false,
                    author_materials: true,
                    sourced_surveys: false,
                  },
                },
                card_snapshot: [],
              },
              [WorkflowNode.experiment_plan]: {
                stage_revision_id: "rev-plan",
                narrative: {
                  plan: {
                    experiments: [
                      {
                        claim: "Latency drops",
                        action: "Run A/B on 20 users",
                        objective: "Measure p95",
                        significance: "Validates contribution",
                      },
                    ],
                  },
                },
                card_snapshot: [],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Latency drops");
    expect(spec).toHaveTextContent("Run A/B on 20 users");
    expect(spec).not.toHaveTextContent("claim verification");
    expect(spec).not.toHaveTextContent("Research inputs");
    expect(spec).not.toHaveTextContent("Peer-reviewed papers");
    expect(spec.textContent).not.toMatch(/"experiments"\s*:/);
  });

  it("renders a legacy Produced Spec Version Gap only once", () => {
    const gap = {
      statement: "Research loops need multi-benchmark verification.",
      status: "candidate",
    };
    renderSpec(
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
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    const occurrences = spec.textContent?.match(/Research loops need multi-benchmark verification\./g);

    expect(occurrences).toHaveLength(1);
    expect(spec.textContent).not.toMatch(/"candidate"\s*:/);
  });

  it("presents Related Work and Gap as concise reader-facing sections", () => {
    renderSpec(
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
        sessionId="session-1"
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
    renderSpec(
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
        sessionId="session-1"
      />,
    );

    expect(screen.getByText("3 sources were analyzed for this Spec Version.")).toBeInTheDocument();
    expect(screen.getByText("The detailed comparison is unavailable in this older Spec Version.")).toBeInTheDocument();
    expect(screen.queryByText("hidden")).not.toBeInTheDocument();
  });

  it("hides raw and generate leftovers on Spec Draft", () => {
    renderSpec(
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
              contribution: {
                narrative: {
                  directions: [{ id: "d1", title: "Hidden direction", description: "x" }],
                  text: "Hidden narrative text",
                },
                card_snapshot: [
                  {
                    id: "card-2",
                    kind: CardKind.contribution,
                    body: { text: "Visible contribution card" },
                  },
                ],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Known idea");
    expect(spec).toHaveTextContent("Bandwidth");
    expect(spec).toHaveTextContent("Visible contribution card");
    expect(within(spec).queryByText("Raw leftovers")).not.toBeInTheDocument();
    expect(within(spec).queryByText("Generate leftovers")).not.toBeInTheDocument();
    expect(spec).not.toHaveTextContent('"schema": "keep-me"');
    expect(spec).not.toHaveTextContent('"extra": 3');
    expect(spec).not.toHaveTextContent('"score": 9');
    expect(spec).not.toHaveTextContent('"assembler": "v2"');
    expect(spec).not.toHaveTextContent("Hidden direction");
    expect(spec).not.toHaveTextContent("Hidden narrative text");
  });

  it("shows problem and research_question for interpretation and hides Intent and the turn list on Spec Draft", () => {
    renderSpec(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              idea_interpretation: {
                narrative: {
                  frame: {
                    intent: "Cut kernel launch latency",
                    problem: "GPU launches are slow",
                    research_question: "Can we fuse launches?",
                  },
                  turns: [
                    { role: "account", kind: "idea", text: "Secret idea text" },
                    {
                      role: "model",
                      preamble: "Hidden preamble",
                      questions: [{ text: "Hidden question?", options: ["A"] }],
                    },
                    { role: "account", kind: "answers", answers: [{ option: "A" }] },
                  ],
                },
                card_snapshot: [],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Idea interpretation");
    expect(spec).not.toHaveTextContent("Cut kernel launch latency");
    expect(spec).toHaveTextContent("GPU launches are slow");
    expect(spec).toHaveTextContent("Can we fuse launches?");
    expect(spec).not.toHaveTextContent("Secret idea text");
    expect(spec).not.toHaveTextContent("Hidden preamble");
    expect(spec).not.toHaveTextContent("Hidden question?");
  });

  it("does not render an Export Scratch editor on Spec Draft", () => {
    renderSpec(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              idea_interpretation: {
                narrative: {
                  frame: {
                    intent: "Cut kernel launch latency",
                    problem: "GPU launches are slow",
                    research_question: "Can we fuse launches?",
                  },
                  turns: [],
                },
                card_snapshot: [],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    expect(spec).toHaveTextContent("Idea interpretation");
    expect(screen.queryByRole("navigation", { name: "Export Scratch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("omits interpretation from Spec Draft when the Idea Frame is blank", () => {
    renderSpec(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              idea_interpretation: {
                narrative: {
                  frame: { intent: "", problem: "", research_question: "" },
                  turns: [{ role: "account", kind: "idea", text: "Only turns" }],
                },
                card_snapshot: [],
              },
              contribution: {
                narrative: {},
                card_snapshot: [
                  {
                    id: "card-1",
                    kind: CardKind.contribution,
                    body: { text: "Visible contribution" },
                  },
                ],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Visible contribution");
    expect(spec).not.toHaveTextContent("Only turns");
    expect(spec).not.toHaveTextContent("Idea interpretation");
    expect(within(spec).queryByRole("region", { name: "Grilling in Produced Spec Version" })).not.toBeInTheDocument();
  });

  it("omits problem and research_question Cards from decomposition on Spec Draft", () => {
    renderSpec(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              idea_decomposition: {
                narrative: {},
                card_snapshot: [
                  {
                    id: "p1",
                    kind: CardKind.problem,
                    body: { text: "Hidden problem card" },
                  },
                  {
                    id: "rq1",
                    kind: CardKind.research_question,
                    body: { text: "Hidden research question card" },
                  },
                  {
                    id: "c1",
                    kind: CardKind.constraint,
                    body: { text: "Must fit in SRAM" },
                  },
                  {
                    id: "o1",
                    kind: CardKind.open_question,
                    body: { text: "Does tiling help?" },
                  },
                ],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Idea decomposition");
    expect(spec).toHaveTextContent("Must fit in SRAM");
    expect(spec).toHaveTextContent("Does tiling help?");
    expect(spec).not.toHaveTextContent("Hidden problem card");
    expect(spec).not.toHaveTextContent("Hidden research question card");
  });

  it("omits decomposition from Spec Draft when only problem and research_question Cards exist", () => {
    renderSpec(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              idea_decomposition: {
                narrative: {},
                card_snapshot: [
                  {
                    id: "p1",
                    kind: CardKind.problem,
                    body: { text: "Hidden problem card" },
                  },
                  {
                    id: "rq1",
                    kind: CardKind.research_question,
                    body: { text: "Hidden research question card" },
                  },
                ],
              },
              contribution: {
                narrative: {},
                card_snapshot: [
                  {
                    id: "card-1",
                    kind: CardKind.contribution,
                    body: { text: "Visible contribution" },
                  },
                ],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Visible contribution");
    expect(spec).not.toHaveTextContent("Idea decomposition");
    expect(spec).not.toHaveTextContent("Hidden problem card");
    expect(within(spec).queryByRole("region", { name: "Grilling in Produced Spec Version" })).not.toBeInTheDocument();
  });

  it("marks a Produced Spec Version Stale when it is not the Valid Spec Version", () => {
    renderSpec(
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
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });

    expect(spec).toHaveTextContent("Stale");
    expect(spec).toHaveTextContent("Produced Spec Version");
    expect(spec).toHaveTextContent("Valid Spec Version");
    expect(spec).toHaveTextContent("Earlier understanding");
  });

  it("prompts to re-mint Related Work when stage_revision_id is missing", () => {
    renderSpec(
      <ProducedSpecVersionView
        produced={produced({
          document: {
            nodes: {
              related_work: {
                narrative: {},
                card_snapshot: [],
              },
            },
          },
        })}
        validSpecVersionId="spec-valid"
        sessionId="session-1"
      />,
    );
    const spec = screen.getByRole("region", { name: "Produced Spec Version" });
    expect(spec).toHaveTextContent("re-minted Spec Version");
  });
});
