import { WORKFLOW_NODE_LABELS } from "../loop/catalog";

import { FINDING_KIND_LABELS, type JudgeIssue } from "./types";

function severityClass(severity: JudgeIssue["severity"]): string {
  switch (severity) {
    case "CRITICAL":
      return "text-destructive";
    case "MAJOR":
      return "text-pending";
    default:
      return "text-muted-foreground";
  }
}

function judgeLabel(sourceNode: string | null | undefined): string | null {
  if (!sourceNode) return null;
  if (sourceNode in WORKFLOW_NODE_LABELS) {
    return WORKFLOW_NODE_LABELS[sourceNode as keyof typeof WORKFLOW_NODE_LABELS];
  }
  return sourceNode;
}

function hasGrounds(issue: JudgeIssue): boolean {
  const grounds = issue.grounds;
  if (!grounds) return false;
  return Boolean(grounds.subject.trim()) || grounds.excerpts.length > 0;
}

export function JudgeIssueList({ issues }: { issues: JudgeIssue[] }) {
  if (issues.length === 0) {
    return <p className="text-sm text-muted-foreground">No Judge Issues on this Judge Run.</p>;
  }
  return (
    <ul className="grid gap-3" aria-label="Judge Issues">
      {issues.map((issue) => {
        const origin = judgeLabel(issue.source_node);
        return (
          <li key={issue.id} className="rounded-md border border-border p-3">
            <p className="text-sm font-medium">
              {FINDING_KIND_LABELS[issue.finding_kind] ?? issue.finding_kind}
              <span className={`ml-2 text-xs ${severityClass(issue.severity)}`}>{issue.severity}</span>
            </p>
            {origin ? (
              <p className="mt-1 text-xs text-muted-foreground" aria-label="Originating Judge">
                {origin}
              </p>
            ) : null}
            {issue.reason ? <p className="mt-1 text-sm whitespace-pre-wrap">{issue.reason}</p> : null}
            {hasGrounds(issue) ? (
              <div className="mt-2 grid gap-2" aria-label="Judge Issue Grounds">
                {issue.grounds?.subject ? (
                  <p className="text-sm whitespace-pre-wrap">{issue.grounds.subject}</p>
                ) : null}
                {issue.grounds?.excerpts.map((excerpt, index) => (
                  <p key={`${excerpt.citation_key}-${index}`} className="text-sm text-muted-foreground">
                    {excerpt.citation_key ? (
                      <span className="font-medium text-navy">{excerpt.citation_key}</span>
                    ) : null}
                    {excerpt.citation_key ? " — " : null}
                    <span>{excerpt.passage.trim() ? excerpt.passage : "No supporting passage"}</span>
                  </p>
                ))}
              </div>
            ) : null}
            {issue.suggestion ? (
              <p className="mt-1 text-sm text-muted-foreground whitespace-pre-wrap">{issue.suggestion}</p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
