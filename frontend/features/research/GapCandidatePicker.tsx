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

  return (
    <section aria-label="Gap Candidate" className="grid gap-4">
      <div>
        <h3 className="font-medium">Gap Candidate</h3>
        <p className="text-sm text-muted-foreground">
          This concise candidate synthesizes all confirmed Related Work. You can edit the summary before saving it.
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
        <Button
          type="button"
          className="justify-self-start"
          disabled={disabled || !isCompleteGap(editing)}
          onClick={() => void onSelect(editing)}
        >
          {selectedGap ? "Save Gap Candidate changes" : "Save Gap Candidate"}
        </Button>
      </div>
    </section>
  );
}
