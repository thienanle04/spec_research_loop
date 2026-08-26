"use client";

import { useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import type { PreferredSources, ResearchInputs } from "./types";

type Props = {
  value: ResearchInputs;
  disabled?: boolean;
  onChange: (value: ResearchInputs) => void;
};

function KeywordEditor({
  values,
  disabled,
  onChange,
}: {
  values: string[];
  disabled?: boolean;
  onChange: (values: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  function addDraft() {
    const item = draft.trim();
    if (!item || values.includes(item)) return;
    onChange([...values, item]);
    setDraft("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addDraft();
    }
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm font-medium">Keywords</legend>
      {values.length > 0 ? (
        <div className="flex flex-wrap gap-2" aria-label="Keywords values">
          {values.map((value) => (
            <span
              key={value}
              className="inline-flex items-center gap-1 rounded-full border bg-muted px-3 py-1 text-sm"
            >
              {value}
              <button
                type="button"
                aria-label={`Remove ${value}`}
                className="rounded-full px-1 text-muted-foreground hover:text-destructive"
                disabled={disabled}
                onClick={() => onChange(values.filter((item) => item !== value))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <div className="flex gap-2">
        <Input
          value={draft}
          disabled={disabled}
          placeholder="Add a keyword or search concept"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={addDraft}
        />
        <Button
          type="button"
          variant="outline"
          aria-label="Add keyword"
          disabled={disabled || !draft.trim()}
          onClick={addDraft}
        >
          Add
        </Button>
      </div>
    </fieldset>
  );
}

const SOURCE_OPTIONS: Array<[keyof PreferredSources, string]> = [
  ["peer_reviewed_papers", "Peer-reviewed papers"],
  ["official_proceedings", "Official proceedings"],
  ["author_materials", "Author materials"],
  ["sourced_surveys", "Surveys with clear sources"],
];

export function ResearchInputsEditor({ value, disabled, onChange }: Props) {
  const patch = <K extends keyof ResearchInputs>(key: K, next: ResearchInputs[K]) =>
    onChange({ ...value, [key]: next });

  function patchPreferredSource(key: keyof PreferredSources, checked: boolean) {
    patch("preferred_sources", { ...value.preferred_sources, [key]: checked });
  }

  return (
    <div className="grid gap-5">
      <section className="grid gap-4 rounded-md border p-4" aria-label="Keywords">
        <div>
          <h3 className="font-medium">Keywords</h3>
          <p className="text-sm text-muted-foreground">
            Confirm the concepts that Related Work will use to generate search queries.
          </p>
        </div>
        <KeywordEditor
          values={value.keywords}
          disabled={disabled}
          onChange={(next) => patch("keywords", next)}
        />
      </section>

      <fieldset className="grid gap-3 rounded-md border p-4">
        <legend className="font-medium">Preferred Sources</legend>
        <p className="text-sm text-muted-foreground">
          Selected categories are prioritized when scholarly results are ranked.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {SOURCE_OPTIONS.map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 rounded-md border p-3 text-sm">
              <input
                type="checkbox"
                checked={value.preferred_sources[key]}
                disabled={disabled}
                onChange={(event) => patchPreferredSource(key, event.target.checked)}
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  );
}
