import { FINDING_KIND_LABELS, type HandlingOption, type JudgeIssue, type ConferenceScores } from "./types";
import { ConferenceScoreList } from "./ConferenceScoreList";
import { JudgeIssueList } from "./JudgeIssueList";
import { WORKFLOW_NODE_LABELS } from "../loop/catalog";
import { WorkflowNode } from "@/lib/api/generated/model";

function clusterIssues(issues: JudgeIssue[], cluster: "consensus" | "disagreement") {
  return issues.filter((issue) => issue.cluster === cluster);
}

export function AggregatorReportView({
  issues,
  scores,
  handlingOptions,
}: {
  issues: JudgeIssue[];
  scores: ConferenceScores | null;
  handlingOptions: HandlingOption[];
}) {
  const consensus = clusterIssues(issues, "consensus");
  const disagreement = clusterIssues(issues, "disagreement");
  return (
    <div className="grid gap-6">
      <section className="grid gap-2" aria-label="Consensus">
        <h3 className="text-sm font-medium text-navy">Consensus</h3>
        {consensus.length === 0 ? (
          <p className="text-sm text-muted-foreground">No consensus Judge Issues.</p>
        ) : (
          <JudgeIssueList issues={consensus} />
        )}
      </section>
      <section className="grid gap-2" aria-label="Disagreement">
        <h3 className="text-sm font-medium text-navy">Disagreement</h3>
        {disagreement.length === 0 ? (
          <p className="text-sm text-muted-foreground">No disagreement Judge Issues.</p>
        ) : (
          <JudgeIssueList issues={disagreement} />
        )}
      </section>
      <section className="grid gap-2" aria-label="Handling Options">
        <h3 className="text-sm font-medium text-navy">Handling Options</h3>
        {handlingOptions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Handling Options are offered for CRITICAL and MAJOR Judge Issues.
          </p>
        ) : (
          <ul className="grid gap-3">
            {handlingOptions.map((option) => (
              <li key={option.id} className="rounded-md border border-border p-3">
                <p className="text-sm font-medium">{option.label}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {FINDING_KIND_LABELS[option.finding_kind] ?? option.finding_kind}
                  {option.target_node in WORKFLOW_NODE_LABELS
                    ? ` → ${WORKFLOW_NODE_LABELS[option.target_node as WorkflowNode]}`
                    : null}
                </p>
                {option.prose ? (
                  <p className="mt-1 text-sm whitespace-pre-wrap">{option.prose}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <ConferenceScoreList scores={scores} />
    </div>
  );
}
