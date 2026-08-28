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

export type CounterEvidenceOutcome =
  | "no_direct_counter_evidence"
  | "gap_narrowed"
  | "gap_not_supported"
  | "inconclusive";

export type CounterEvidenceResult = {
  result_key: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
  provider: string | null;
  provider_source_id: string | null;
  abstract: string | null;
  retrieval_score: number | null;
  reranker_score: number | null;
  discovery_queries: string[];
  verification_status: "pending" | "verified" | "warning" | "rejected";
  verification_messages: string[];
  content_basis: "metadata_only" | "abstract" | "full_text";
  evidence_passage: string | null;
  evidence_location: string | null;
  grounding_status: "pending" | "grounded" | "warning" | "rejected";
  relevance_status: "pending" | "relevant" | "irrelevant" | "uncertain";
  support_status: "pending" | "supported" | "unsupported" | "uncertain";
  impact: CounterEvidenceOutcome;
  rationale: string;
};

export type GapClaimAssessment = {
  claim_id: string;
  kind:
    | "existing_capability"
    | "unresolved_limitation"
    | "technical_mechanism"
    | "human_evaluation"
    | "domain_scope";
  statement: string;
  supporting_citation_keys: string[];
  supporting_evidence: {
    citation_key: string;
    passage: string;
    location: string;
  }[];
  counter_evidence_result_keys: string[];
  outcome: CounterEvidenceOutcome;
  assessment: string;
};

export type GapCandidate = {
  statement: string;
  supporting_citation_keys: string[];
  status: "candidate" | "insufficient_evidence" | "proposed";
  search_audit: {
    assessed_statement: string;
    related_work_queries: string[];
    counter_evidence_queries: string[];
    providers: string[];
    related_work_candidate_count: number;
    related_work_analyzed_count: number;
    counter_evidence_candidate_count: number;
    counter_evidence_analyzed_count: number;
    counter_evidence_outcome: CounterEvidenceOutcome;
    counter_evidence_assessment: string;
    counter_evidence_results: CounterEvidenceResult[];
    claim_assessments: GapClaimAssessment[];
    readiness_messages: string[];
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

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function counterEvidenceResults(value: unknown): CounterEvidenceResult[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw) => {
    const item = record(raw);
    if (typeof item.result_key !== "string" || typeof item.title !== "string") return [];
    const rawVerification = item.verification_status;
    const verificationStatus =
      rawVerification === "verified" ||
      rawVerification === "warning" ||
      rawVerification === "rejected"
        ? rawVerification
        : "pending";
    const rawImpact = item.impact;
    const impact: CounterEvidenceOutcome =
      rawImpact === "no_direct_counter_evidence" ||
      rawImpact === "gap_narrowed" ||
      rawImpact === "gap_not_supported"
        ? rawImpact
        : "inconclusive";
    return [
      {
        result_key: item.result_key,
        title: item.title,
        authors: strings(item.authors),
        year: optionalNumber(item.year),
        venue: optionalString(item.venue),
        doi: optionalString(item.doi),
        url: optionalString(item.url),
        provider: optionalString(item.provider),
        provider_source_id: optionalString(item.provider_source_id),
        abstract: optionalString(item.abstract),
        retrieval_score: optionalNumber(item.retrieval_score),
        reranker_score: optionalNumber(item.reranker_score),
        discovery_queries: strings(item.discovery_queries),
        verification_status: verificationStatus,
        verification_messages: strings(item.verification_messages),
        content_basis:
          item.content_basis === "abstract" || item.content_basis === "full_text"
            ? item.content_basis
            : "metadata_only",
        evidence_passage: optionalString(item.evidence_passage),
        evidence_location: optionalString(item.evidence_location),
        grounding_status:
          item.grounding_status === "grounded" ||
          item.grounding_status === "warning" ||
          item.grounding_status === "rejected"
            ? item.grounding_status
            : "pending",
        relevance_status:
          item.relevance_status === "relevant" ||
          item.relevance_status === "irrelevant" ||
          item.relevance_status === "uncertain"
            ? item.relevance_status
            : "pending",
        support_status:
          item.support_status === "supported" ||
          item.support_status === "unsupported" ||
          item.support_status === "uncertain"
            ? item.support_status
            : "pending",
        impact,
        rationale:
          typeof item.rationale === "string" && item.rationale.trim()
            ? item.rationale
            : "This result was not included in the validated assessment.",
      },
    ];
  });
}

function gapClaimAssessments(value: unknown): GapClaimAssessment[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw) => {
    const item = record(raw);
    if (
      typeof item.claim_id !== "string" ||
      typeof item.statement !== "string" ||
      typeof item.kind !== "string"
    ) {
      return [];
    }
    const allowedKinds: GapClaimAssessment["kind"][] = [
      "existing_capability",
      "unresolved_limitation",
      "technical_mechanism",
      "human_evaluation",
      "domain_scope",
    ];
    if (!allowedKinds.includes(item.kind as GapClaimAssessment["kind"])) return [];
    const rawOutcome = item.outcome;
    const outcome: CounterEvidenceOutcome =
      rawOutcome === "no_direct_counter_evidence" ||
      rawOutcome === "gap_narrowed" ||
      rawOutcome === "gap_not_supported"
        ? rawOutcome
        : "inconclusive";
    return [
      {
        claim_id: item.claim_id,
        kind: item.kind as GapClaimAssessment["kind"],
        statement: item.statement,
        supporting_citation_keys: strings(item.supporting_citation_keys),
        supporting_evidence: Array.isArray(item.supporting_evidence)
          ? item.supporting_evidence.flatMap((rawEvidence) => {
              const evidence = record(rawEvidence);
              if (
                typeof evidence.citation_key !== "string" ||
                typeof evidence.passage !== "string" ||
                typeof evidence.location !== "string"
              ) {
                return [];
              }
              return [
                {
                  citation_key: evidence.citation_key,
                  passage: evidence.passage,
                  location: evidence.location,
                },
              ];
            })
          : [],
        counter_evidence_result_keys: strings(item.counter_evidence_result_keys),
        outcome,
        assessment: typeof item.assessment === "string" ? item.assessment : "",
      },
    ];
  });
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
      assessed_statement:
        typeof audit.assessed_statement === "string" ? audit.assessed_statement : "",
      related_work_queries: strings(audit.related_work_queries),
      counter_evidence_queries: strings(audit.counter_evidence_queries),
      providers: strings(audit.providers),
      related_work_candidate_count: nonnegativeNumber(audit.related_work_candidate_count),
      related_work_analyzed_count: nonnegativeNumber(audit.related_work_analyzed_count),
      counter_evidence_candidate_count: nonnegativeNumber(audit.counter_evidence_candidate_count),
      counter_evidence_analyzed_count: nonnegativeNumber(audit.counter_evidence_analyzed_count),
      counter_evidence_outcome: counterEvidenceOutcome,
      counter_evidence_assessment:
        typeof audit.counter_evidence_assessment === "string"
          ? audit.counter_evidence_assessment
          : "",
      counter_evidence_results: counterEvidenceResults(audit.counter_evidence_results),
      claim_assessments: gapClaimAssessments(audit.claim_assessments),
      readiness_messages: strings(audit.readiness_messages),
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
  const normalize = (value: string) => value.trim().toLocaleLowerCase().replace(/\s+/g, " ");
  const substantiveResultsGrounded = candidate.search_audit.counter_evidence_results
    .every(
      (result) =>
        result.verification_status === "verified" &&
        result.content_basis !== "metadata_only" &&
        result.grounding_status === "grounded" &&
        result.relevance_status === "relevant" &&
        result.support_status === "supported" &&
        Boolean(result.evidence_passage?.trim()) &&
        Boolean(result.evidence_location?.trim()),
    );
  const counterKeys = new Set(
    candidate.search_audit.counter_evidence_results.map((result) => result.result_key),
  );
  const claimsSupported =
    candidate.search_audit.claim_assessments.length > 0 &&
    candidate.search_audit.claim_assessments.every(
      (claim) =>
        claim.supporting_citation_keys.length > 0 &&
        claim.supporting_citation_keys.every((key) => eligible.has(key)) &&
        claim.supporting_evidence.length > 0 &&
        new Set(claim.supporting_evidence.map((evidence) => evidence.citation_key)).size ===
          new Set(claim.supporting_citation_keys).size &&
        claim.supporting_evidence.every(
          (evidence) =>
            claim.supporting_citation_keys.includes(evidence.citation_key) &&
            Boolean(evidence.passage.trim()) &&
            Boolean(evidence.location.trim()),
        ) &&
        (claim.outcome === "no_direct_counter_evidence" || claim.outcome === "gap_narrowed") &&
        claim.counter_evidence_result_keys.length === counterKeys.size &&
        claim.counter_evidence_result_keys.every((key) => counterKeys.has(key)),
    );
  const mappedSupporting = new Set(
    candidate.search_audit.claim_assessments.flatMap(
      (claim) => claim.supporting_citation_keys,
    ),
  );
  const relatedPortfolioSize = Math.min(
    5,
    candidate.search_audit.related_work_candidate_count,
  );
  const counterPortfolioSize = Math.min(
    5,
    candidate.search_audit.counter_evidence_candidate_count,
  );
  return (
    normalize(candidate.statement) === normalize(candidate.search_audit.assessed_statement) &&
    supporting.size > 0 &&
    [...supporting].every((key) => eligible.has(key)) &&
    candidate.evidence_check.ready &&
    candidate.search_audit.complete &&
    candidate.search_audit.readiness_messages.length === 0 &&
    candidate.search_audit.related_work_analyzed_count === relatedPortfolioSize &&
    supporting.size === relatedPortfolioSize &&
    candidate.search_audit.counter_evidence_analyzed_count > 0 &&
    candidate.search_audit.counter_evidence_analyzed_count <= counterPortfolioSize &&
    counterKeys.size === counterPortfolioSize &&
    mappedSupporting.size === supporting.size &&
    [...mappedSupporting].every((key) => supporting.has(key)) &&
    candidate.search_audit.counter_evidence_outcome !== "gap_not_supported" &&
    candidate.search_audit.counter_evidence_outcome !== "inconclusive" &&
    substantiveResultsGrounded &&
    claimsSupported
  );
}
