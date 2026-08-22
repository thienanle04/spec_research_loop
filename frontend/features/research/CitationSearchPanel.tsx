"use client";

import { Button } from "@/components/ui/button";

type Props = {
  running: boolean;
  progress: number;
  progressMessage: string | null;
  warnings: string[];
  error: string | null;
  disabled?: boolean;
  onSearch: () => void;
  onAbort: () => void;
};

export function CitationSearchPanel({
  running,
  progress,
  progressMessage,
  warnings,
  error,
  disabled,
  onSearch,
  onAbort,
}: Props) {
  return (
    <section aria-label="Related Work search" className="grid gap-3 rounded-md border bg-muted/30 p-4">
      <div>
        <h3 className="font-medium">Search and analyze</h3>
        <p className="text-sm text-muted-foreground">
          The system generates search queries from the confirmed Research Inputs, retrieves scholarly sources, and analyzes them against the research idea.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {running ? (
          <Button type="button" variant="outline" onClick={onAbort}>
            Stop search
          </Button>
        ) : (
          <Button type="button" disabled={disabled} onClick={onSearch}>
            {error ? "Retry search" : "Search and analyze"}
          </Button>
        )}
      </div>
      {running || progressMessage ? (
        <div role="status" className="grid gap-1 text-sm">
          <div className="h-2 overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full bg-in-progress transition-[width]"
              style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
            />
          </div>
          <p>{progressMessage ?? "Starting search…"}</p>
        </div>
      ) : null}
      {warnings.length > 0 ? (
        <ul role="status" className="list-disc pl-5 text-sm text-pending">
          {warnings.map((warning, index) => (
            <li key={`${warning}-${index}`}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
