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
import type {
  ConferenceScores,
  HandlingOption,
  JudgeIssue,
  JudgeNode,
  JudgeRun,
  JudgementStreamEvent,
} from "./types";
import { FIVE_JUDGE_NODES, JUDGE_HEAD_PURPOSE } from "./types";
import { useJudgementStream } from "./useJudgementStream";

type Props = {
  sessionId: string;
  session: LoopSessionResponse;
  onRunningChange?: (running: boolean) => void;
  onConfirmabilityChange?: (confirmable: boolean) => void;
  onPicked?: (next: LoopSessionResponse) => void;
};

function judgeRunQueryKey(sessionId: string, node: string, revisionId?: string | null) {
  return ["/api/judgement/run", sessionId, node, revisionId ?? "working"] as const;
}

function compactHeadStatusLabel(
  displayStatus: "running" | "current" | NodeHeadStatus | string,
): "evaluating" | "none" | "done" | "stale" {
  if (displayStatus === "running") return "evaluating";
  if (displayStatus === NodeHeadStatus.empty) return "none";
  if (displayStatus === NodeHeadStatus.current || displayStatus === "current") return "done";
  return "stale";
}

export function JudgementStageContainer({
  sessionId,
  session,
  onRunningChange,
  onConfirmabilityChange,
  onPicked,
}: Props) {
  const queryClient = useQueryClient();
  const { queue } = useLoopSessionSave();
  const stream = useJudgementStream();
  const startedAggregatorKeyRef = useRef<string | null>(null);
  const [issues, setIssues] = useState<JudgeIssue[]>([]);
  const [scores, setScores] = useState<ConferenceScores | null>(null);
  const [handlingOptions, setHandlingOptions] = useState<HandlingOption[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [headSummaries, setHeadSummaries] = useState<
    Partial<Record<JudgeNode, { status?: "running" | "current" }>>
  >({});
  const node = WorkflowNode.aggregator as JudgeNode;
  const hasOutput = issues.length > 0 || scores != null || handlingOptions.length > 0;
  const aggregatorConfirmable =
    session.working_draft_node === WorkflowNode.aggregator && hasOutput;
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
  const fiveJudgeHeadsCurrent = FIVE_JUDGE_NODES.every((judge) => {
    const head = session.node_heads.find((item) => item.node === judge);
    return head?.status === NodeHeadStatus.current;
  });
  const aggregatorNeedsGenerate =
    (workingHead?.status ?? NodeHeadStatus.empty) !== NodeHeadStatus.current;
  const aggregatorStartKey = fiveJudgeHeadsCurrent
    ? `${sessionId}:${workingHead?.status ?? NodeHeadStatus.empty}:${workingHead?.stage_revision_id ?? ""}`
    : null;

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
    onConfirmabilityChange?.(aggregatorConfirmable);
    return () => onConfirmabilityChange?.(false);
  }, [aggregatorConfirmable, onConfirmabilityChange]);

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

  function applyAggregatorReportEvent(event: JudgementStreamEvent) {
    if (event.node !== WorkflowNode.aggregator) return;
    if (event.type === "draft_patch") {
      setIssues(event.issues);
      setScores(event.scores ?? null);
      setHandlingOptions(event.handling_options ?? []);
    }
  }

  function applyJudgeHeadEvent(event: JudgementStreamEvent) {
    if (!(FIVE_JUDGE_NODES as readonly string[]).includes(event.node)) return;
    const judge = event.node as JudgeNode;
    if (event.type === "progress" || event.type === "draft_patch") {
      setHeadSummaries((current) => ({
        ...current,
        [judge]: { status: "running" },
      }));
    } else if (event.type === "done") {
      setHeadSummaries((current) => ({
        ...current,
        [judge]: { status: "current" },
      }));
    } else if (event.type === "error") {
      setHeadSummaries((current) => ({
        ...current,
        [judge]: { status: undefined },
      }));
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
          applyJudgeHeadEvent(event);
          applyAggregatorReportEvent(event);
          if (event.type === "draft_patch") {
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
            void queryClient.invalidateQueries({ queryKey: sessionKey });
          }
        },
      });
      await queryClient.invalidateQueries({ queryKey: ["/api/judgement/run", sessionId] });
      await queryClient.invalidateQueries({ queryKey: sessionKey });
    } catch (error) {
      setSaveError(getApiErrorMessage(error));
    }
  }

  const loadedAggregatorOutput =
    (runQuery.data?.issues?.length ?? 0) > 0 ||
    runQuery.data?.scores != null ||
    (runQuery.data?.handling_options?.length ?? 0) > 0;

  useEffect(() => {
    if (aggregatorStartKey == null || !aggregatorNeedsGenerate) return;
    if (runQuery.isPending || loadedAggregatorOutput || stream.running) return;
    if (startedAggregatorKeyRef.current === aggregatorStartKey) return;
    startedAggregatorKeyRef.current = aggregatorStartKey;
    void generate({ staleReaccept });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- start once per empty/Stale Aggregator when five Judge heads are current
  }, [
    aggregatorStartKey,
    aggregatorNeedsGenerate,
    runQuery.isPending,
    loadedAggregatorOutput,
    stream.running,
    staleReaccept,
  ]);

  const title = WORKFLOW_NODE_LABELS[WorkflowNode.aggregator];
  const error = stream.error ?? saveError ?? (runQuery.isError ? "Could not load Judge Run." : null);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-navy">{title}</CardTitle>
        <CardDescription>
          The Aggregator copies Judge Issues and scores. Confirm freezes the report even when
          CRITICAL Issues remain.
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
            const summary = headSummaries[judge];
            const statusLabel = compactHeadStatusLabel(summary?.status ?? status);
            return (
              <li
                key={judge}
                aria-label={WORKFLOW_NODE_LABELS[judge]}
                className="flex h-full flex-col gap-2 rounded-md border border-border bg-card px-3 py-2"
              >
                <p className="text-sm text-navy">{JUDGE_HEAD_PURPOSE[judge]}</p>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">{statusLabel}</p>
              </li>
            );
          })}
        </ul>
        {stream.running ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" onClick={stream.abort}>
              Stop generation
            </Button>
            <p role="status" className="text-sm text-muted-foreground">
              {stream.progressMessage ?? "Generating…"}
            </p>
          </div>
        ) : canRunPending ? (
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={() => void generatePending()}
          >
            Run evaluation
          </Button>
        ) : null}
        <AggregatorReportView
          issues={issues}
          scores={scores}
          handlingOptions={handlingOptions}
          canPick={hasOutput}
          picking={picking}
          onPick={(option) => void pick({ handling_option_id: option.id })}
          onPickOther={(prose, targetNode) =>
            void pick({ prose, target_node: targetNode })
          }
        />
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
