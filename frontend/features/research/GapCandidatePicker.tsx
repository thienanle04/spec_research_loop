"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { isCompleteGap, type GapCandidate } from "./types";

const impactLabels = {
  no_direct_counter_evidence: "No direct counter-evidence",
  gap_narrowed: "Narrows the Gap",
  gap_not_supported: "Gap already addressed",
  inconclusive: "Inconclusive",
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
  const evidenceWarnings = [
    ...(editing.search_audit.counter_evidence_outcome === "gap_not_supported"
      ? ["Counter-evidence indicates that the proposed Gap is already addressed by existing work."]
      : []),
    ...(editing.search_audit.counter_evidence_outcome === "inconclusive"
      ? ["The counter-evidence search was inconclusive."]
      : []),
    ...editing.evidence_check.messages,
  ];

  return (
    <section aria-label="Gap Candidate" className="grid gap-4">
      <div>
        <h3 className="font-medium">Gap Candidate</h3>
        <p className="text-sm text-muted-foreground">
          This candidate synthesizes the top five Related Work results and a separate counter-evidence search. You can edit the summary without changing its audit.
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
            {evidenceReady ? "Evidence-ready Gap Candidate" : "Evidence warning"}
          </p>
          <p className="text-muted-foreground">
            {editing.search_audit.related_work_analyzed_count} Related Work result(s) and {editing.search_audit.counter_evidence_analyzed_count} counter-evidence result(s) analyzed.
          </p>
          {!evidenceReady ? (
            <div className="grid gap-1 text-pending">
              <p>
                Evidence is incomplete or does not support this Gap Candidate. You can still save and Confirm; the decision is yours.
              </p>
              {evidenceWarnings.length > 0 ? (
                <ul className="list-disc pl-5">
                  {evidenceWarnings.map((warning, index) => (
                    <li key={`${warning}-${index}`}>{warning}</li>
                  ))}
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
                      {impactLabels[result.impact]} · Verification: {result.verification_status}
                    </p>
                    <p className="text-muted-foreground">{result.rationale}</p>
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
