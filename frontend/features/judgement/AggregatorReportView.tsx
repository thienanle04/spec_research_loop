"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { WorkflowNode } from "@/lib/api/generated/model";

import { HANDLING_OPTION_TARGETS, WORKFLOW_NODE_LABELS } from "../loop/catalog";
import { ConferenceScoreList } from "./ConferenceScoreList";
import { JudgeIssueList } from "./JudgeIssueList";
import { FINDING_KIND_LABELS, type HandlingOption, type JudgeIssue, type ConferenceScores } from "./types";

function clusterIssues(issues: JudgeIssue[], cluster: "consensus" | "disagreement") {
  return issues.filter((issue) => issue.cluster === cluster);
}

export function AggregatorReportView({
  issues,
  scores,
  handlingOptions,
  canPick = false,
  picking = false,
  pickError = null,
  onPick,
  onPickOther,
}: {
  issues: JudgeIssue[];
  scores: ConferenceScores | null;
  handlingOptions: HandlingOption[];
  canPick?: boolean;
  picking?: boolean;
  pickError?: string | null;
  onPick?: (option: HandlingOption) => void;
  onPickOther?: (prose: string, targetNode: WorkflowNode) => void;
}) {
  const consensus = clusterIssues(issues, "consensus");
  const disagreement = clusterIssues(issues, "disagreement");
  const [otherProse, setOtherProse] = useState("");
  const [otherTarget, setOtherTarget] = useState<WorkflowNode>(WorkflowNode.gap);
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
                {canPick ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    disabled={picking}
                    onClick={() => onPick?.(option)}
                  >
                    Pick {option.label}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {canPick ? (
          <form
            className="grid gap-3 rounded-md border border-border p-3"
            aria-label="Other Handling Option"
            onSubmit={(event) => {
              event.preventDefault();
              const prose = otherProse.trim();
              if (!prose) return;
              onPickOther?.(prose, otherTarget);
            }}
          >
            <p className="text-sm font-medium">Other</p>
            <p className="text-xs text-muted-foreground">
              Account-supplied prose and target Workflow Node. The Aggregator does not invent Other.
            </p>
            <div className="grid gap-1">
              <Label htmlFor="other-handling-prose">Other prose</Label>
              <Textarea
                id="other-handling-prose"
                value={otherProse}
                onChange={(event) => setOtherProse(event.target.value)}
                disabled={picking}
              />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="other-handling-target">Other target Workflow Node</Label>
              <select
                id="other-handling-target"
                className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
                value={otherTarget}
                disabled={picking}
                onChange={(event) => setOtherTarget(event.target.value as WorkflowNode)}
              >
                {HANDLING_OPTION_TARGETS.map((node) => (
                  <option key={node} value={node}>
                    {WORKFLOW_NODE_LABELS[node]}
                  </option>
                ))}
              </select>
            </div>
            <Button type="submit" variant="outline" size="sm" className="justify-self-start" disabled={picking}>
              Pick Other
            </Button>
          </form>
        ) : null}
        {pickError ? (
          <p role="alert" className="text-sm text-destructive">
            {pickError}
          </p>
        ) : null}
      </section>
      <ConferenceScoreList scores={scores} />
    </div>
  );
}
