import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CardKind, LoopStage, WorkflowNode } from "@/lib/api/generated/model";

import { ResearchDemoLauncher } from "./ResearchDemoLauncher";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  createSession: vi.fn(),
  patchDraft: vi.fn(),
  createCard: vi.fn(),
  confirm: vi.fn(),
  prepare: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/research-demo",
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
}));

vi.mock("@/features/identity", () => ({
  useAccount: () => ({
    ready: true,
    hasToken: true,
    signedIn: true,
    isLoading: false,
  }),
}));

vi.mock("@/lib/api/generated/endpoints", () => ({
  createSessionApiLoopSessionsPost: mocks.createSession,
  patchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch: mocks.patchDraft,
  createCardApiLoopSessionsSessionIdCardsPost: mocks.createCard,
  confirmApiLoopSessionsSessionIdConfirmPost: mocks.confirm,
  recomputePrepareApiLoopSessionsSessionIdRecomputePreparePost: mocks.prepare,
}));

describe("ResearchDemoLauncher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.createSession.mockResolvedValue({
      status: 201,
      data: { id: "session-demo", version: 1 },
    });
    mocks.patchDraft.mockResolvedValue({ status: 200, data: { version: 2 } });
    mocks.confirm
      .mockResolvedValueOnce({ status: 200, data: { version: 3 } })
      .mockResolvedValueOnce({ status: 200, data: { version: 8 } });
    mocks.createCard
      .mockResolvedValueOnce({ status: 201, data: { version: 4 } })
      .mockResolvedValueOnce({ status: 201, data: { version: 5 } })
      .mockResolvedValueOnce({ status: 201, data: { version: 6 } })
      .mockResolvedValueOnce({ status: 201, data: { version: 7 } });
    mocks.prepare.mockResolvedValue({ status: 200, data: { version: 9 } });
  });

  it("bootstraps the prepared Idea and opens Research Inputs", async () => {
    const user = userEvent.setup();
    render(<ResearchDemoLauncher />);

    expect(screen.getByText(/claim checklist for paper summaries/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create and open Research demo" }));

    await waitFor(() => {
      expect(mocks.push).toHaveBeenCalledWith(
        "/sessions/session-demo?stage=related_work",
      );
    });
    expect(mocks.confirm).toHaveBeenNthCalledWith(1, "session-demo", {
      node: WorkflowNode.idea_interpretation,
      expected_version: 2,
    });
    expect(mocks.createCard.mock.calls.map((call) => call[1].kind)).toEqual([
      CardKind.problem,
      CardKind.research_question,
      CardKind.constraint,
      CardKind.open_question,
    ]);
    expect(mocks.confirm).toHaveBeenNthCalledWith(2, "session-demo", {
      node: WorkflowNode.idea_decomposition,
      expected_version: 7,
    });
    expect(mocks.prepare).toHaveBeenCalledWith("session-demo", {
      stage: LoopStage.related_work,
      expected_version: 8,
    });
  });

  it("shows a recoverable error when bootstrap fails", async () => {
    const user = userEvent.setup();
    mocks.createSession.mockRejectedValueOnce(new Error("Backend unavailable"));
    render(<ResearchDemoLauncher />);

    await user.click(screen.getByRole("button", { name: "Create and open Research demo" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
    expect(screen.getByRole("button", { name: "Create and open Research demo" })).toBeEnabled();
  });
});
