import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { JudgeRunRevisionView, isJudgeNode } from "@/features/judgement";
import { NodeHeadStatus, WorkflowNode, type HeadRevisionResponse } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

import { WORKFLOW_NODE_LABELS } from "./catalog";
import { StageRevisionBody } from "./StageRevisionBody";

export function HeadRevisionView({
  node,
  status,
  revision,
  available,
  upstreamNames,
  dimmed = false,
  onEdit,
  sessionId,
  stageRevisionId,
}: {
  node: WorkflowNode;
  status: NodeHeadStatus;
  revision: HeadRevisionResponse | null;
  available: boolean;
  upstreamNames: string[];
  dimmed?: boolean;
  onEdit?: () => void;
  sessionId: string;
  stageRevisionId?: string | null;
}) {
  const title = WORKFLOW_NODE_LABELS[node];
  return (
    <section aria-label={`${title} Stage Revision`}>
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3">
          <CardTitle className="font-serif text-navy">{title}</CardTitle>
          {onEdit ? (
            <Button type="button" variant="outline" size="sm" onClick={onEdit}>
              Edit {title}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          {!available ? (
            <p className="text-sm text-muted-foreground">
              Upstream Workflow Nodes are not current
              {upstreamNames.length > 0 ? `: ${upstreamNames.join(", ")}.` : "."}
            </p>
          ) : status === NodeHeadStatus.empty || revision == null ? (
            <p className="text-sm text-muted-foreground">No Stage Revision yet.</p>
          ) : (
            <div className={cn("grid gap-3", dimmed && "opacity-50")}>
              {status === NodeHeadStatus.stale ? (
                <p className="text-sm font-medium text-pending">Stale</p>
              ) : null}
              {isJudgeNode(node) ? (
                <JudgeRunRevisionView
                  sessionId={sessionId}
                  node={node}
                  stageRevisionId={stageRevisionId ?? null}
                />
              ) : (
                <StageRevisionBody
                  node={node}
                  payload={{ narrative: revision.narrative, card_snapshot: revision.card_snapshot }}
                  showNodeLabel={false}
                  sessionId={sessionId}
                  stageRevisionId={stageRevisionId ?? null}
                />
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
