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
