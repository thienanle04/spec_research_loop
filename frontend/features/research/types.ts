import type {
  CitationResponse,
} from "@/lib/api/generated/model";

export type PreferredSources = {
  peer_reviewed_papers: boolean;
  official_proceedings: boolean;
  author_materials: boolean;
  sourced_surveys: boolean;
};

export type ResearchInputs = {
  keywords: string[];
  preferred_sources: PreferredSources;
};

export type GapCandidate = {
  statement: string;
  supporting_citation_keys: string[];
  status: "candidate" | "insufficient_evidence" | "proposed";
  search_audit: {
    related_work_queries: string[];
    counter_evidence_queries: string[];
    providers: string[];
    related_work_candidate_count: number;
    related_work_analyzed_count: number;
    counter_evidence_candidate_count: number;
    counter_evidence_analyzed_count: number;
    counter_evidence_outcome:
      | "no_direct_counter_evidence"
      | "gap_narrowed"
      | "gap_not_supported"
      | "inconclusive";
    completed_at: string | null;
    complete: boolean;
  };
  evidence_check: {
    verified_citation_keys: string[];
    grounded_citation_keys: string[];
    eligible_citation_keys: string[];
    ready: boolean;
    messages: string[];
  };
};

export type ResearchStreamEvent =
  | { type: "progress"; node: string; message: string; pct: number }
  | { type: "citation_upsert"; node: "related_work"; citation: CitationResponse }
  | { type: "draft_patch"; node: string; narrative: Record<string, unknown> }
  | { type: "warning"; node: string; code: string; message: string }
  | { type: "done"; node: string; version: number; citation_count: number }
  | { type: "error"; node: string; code: string; message: string };

export function emptyResearchInputs(): ResearchInputs {
  return {
    keywords: [],
    preferred_sources: {
      peer_reviewed_papers: true,
      official_proceedings: true,
      author_materials: true,
      sourced_surveys: true,
    },
  };
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function nonnegativeNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

export function researchInputsFrom(value: Record<string, unknown>): ResearchInputs {
  const rawPreferred =
    value.preferred_sources &&
    typeof value.preferred_sources === "object" &&
    !Array.isArray(value.preferred_sources)
      ? (value.preferred_sources as Record<string, unknown>)
      : null;
  return {
    keywords: strings(value.keywords),
    preferred_sources: {
      peer_reviewed_papers:
        typeof rawPreferred?.peer_reviewed_papers === "boolean"
          ? rawPreferred.peer_reviewed_papers
          : true,
      official_proceedings:
        typeof rawPreferred?.official_proceedings === "boolean"
          ? rawPreferred.official_proceedings
          : true,
      author_materials:
        typeof rawPreferred?.author_materials === "boolean"
          ? rawPreferred.author_materials
          : true,
      sourced_surveys:
        typeof rawPreferred?.sourced_surveys === "boolean"
          ? rawPreferred.sourced_surveys
          : true,
    },
  };
}

export function gapCandidateFrom(value: unknown): GapCandidate | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (typeof item.statement !== "string") return null;
  const audit = record(item.search_audit);
  const evidence = record(item.evidence_check);
  const rawStatus = item.status;
  const status =
    rawStatus === "candidate" || rawStatus === "insufficient_evidence" || rawStatus === "proposed"
      ? rawStatus
      : "insufficient_evidence";
  const rawOutcome = audit.counter_evidence_outcome;
  const counterEvidenceOutcome =
    rawOutcome === "no_direct_counter_evidence" ||
    rawOutcome === "gap_narrowed" ||
    rawOutcome === "gap_not_supported" ||
    rawOutcome === "inconclusive"
      ? rawOutcome
      : "inconclusive";
  return {
    statement: item.statement as string,
    supporting_citation_keys: strings(item.supporting_citation_keys),
    status,
    search_audit: {
      related_work_queries: strings(audit.related_work_queries),
      counter_evidence_queries: strings(audit.counter_evidence_queries),
      providers: strings(audit.providers),
      related_work_candidate_count: nonnegativeNumber(audit.related_work_candidate_count),
      related_work_analyzed_count: nonnegativeNumber(audit.related_work_analyzed_count),
      counter_evidence_candidate_count: nonnegativeNumber(audit.counter_evidence_candidate_count),
      counter_evidence_analyzed_count: nonnegativeNumber(audit.counter_evidence_analyzed_count),
      counter_evidence_outcome: counterEvidenceOutcome,
      completed_at: typeof audit.completed_at === "string" ? audit.completed_at : null,
      complete: audit.complete === true,
    },
    evidence_check: {
      verified_citation_keys: strings(evidence.verified_citation_keys),
      grounded_citation_keys: strings(evidence.grounded_citation_keys),
      eligible_citation_keys: strings(evidence.eligible_citation_keys),
      ready: evidence.ready === true,
      messages: strings(evidence.messages),
    },
  };
}

export function gapCandidateFromNarrative(value: Record<string, unknown>): GapCandidate | null {
  return gapCandidateFrom(value.candidate);
}

export function isCompleteGap(candidate: GapCandidate | null): boolean {
  if (!candidate?.statement.trim() || candidate.status !== "candidate") return false;
  const supporting = new Set(candidate.supporting_citation_keys);
  const eligible = new Set(candidate.evidence_check.eligible_citation_keys);
  return (
    supporting.size > 0 &&
    [...supporting].every((key) => eligible.has(key)) &&
    candidate.evidence_check.ready &&
    candidate.search_audit.complete &&
    candidate.search_audit.counter_evidence_outcome !== "gap_not_supported" &&
    candidate.search_audit.counter_evidence_outcome !== "inconclusive"
  );
}
