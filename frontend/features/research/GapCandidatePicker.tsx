"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { isCompleteGap, type GapCandidate } from "./types";

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
            {evidenceReady ? "Evidence-ready Gap Candidate" : "Insufficient evidence"}
          </p>
          <p className="text-muted-foreground">
            {editing.search_audit.related_work_analyzed_count} Related Work result(s) and {editing.search_audit.counter_evidence_analyzed_count} counter-evidence result(s) analyzed.
          </p>
          {!evidenceReady ? (
            <p className="text-pending">
              Saving is disabled until verified Citations, grounded passages, and a conclusive search audit are available.
            </p>
          ) : null}
        </div>
        <Button
          type="button"
          className="justify-self-start"
          disabled={disabled || !evidenceReady}
          onClick={() => void onSelect(editing)}
        >
          {selectedGap ? "Save Gap Candidate changes" : "Save Gap Candidate"}
        </Button>
      </div>
    </section>
  );
}
