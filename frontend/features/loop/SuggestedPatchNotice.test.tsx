import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SuggestedPatchNotice } from "./SuggestedPatchNotice";

describe("SuggestedPatchNotice", () => {
  it("renders prose and Card ids from Working Draft narrative", () => {
    render(
      <SuggestedPatchNotice
        narrative={{
          suggested_patch: "Cite a passage that entails the claim.",
          target_card_ids: ["card-1"],
        }}
      />,
    );
    expect(screen.getByRole("region", { name: "Suggested patch" })).toBeInTheDocument();
    expect(screen.getByText("Cite a passage that entails the claim.")).toBeInTheDocument();
    expect(screen.getByText("Card ids: card-1")).toBeInTheDocument();
  });

  it("renders nothing without a suggested patch", () => {
    const { container } = render(<SuggestedPatchNotice narrative={{ candidate: {} }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
