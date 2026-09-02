import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExportScratchMarkdownEditor } from "./ExportScratchMarkdownEditor";

describe("ExportScratchMarkdownEditor", () => {
  it("shows Source and Preview tabs and a live preview", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ExportScratchMarkdownEditor value={"## Gap\n\nTiling DRAM traffic."} onChange={onChange} />,
    );
    expect(screen.getByRole("tab", { name: "Source" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Preview" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("region", { name: "Export Scratch preview" })).toHaveTextContent(
      "Tiling DRAM traffic.",
    );
    expect(screen.getByRole("region", { name: "Export Scratch preview" })).toHaveClass("bg-card");
    expect(screen.getByRole("region", { name: "Export Scratch preview" })).not.toHaveClass("hidden");
    await user.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByRole("tab", { name: "Preview" })).toHaveAttribute("aria-selected", "true");
  });

  it("renders claim headings distinctly from labeled body fields", () => {
    render(
      <ExportScratchMarkdownEditor
        value={"### **Main claim**\n\n**Baseline:**\nuntiled\n\n---\n\n### **Second claim**"}
        onChange={vi.fn()}
      />,
    );
    const preview = screen.getByRole("region", { name: "Export Scratch preview" });
    const headings = preview.querySelectorAll("h3");
    expect(headings).toHaveLength(2);
    expect(headings[0]).toHaveTextContent("Main claim");
    expect(headings[0]?.className).toMatch(/font-semibold/);
    expect(preview.querySelector("hr")).not.toBeNull();
  });
});
