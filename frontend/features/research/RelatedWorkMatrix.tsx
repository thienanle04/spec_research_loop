import { FileText } from "lucide-react";

import type { CitationResponse, RelatedWorkFindingResponse } from "@/lib/api/generated/model";

type Props = {
  citations: CitationResponse[];
  findings: RelatedWorkFindingResponse[];
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
      <blockquote className="mt-2 border-l-2 pl-2 leading-5 text-muted-foreground">
        “{evidence.passage}”
      </blockquote>
    </details>
  );
}

export function RelatedWorkMatrix({ citations, findings }: Props) {
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
          <table className="w-full min-w-[980px] border-collapse text-left text-sm">
            <thead className="bg-muted/70">
              <tr>
                <th className="w-[18%] border-r p-3 font-semibold">Study</th>
                <th className="w-[25%] border-r p-3 font-semibold">What was done?</th>
                <th className="w-[22%] border-r p-3 font-semibold">Method or feedback</th>
                <th className="w-[27%] border-r p-3 font-semibold">Remaining limitation</th>
                <th className="w-[8%] p-3 text-center font-semibold">Source</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding) => {
                const citation = citationsById.get(finding.citation_id);
                const href = sourceHref(citation);
                const title = citation?.title ?? "Citation not found";
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
                          {title}
                        </a>
                      ) : (
                        <p className="font-semibold">{title}</p>
                      )}
                      <p className="mt-1 text-xs text-muted-foreground">
                        {citation?.year ? `(${citation.year})` : citation?.citation_key}
                      </p>
                    </td>
                    <td className="border-r p-3 leading-6">
                      {finding.what_was_done}
                      <EvidenceSupport evidence={evidenceFor(finding, "what_was_done")} />
                    </td>
                    <td className="border-r p-3 leading-6">
                      {finding.method_or_feedback || "Not stated in the source metadata"}
                      <EvidenceSupport evidence={evidenceFor(finding, "method_or_feedback")} />
                    </td>
                    <td className="border-r p-3 leading-6">
                      {finding.limitation}
                      <EvidenceSupport evidence={evidenceFor(finding, "limitation")} />
                    </td>
                    <td className="p-3 text-center">
                      {href ? (
                        <a
                          aria-label={`Open source: ${title}`}
                          className="inline-flex size-10 items-center justify-center rounded-xl border border-in-progress/25 bg-in-progress/10 text-in-progress transition-colors hover:bg-in-progress/15"
                          href={href}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <FileText aria-hidden="true" className="size-5" />
                        </a>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
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
