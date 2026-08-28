"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { isCompleteGap, type GapCandidate } from "./types";

const impactLabels = {
  no_direct_counter_evidence: "No direct counter-evidence found",
  gap_narrowed: "Potential Gap narrowed by existing work",
  gap_not_supported: "Existing work appears to address this limitation",
  inconclusive: "Not enough evidence to decide",
} as const;

function sourceHref(url: string | null, doi: string | null): string | null {
  return url ?? (doi ? `https://doi.org/${doi}` : null);
}

type Props = {
  candidate: GapCandidate | null;
  selectedGap: GapCandidate | null;
  disabled?: boolean;
  onSelect: (candidate: GapCandidate) => Promise<void> | void;
};

export function GapCandidatePicker({ candidate, selectedGap, disabled, onSelect }: Props) {
  const [editing, setEditing] = useState<GapCandidate | null>(selectedGap ?? candidate);

  useEffect(() => {
    setEditing(selectedGap ?? candidate);
  }, [candidate, selectedGap]);

  if (!editing) {
    return (
      <section aria-label="Gap Candidate">
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          No Gap Candidate has been generated yet. Use Generate Gap Candidate when you are ready.
        </p>
      </section>
    );
  }

  const evidenceReady = isCompleteGap(editing);
  const hasStatement = Boolean(editing.statement.trim());
  const normalize = (value: string) => value.trim().toLocaleLowerCase().replace(/\s+/g, " ");
  const auditStale =
    normalize(editing.statement) !== normalize(editing.search_audit.assessed_statement);
  const claimsHaveCounterAudit =
    editing.search_audit.counter_evidence_results.length > 0 &&
    editing.search_audit.claim_assessments.every(
      (claim) => claim.counter_evidence_result_keys.length > 0,
    );
  const evidenceWarning = auditStale
    ? "This summary was edited after the literature review. Regenerate it before treating the evidence as current."
    : editing.search_audit.counter_evidence_outcome === "gap_not_supported"
      ? "Existing work appears to address this Gap. Review the counter-evidence before continuing."
      : editing.search_audit.counter_evidence_outcome === "inconclusive"
        ? "The limitations below are supported by Related Work, but there is not enough verified counter-evidence to determine whether they remain unresolved. Treat this as a potential Gap."
        : !evidenceReady
          ? "Some evidence checks are still incomplete. Only source-supported limitations are shown."
          : null;

  return (
    <section aria-label="Gap Candidate" className="grid gap-4">
      <div>
        <h3 className="font-medium">Gap Candidate</h3>
        <p className="text-sm text-muted-foreground">
          This potential Gap summarizes source-supported limitations and how confidently the
          counter-evidence review could assess them.
        </p>
      </div>
      <div className="grid gap-4 rounded-md border border-navy p-4">
        <label className="grid gap-2 text-sm font-medium">
          Gap Candidate summary
          <Textarea
            value={editing.statement}
            disabled={disabled}
            rows={6}
            onChange={(event) => setEditing({ ...editing, statement: event.target.value })}
          />
        </label>
        <div className="grid gap-1 rounded-md bg-muted/50 p-3 text-sm" role="status">
          <p className="font-medium">
            {evidenceReady
              ? "Evidence-ready Gap Candidate"
              : editing.search_audit.counter_evidence_outcome === "inconclusive"
                ? "Potential Gap — further validation needed"
                : "Evidence needs review"}
          </p>
          <p className="text-muted-foreground">
            {editing.search_audit.related_work_analyzed_count} Related Work result(s) and {editing.search_audit.counter_evidence_analyzed_count} counter-evidence result(s) analyzed.
          </p>
          {!evidenceReady ? (
            <div className="grid gap-1 text-pending">
              <p>
                You can continue with this potential Gap, but keep its uncertainty visible in later stages.
              </p>
              {evidenceWarning ? (
                <ul className="list-disc pl-5">
                  <li>{evidenceWarning}</li>
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
        {editing.search_audit.counter_evidence_assessment ? (
          <div className="grid gap-1 text-sm">
            <p className="font-medium">Counter-evidence assessment</p>
            <p className="text-muted-foreground">
              {editing.search_audit.counter_evidence_assessment}
            </p>
          </div>
        ) : null}
        {editing.search_audit.claim_assessments.length > 0 ? (
          <div
            className="grid gap-2 text-sm"
            role="region"
            aria-label={
              claimsHaveCounterAudit
                ? "Atomic Gap claims"
                : "Source-grounded limitations awaiting counter-evidence audit"
            }
          >
            <p className="font-medium">
              {claimsHaveCounterAudit
                ? "Atomic Gap claims"
                : "Source-grounded limitations awaiting counter-evidence audit"}
            </p>
            <ul className="grid gap-2">
              {editing.search_audit.claim_assessments.map((claim) => (
                <li key={claim.claim_id} className="grid gap-1 rounded-md border p-3">
                  <p>{claim.statement}</p>
                  <p className="text-muted-foreground">
                    Supported by Related Work · Counter-evidence review:{" "}
                    {impactLabels[claim.outcome]}
                  </p>
                  {claim.assessment ? (
                    <p className="text-muted-foreground">{claim.assessment}</p>
                  ) : null}
                  {claim.supporting_evidence.map((evidence) => (
                    <blockquote
                      key={`${claim.claim_id}-${evidence.citation_key}`}
                      className="border-l-2 pl-3 text-muted-foreground"
                    >
                      “{evidence.passage}” — {evidence.location} · {evidence.citation_key}
                    </blockquote>
                  ))}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {editing.search_audit.counter_evidence_results.length > 0 ? (
          <div className="grid gap-2 text-sm" aria-label="Counter-evidence sources">
            <p className="font-medium">Counter-evidence sources</p>
            <ul className="grid gap-3">
              {editing.search_audit.counter_evidence_results.map((result) => {
                const href = sourceHref(result.url, result.doi);
                return (
                  <li key={result.result_key} className="grid gap-1 rounded-md border p-3">
                    <p className="font-medium">
                      {href ? (
                        <a href={href} target="_blank" rel="noreferrer" className="underline">
                          {result.title}
                        </a>
                      ) : (
                        result.title
                      )}
                    </p>
                    <p className="text-muted-foreground">
                      {[result.year, result.venue, result.provider].filter(Boolean).join(" · ")}
                    </p>
                    <p>
                      {impactLabels[result.impact]} · Source identity: {result.verification_status}
                    </p>
                    <p>
                      Content: {result.content_basis.replaceAll("_", " ")} · Grounding:{" "}
                      {result.grounding_status} · Relevance: {result.relevance_status} · Support:{" "}
                      {result.support_status}
                    </p>
                    <p className="text-muted-foreground">{result.rationale}</p>
                    {result.evidence_passage ? (
                      <blockquote className="border-l-2 pl-3 text-muted-foreground">
                        “{result.evidence_passage}”
                        {result.evidence_location ? ` — ${result.evidence_location}` : ""}
                      </blockquote>
                    ) : null}
                    {result.verification_messages.length > 0 ? (
                      <p className="text-muted-foreground">
                        {result.verification_messages.join(" ")}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
        <Button
          type="button"
          className="justify-self-start"
          disabled={disabled || !hasStatement}
          onClick={() => void onSelect(editing)}
        >
          {selectedGap ? "Save Gap Candidate changes" : "Save Gap Candidate"}
        </Button>
      </div>
    </section>
  );
}
