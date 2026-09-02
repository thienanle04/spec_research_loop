import { Pin, PinOff } from "lucide-react";

import type { CitationResponse, RelatedWorkFindingResponse } from "@/lib/api/generated/model";

type Props = {
  citations: CitationResponse[];
  findings: RelatedWorkFindingResponse[];
  pinningCitationId?: string | null;
  onToggleCitationPin?: (citation: CitationResponse) => void;
};

type RetrievalCitation = CitationResponse & {
  pinned?: boolean;
  retrieval_score?: number | null;
  text_source_kind?: string | null;
  text_char_count?: number | null;
};

type EvidenceKey = "what_was_done" | "method_or_feedback" | "limitation";
type SourceEvidence = { passage: string; location: string };
type FindingWithEvidence = RelatedWorkFindingResponse & {
  evidence?: Partial<Record<EvidenceKey, SourceEvidence>>;
};

function sourceHref(citation: CitationResponse | undefined): string | null {
  if (!citation) return null;
  return citation.url || (citation.doi ? `https://doi.org/${citation.doi}` : null);
}

function researchWorkName(citation: CitationResponse | undefined): string {
  const value = citation?.metadata?.research_work_name;
  if (typeof value === "string" && value.trim()) return value.trim();
  const [prefix, suffix] = (citation?.title ?? "").split(":", 2);
  if (suffix && prefix.trim().split(/\s+/).length <= 6 && prefix.trim().length <= 60) {
    return prefix.trim();
  }
  return "Unnamed research work";
}

function evidenceFor(finding: RelatedWorkFindingResponse, key: EvidenceKey): SourceEvidence {
  const evidence = (finding as FindingWithEvidence).evidence?.[key];
  return evidence?.passage && evidence.location
    ? evidence
    : { passage: finding.supporting_passage, location: "Source excerpt" };
}

function EvidenceSupport({ evidence }: { evidence: SourceEvidence }) {
  return (
    <details className="mt-3 rounded-md border bg-muted/40 p-2 text-xs">
      <summary className="cursor-pointer font-medium">Evidence · {evidence.location}</summary>
      <blockquote className="mt-2 whitespace-pre-line break-words border-l-2 pl-2 leading-5 text-muted-foreground">
        “{evidence.passage}”
      </blockquote>
    </details>
  );
}

export function RelatedWorkMatrix({
  citations,
  findings,
  pinningCitationId,
  onToggleCitationPin,
}: Props) {
  const citationsById = new Map(citations.map((citation) => [citation.id, citation]));

  return (
    <section aria-label="Related Work comparison" className="grid gap-3">
      <div>
        <h3 className="font-medium">Related Work comparison</h3>
        <p className="text-sm text-muted-foreground">
          Compare prior work, feedback methods, and remaining limitations. Expand Evidence in each cell to inspect the exact source passage and location behind that assertion.
        </p>
      </div>
      {findings.length === 0 ? (
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          Search and analyze scholarly sources to build the comparison.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full min-w-[900px] border-collapse text-left text-sm">
            <thead className="bg-muted/70">
              <tr>
                <th className="w-[18%] border-r p-3 font-semibold">Study</th>
                <th className="w-[27%] border-r p-3 font-semibold">What was done?</th>
                <th className="w-[24%] border-r p-3 font-semibold">Method or feedback</th>
                <th className="w-[31%] p-3 font-semibold">Remaining limitation</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding) => {
                const citation = citationsById.get(finding.citation_id);
                const href = sourceHref(citation);
                const title = citation?.title ?? "Citation not found";
                const studyName = researchWorkName(citation);
                const retrieval = citation as RetrievalCitation | undefined;
                return (
                  <tr key={finding.id} className="border-t align-top">
                    <td className="border-r p-3">
                      {href ? (
                        <a
                          className="font-semibold text-in-progress hover:underline"
                          href={href}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {studyName}
                        </a>
                      ) : (
                        <p className="font-semibold">{studyName}</p>
                      )}
                      <p className="mt-1 text-xs text-muted-foreground">
                        {citation?.year ? `(${citation.year})` : citation?.citation_key}
                      </p>
                      <p className="mt-2 text-xs leading-5 text-muted-foreground">
                        Article: {title}
                      </p>
                      {retrieval ? (
                        <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-muted-foreground">
                          {typeof retrieval.retrieval_score === "number" ? (
                            <span className="rounded bg-muted px-1.5 py-0.5">
                              Relevance {Math.round(retrieval.retrieval_score * 100)}%
                            </span>
                          ) : null}
                          {retrieval.text_source_kind ? (
                            <span className="rounded bg-muted px-1.5 py-0.5">
                              {retrieval.text_source_kind.replaceAll("_", " ")}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                      {citation && onToggleCitationPin ? (
                        <button
                          type="button"
                          className="mt-2 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                          disabled={pinningCitationId === citation.id}
                          onClick={() => onToggleCitationPin(citation)}
                        >
                          {retrieval?.pinned ? (
                            <PinOff aria-hidden="true" className="size-3" />
                          ) : (
                            <Pin aria-hidden="true" className="size-3" />
                          )}
                          {retrieval?.pinned ? "Unpin" : "Keep on rerun"}
                        </button>
                      ) : null}
                    </td>
                    <td className="border-r p-3 leading-6">
                      {finding.what_was_done}
                      <EvidenceSupport evidence={evidenceFor(finding, "what_was_done")} />
                    </td>
                    <td className="border-r p-3 leading-6">
                      {finding.method_or_feedback || "Not stated in the source metadata"}
                      <EvidenceSupport evidence={evidenceFor(finding, "method_or_feedback")} />
                    </td>
                    <td className="p-3 leading-6">
                      {finding.limitation}
                      <EvidenceSupport evidence={evidenceFor(finding, "limitation")} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
