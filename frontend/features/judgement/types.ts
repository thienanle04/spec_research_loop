export type JudgeSeverity = "CRITICAL" | "MAJOR" | "MINOR";

export type JudgeIssue = {
  id: string;
  finding_kind: string;
  severity: JudgeSeverity;
  reason: string;
  suggestion: string;
  target_card_id: string | null;
};

export type ConferenceScores = {
  originality: number;
  significance: number;
  soundness: number;
  clarity: number;
  reproducibility: number;
};

export type JudgeRun = {
  node: string;
  issues: JudgeIssue[];
  scores?: ConferenceScores | null;
};

export type JudgementStreamEvent =
  | { type: "progress"; node: string; message: string; pct: number }
  | { type: "draft_patch"; node: string; issues: JudgeIssue[]; scores?: ConferenceScores | null }
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
