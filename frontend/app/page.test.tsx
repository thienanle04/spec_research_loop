import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "./page";

vi.mock("@/features/identity", () => ({
  useAccount: () => ({ signedIn: false }),
}));

describe("HomePage", () => {
  it("sends the product CTA to Loop Sessions and lists all Loop Stages", () => {
    render(<HomePage />);

    expect(screen.getByRole("link", { name: "Start a Loop Session" })).toHaveAttribute(
      "href",
      "/sessions",
    );
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent),
    ).toEqual([
      "Grilling",
      "Related work",
      "Gap",
      "Contribution",
      "Claims/evidence",
      "Experiment planning",
      "Spec Draft",
      "Independent judges",
      "Readiness",
    ]);
  });
});
