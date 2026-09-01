"use client";

import { Button } from "@/components/ui/button";

import type { DiscoveryLeads, ToolCoverage } from "./types";

type Props = {
  running: boolean;
  progress: number;
  progressMessage: string | null;
  warnings: string[];
  discoveryLeads?: DiscoveryLeads | null;
  toolCoverage?: ToolCoverage[];
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
  discoveryLeads,
  toolCoverage = [],
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
            The system proposes tools only from central mechanism keywords, runs one exact query per tool, then uses ranking context to keep the most Idea-relevant article for each tool.
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
      {discoveryLeads ? (
        <div className="grid gap-2 rounded-md border bg-background p-3 text-sm">
          <div>
            <h4 className="font-medium">LLM discovery leads</h4>
            <p className="text-muted-foreground">
              Only tool-generation keywords can propose tools. Ranking-context keywords are used only to choose the paper that best matches the Idea.
            </p>
          </div>
          <LeadGroup
            label="Tool-generation keywords"
            values={discoveryLeads.tool_discovery_keywords}
          />
          <LeadGroup
            label="Ranking-context keywords"
            values={discoveryLeads.supporting_context_keywords}
          />
          <ToolLeadGroup
            values={discoveryLeads.tools_and_frameworks}
            coverage={toolCoverage}
          />
          <LeadGroup label="Techniques" values={discoveryLeads.techniques} />
          <LeadGroup label="Candidate works" values={discoveryLeads.candidate_work_titles} />
          <LeadGroup label="Aliases" values={discoveryLeads.aliases} />
        </div>
      ) : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}

function ToolLeadGroup({
  values,
  coverage,
}: {
  values: string[];
  coverage: ToolCoverage[];
}) {
  if (values.length === 0) return null;
  const byName = new Map(coverage.map((item) => [item.tool.toLocaleLowerCase(), item]));
  return (
    <div>
      <span className="font-medium">Tools and frameworks: </span>
      <span className="inline-flex flex-wrap gap-1.5">
        {values.map((value) => {
          const item = byName.get(value.toLocaleLowerCase());
          return (
            <span
              key={value}
              title={item?.article_title ?? undefined}
              className="rounded border px-1.5 py-0.5 text-xs"
            >
              {value}
              {item ? (item.status === "matched_citation" ? " · cited" : " · not found") : ""}
            </span>
          );
        })}
      </span>
    </div>
  );
}

function LeadGroup({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div>
      <span className="font-medium">{label}: </span>
      <span>{values.join(", ")}</span>
    </div>
  );
}
