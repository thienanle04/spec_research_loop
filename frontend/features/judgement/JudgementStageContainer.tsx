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
import { AggregatorReportView } from "./AggregatorReportView";
import { ConferenceScoreList } from "./ConferenceScoreList";
import { JudgeIssueList } from "./JudgeIssueList";
import type { ConferenceScores, HandlingOption, JudgeIssue, JudgeNode, JudgeRun } from "./types";
import { FIVE_JUDGE_NODES } from "./types";
import { useJudgementStream } from "./useJudgementStream";

type Props = {
  sessionId: string;
  session: LoopSessionResponse;
  generateRequestId?: number;
  onRunningChange?: (running: boolean) => void;
  onConfirmabilityChange?: (confirmable: boolean) => void;
  onPicked?: (next: LoopSessionResponse) => void;
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
  onPicked,
}: Props) {
  const queryClient = useQueryClient();
  const { queue } = useLoopSessionSave();
  const stream = useJudgementStream();
  const seenGenerateRequestIdRef = useRef(generateRequestId);
  const [issues, setIssues] = useState<JudgeIssue[]>([]);
  const [scores, setScores] = useState<ConferenceScores | null>(null);
  const [handlingOptions, setHandlingOptions] = useState<HandlingOption[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const node = WorkflowNode.aggregator as JudgeNode;
  const canGenerate = true;
  const hasOutput = issues.length > 0 || scores != null || handlingOptions.length > 0;
  const workingHead = session.node_heads.find((head) => head.node === WorkflowNode.aggregator);
  const staleReaccept =
    workingHead?.status === NodeHeadStatus.stale && workingHead.generated_since_prepare !== true;
  const pendingJudges = FIVE_JUDGE_NODES.filter((judge) => {
    const head = session.node_heads.find((item) => item.node === judge);
    const status = head?.status ?? NodeHeadStatus.empty;
    return status === NodeHeadStatus.empty || status === NodeHeadStatus.stale;
  });
  const canRunPending = pendingJudges.length > 0;
  const pendingNeedsReaccept = pendingJudges.some((judge) => {
    const head = session.node_heads.find((item) => item.node === judge);
    return head?.status === NodeHeadStatus.stale && head.generated_since_prepare !== true;
  });
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
    if (runQuery.data) {
      setScores(runQuery.data.scores ?? null);
      setHandlingOptions(runQuery.data.handling_options ?? []);
    }
  }, [runQuery.data]);

  useEffect(() => {
    onConfirmabilityChange?.(true);
  }, [onConfirmabilityChange]);

  useEffect(() => {
    onRunningChange?.(stream.running);
  }, [onRunningChange, stream.running]);

  function expectedVersion(): number {
    return currentSession().version;
  }

  function currentSession(): LoopSessionResponse {
    const cached = queryClient.getQueryData(sessionKey) as
      | { status: number; data: LoopSessionResponse }
      | undefined;
    if (cached?.status === 200) {
      return cached.data;
    }
    return session;
  }

  function updateSession(next: LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, { status: 200, data: next });
  }

  async function pick(body: {
    handling_option_id?: string;
    prose?: string;
    target_node?: WorkflowNode;
  }) {
    setSaveError(null);
    setPicking(true);
    try {
      await queue.flush();
      const response = await customFetch<{ data: LoopSessionResponse; status: number }>(
        `/api/loop/sessions/${sessionId}/pick`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_version: expectedVersion(),
            ...body,
          }),
        },
      );
      updateSession(response.data);
      onPicked?.(response.data);
    } catch (error) {
      setSaveError(getApiErrorMessage(error));
    } finally {
      setPicking(false);
    }
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
            setScores(event.scores ?? null);
            setHandlingOptions(event.handling_options ?? []);
          } else if (event.type === "done") {
            const latest = currentSession();
            updateSession(
              withGeneratedSincePrepare(
                {
                  ...latest,
                  version: event.version,
                },
                event.node as WorkflowNode,
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

  async function generatePending() {
    setSaveError(null);
    try {
      await queue.flush();
      await stream.startPending({
        sessionId,
        expectedVersion: expectedVersion(),
        staleReaccept: pendingNeedsReaccept,
        onEvent: (event) => {
          if (event.type === "draft_patch") {
            if (event.node === node) {
              setIssues(event.issues);
              setScores(event.scores ?? null);
              setHandlingOptions(event.handling_options ?? []);
            }
            void queryClient.invalidateQueries({
              queryKey: judgeRunQueryKey(sessionId, event.node),
            });
          } else if (event.type === "done") {
            const latest = currentSession();
            updateSession(
              withGeneratedSincePrepare(
                {
                  ...latest,
                  version: event.version,
                },
                event.node as WorkflowNode,
              ),
            );
          }
        },
      });
      await queryClient.invalidateQueries({ queryKey: ["/api/judgement/run", sessionId] });
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

  const title = WORKFLOW_NODE_LABELS[WorkflowNode.aggregator];
  const error = stream.error ?? saveError ?? (runQuery.isError ? "Could not load Judge Run." : null);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-navy">{title}</CardTitle>
        <CardDescription>
          The Aggregator copies Judge Issues and scores. It does not majority-vote. Confirm freezes
          the report even when CRITICAL Issues remain.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <ul
          aria-label="Judge Node Heads"
          className="grid gap-2 sm:grid-cols-5"
        >
          {FIVE_JUDGE_NODES.map((judge) => {
            const head = session.node_heads.find((item) => item.node === judge);
            const status = head?.status ?? NodeHeadStatus.empty;
            return (
              <li
                key={judge}
                className="rounded-md border border-border bg-card px-3 py-2"
              >
                <p className="text-sm font-medium text-navy">{WORKFLOW_NODE_LABELS[judge]}</p>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">{status}</p>
              </li>
            );
          })}
        </ul>
        <AggregatorReportView
          issues={issues}
          scores={scores}
          handlingOptions={handlingOptions}
          canPick
          picking={picking}
          onPick={(option) => void pick({ handling_option_id: option.id })}
          onPickOther={(prose, targetNode) =>
            void pick({ prose, target_node: targetNode })
          }
        />
        {stream.running ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" onClick={stream.abort}>
              Stop Judge
            </Button>
            <p role="status" className="text-sm text-muted-foreground">
              {stream.progressMessage ?? "Running Judge…"}
            </p>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            {canGenerate ? (
              <Button type="button" variant="outline" onClick={() => void generate()}>
                {hasOutput ? `Regenerate ${title}` : `Generate ${title}`}
              </Button>
            ) : null}
            {canRunPending ? (
              <Button type="button" variant="outline" onClick={() => void generatePending()}>
                Run pending Judges
              </Button>
            ) : null}
          </div>
        )}
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
    return <p className="text-sm text-muted-foreground">Loading Judge Run…</p>;
  }
  if (runQuery.isError || !runQuery.data) {
    return <p className="text-sm text-destructive">Could not load frozen Judge Run.</p>;
  }
  if (node === WorkflowNode.conference_judge) {
    return <ConferenceScoreList scores={runQuery.data.scores ?? null} />;
  }
  if (node === WorkflowNode.aggregator) {
    return (
      <AggregatorReportView
        issues={runQuery.data.issues}
        scores={runQuery.data.scores ?? null}
        handlingOptions={runQuery.data.handling_options ?? []}
      />
    );
  }
  return <JudgeIssueList issues={runQuery.data.issues} />;
}
