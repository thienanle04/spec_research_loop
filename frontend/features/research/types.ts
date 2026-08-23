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
  status: "proposed";
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
  return {
    statement: item.statement as string,
    supporting_citation_keys: strings(item.supporting_citation_keys),
    status: "proposed",
  };
}

export function gapCandidateFromNarrative(value: Record<string, unknown>): GapCandidate | null {
  return gapCandidateFrom(value.candidate);
}

export function isCompleteGap(candidate: GapCandidate | null): boolean {
  return Boolean(candidate?.statement.trim());
}
