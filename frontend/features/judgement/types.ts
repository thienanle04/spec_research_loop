export type JudgeSeverity = "CRITICAL" | "MAJOR" | "MINOR";

export type JudgeIssueGrounds = {
  subject: string;
  excerpts: { citation_key: string; passage: string }[];
};

export type JudgeIssue = {
  id: string;
  finding_kind: string;
  severity: JudgeSeverity;
  reason: string;
  suggestion: string;
  target_card_id: string | null;
  source_node?: string | null;
  cluster?: "consensus" | "disagreement" | null;
  grounds?: JudgeIssueGrounds | null;
};

export type ConferenceScores = {
  originality: number;
  significance: number;
  soundness: number;
  clarity: number;
  reproducibility: number;
};

export type HandlingOption = {
  id: string;
  finding_kind: string;
  source_node: string;
  label: string;
  target_node: string;
  prose: string;
  aggregator_issue_id?: string | null;
};

export type ReadinessState = "not_evaluated" | "blocked" | "ready";

export type JudgeRun = {
  node: string;
  issues: JudgeIssue[];
  scores?: ConferenceScores | null;
  clusters?: {
    consensus: JudgeIssue[];
    disagreement: JudgeIssue[];
  } | null;
  handling_options?: HandlingOption[] | null;
  readiness?: ReadinessState | null;
};

export type Readiness = {
  state: ReadinessState;
  notice: string;
  scores?: ConferenceScores | null;
};

export type JudgementStreamEvent =
  | { type: "progress"; node: string; message: string; pct: number }
  | { type: "draft_patch"; node: string; issues: JudgeIssue[]; scores?: ConferenceScores | null; handling_options?: HandlingOption[] | null }
  | { type: "done"; node: string; version: number }
  | { type: "error"; node: string; code: string; message: string };

export const JUDGE_NODES = [
  "gap_judge",
  "contribution_judge",
  "evidence_judge",
  "experiment_judge",
  "conference_judge",
  "aggregator",
] as const;

export const FIVE_JUDGE_NODES = [
  "gap_judge",
  "contribution_judge",
  "evidence_judge",
  "experiment_judge",
  "conference_judge",
] as const;

export const JUDGE_HEAD_PURPOSE: Record<(typeof FIVE_JUDGE_NODES)[number], string> = {
  gap_judge: "Check whether the gap is actually supported by the literature.",
  contribution_judge: "Check whether the contribution is new, clear, and overstated.",
  evidence_judge: "Check whether citations actually support the accompanying content.",
  experiment_judge: "Check whether the experiments are sufficient to support the claim.",
  conference_judge:
    "Evaluate originality, significance, soundness, clarity, and reproducibility.",
};

export type JudgeNode = (typeof JUDGE_NODES)[number];

export function isJudgeNode(node: string): node is JudgeNode {
  return (JUDGE_NODES as readonly string[]).includes(node);
}

export const FINDING_KIND_LABELS: Record<string, string> = {
  gap_unsupported_by_sources: "Gap unsupported by sources",
  gap_already_addressed: "Gap already addressed",
  gap_untestable: "Gap untestable",
  contribution_not_novel: "Contribution not novel",
  contribution_overclaimed: "Contribution overclaimed",
  unsupported_citation: "Unsupported citation",
  claim_broader_than_experiment: "Claim broader than experiment",
  experiment_insufficient_for_claim: "Experiment insufficient for claim",
};
