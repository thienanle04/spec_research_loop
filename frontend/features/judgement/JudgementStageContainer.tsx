"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiErrorMessage } from "@/lib/api/config";
import { getGetSessionApiLoopSessionsSessionIdGetQueryKey } from "@/lib/api/generated/endpoints";
import { WorkflowNode, NodeHeadStatus, type LoopSessionResponse } from "@/lib/api/generated/model";
import { customFetch } from "@/lib/api/mutator";

import { WORKFLOW_NODE_LABELS } from "../loop/catalog";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { withGeneratedSincePrepare } from "../loop/stage-signals";
import { JudgeIssueList } from "./JudgeIssueList";
import type { JudgeIssue, JudgeNode, JudgeRun } from "./types";
import { useJudgementStream } from "./useJudgementStream";

const GENERATABLE_JUDGE_NODES = new Set<string>([
  WorkflowNode.gap_judge,
  WorkflowNode.contribution_judge,
  WorkflowNode.evidence_judge,
  WorkflowNode.experiment_judge,
]);

type Props = {
  sessionId: string;
  session: LoopSessionResponse;
  generateRequestId?: number;
  onRunningChange?: (running: boolean) => void;
  onConfirmabilityChange?: (confirmable: boolean) => void;
};

function judgeRunQueryKey(sessionId: string, node: string, revisionId?: string | null) {
  return ["/api/judgement/run", sessionId, node, revisionId ?? "working"] as const;
}

export function JudgementStageContainer({
  sessionId,
  session,
  generateRequestId = 0,
  onRunningChange,
  onConfirmabilityChange,
}: Props) {
  const queryClient = useQueryClient();
  const { queue } = useLoopSessionSave();
  const stream = useJudgementStream();
  const seenGenerateRequestIdRef = useRef(generateRequestId);
  const [issues, setIssues] = useState<JudgeIssue[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const node = session.working_draft_node as JudgeNode;
  const canGenerate = GENERATABLE_JUDGE_NODES.has(node);
  const workingHead = session.node_heads.find((head) => head.node === session.working_draft_node);
  const staleReaccept =
    workingHead?.status === NodeHeadStatus.stale && workingHead.generated_since_prepare !== true;
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  const runQuery = useQuery({
    queryKey: judgeRunQueryKey(sessionId, node),
    queryFn: async () => {
      const response = await customFetch<{ data: JudgeRun; status: number }>(
        `/api/judgement/sessions/${sessionId}/nodes/${node}`,
        { method: "GET" },
      );
      return response.data;
    },
  });

  useEffect(() => {
    if (runQuery.data?.issues) {
      setIssues(runQuery.data.issues);
    }
  }, [runQuery.data]);

  useEffect(() => {
    onConfirmabilityChange?.(true);
  }, [onConfirmabilityChange]);

  useEffect(() => {
    onRunningChange?.(stream.running);
  }, [onRunningChange, stream.running]);

  function expectedVersion(): number {
    const cached = queryClient.getQueryData(sessionKey) as
      | { status: number; data: LoopSessionResponse }
      | undefined;
    if (cached?.status === 200) {
      return cached.data.version;
    }
    return session.version;
  }

  function updateSession(next: LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, { status: 200, data: next });
  }

  async function generate(options?: { staleReaccept?: boolean }) {
    setSaveError(null);
    try {
      await queue.flush();
      await stream.start({
        sessionId,
        node,
        expectedVersion: expectedVersion(),
        staleReaccept: options?.staleReaccept === true,
        onEvent: (event) => {
          if (event.type === "draft_patch") {
            setIssues(event.issues);
          } else if (event.type === "done") {
            updateSession(
              withGeneratedSincePrepare(
                {
                  ...session,
                  version: event.version,
                },
                session.working_draft_node,
              ),
            );
          }
        },
      });
      await queryClient.invalidateQueries({ queryKey: judgeRunQueryKey(sessionId, node) });
    } catch (error) {
      setSaveError(getApiErrorMessage(error));
    }
  }

  useEffect(() => {
    const previous = seenGenerateRequestIdRef.current;
    seenGenerateRequestIdRef.current = generateRequestId;
    if (generateRequestId < 1 || generateRequestId <= previous) return;
    void generate({ staleReaccept });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stale-dialog trigger only
  }, [generateRequestId]);

  const title = WORKFLOW_NODE_LABELS[session.working_draft_node];
  const error = stream.error ?? saveError ?? (runQuery.isError ? "Could not load Judge Issues." : null);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-navy">{title}</CardTitle>
        <CardDescription>
          Independent Judges evaluate the Valid Spec Version. Confirm freezes this Judge Run even when
          CRITICAL Issues remain.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <JudgeIssueList issues={issues} />
        {stream.running ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" onClick={stream.abort}>
              Stop Judge
            </Button>
            <p role="status" className="text-sm text-muted-foreground">
              {stream.progressMessage ?? "Running Judge…"}
            </p>
          </div>
        ) : canGenerate ? (
          <Button type="button" variant="outline" className="justify-self-start" onClick={() => void generate()}>
            {issues.length > 0 ? `Regenerate ${title}` : `Generate ${title}`}
          </Button>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function JudgeRunRevisionView({
  sessionId,
  node,
  stageRevisionId,
}: {
  sessionId: string;
  node: WorkflowNode;
  stageRevisionId: string | null;
}) {
  const runQuery = useQuery({
    queryKey: judgeRunQueryKey(sessionId, node, stageRevisionId),
    enabled: Boolean(stageRevisionId),
    queryFn: async () => {
      const params = new URLSearchParams({ stage_revision_id: stageRevisionId ?? "" });
      const response = await customFetch<{ data: JudgeRun; status: number }>(
        `/api/judgement/sessions/${sessionId}/nodes/${node}?${params.toString()}`,
        { method: "GET" },
      );
      return response.data;
    },
  });
  if (!stageRevisionId) {
    return <p className="text-sm text-muted-foreground">No Stage Revision yet.</p>;
  }
  if (runQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading Judge Issues…</p>;
  }
  if (runQuery.isError || !runQuery.data) {
    return <p className="text-sm text-destructive">Could not load frozen Judge Issues.</p>;
  }
  return <JudgeIssueList issues={runQuery.data.issues} />;
}
