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

export function JudgeIssueList({ issues }: { issues: JudgeIssue[] }) {
  if (issues.length === 0) {
    return <p className="text-sm text-muted-foreground">No Judge Issues on this Judge Run.</p>;
  }
  return (
    <ul className="grid gap-3" aria-label="Judge Issues">
      {issues.map((issue) => (
        <li key={issue.id} className="rounded-md border border-border p-3">
          <p className="text-sm font-medium">
            {FINDING_KIND_LABELS[issue.finding_kind] ?? issue.finding_kind}
            <span className={`ml-2 text-xs ${severityClass(issue.severity)}`}>{issue.severity}</span>
          </p>
          {issue.reason ? <p className="mt-1 text-sm whitespace-pre-wrap">{issue.reason}</p> : null}
          {issue.suggestion ? (
            <p className="mt-1 text-sm text-muted-foreground whitespace-pre-wrap">{issue.suggestion}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
