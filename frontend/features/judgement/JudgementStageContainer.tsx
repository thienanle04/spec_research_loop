"use client";

import { useEffect, useRef, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

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

function severityCounts(issues: JudgeIssue[]) {
  return {
    CRITICAL: issues.filter((item) => item.severity === "CRITICAL").length,
    MAJOR: issues.filter((item) => item.severity === "MAJOR").length,
    MINOR: issues.filter((item) => item.severity === "MINOR").length,
  };
}

type HeadSummary = {
  status?: "running" | "current";
  issues?: JudgeIssue[];
  scores?: ConferenceScores | null;
};

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
  const [generatingNode, setGeneratingNode] = useState<JudgeNode | null>(null);
  const [staleDialogJudge, setStaleDialogJudge] = useState<JudgeNode | null>(null);
  const [headSummaries, setHeadSummaries] = useState<Partial<Record<JudgeNode, HeadSummary>>>({});
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
  const judgeRuns = useQueries({
    queries: FIVE_JUDGE_NODES.map((judge) => {
      const head = session.node_heads.find((item) => item.node === judge);
      const empty = (head?.status ?? NodeHeadStatus.empty) === NodeHeadStatus.empty;
      return {
        queryKey: judgeRunQueryKey(sessionId, judge),
        enabled: !empty,
        queryFn: async () => {
          const response = await customFetch<{ data: JudgeRun; status: number }>(
            `/api/judgement/sessions/${sessionId}/nodes/${judge}`,
            { method: "GET" },
          );
          return response.data;
        },
      };
    }),
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

  function judgeNeedsStaleReaccept(judge: JudgeNode): boolean {
    const head = currentSession().node_heads.find((item) => item.node === judge);
    return head?.status === NodeHeadStatus.stale && head.generated_since_prepare !== true;
  }

  async function generateJudge(judge: JudgeNode, options?: { staleReaccept?: boolean }) {
    if (judgeNeedsStaleReaccept(judge) && options?.staleReaccept !== true) {
      setStaleDialogJudge(judge);
      return;
    }
    setStaleDialogJudge(null);
    setSaveError(null);
    setGeneratingNode(judge);
    try {
      await queue.flush();
      await stream.start({
        sessionId,
        node: judge,
        expectedVersion: expectedVersion(),
        staleReaccept: options?.staleReaccept === true,
        onEvent: (event) => {
          if (event.node !== judge) return;
          if (event.type === "draft_patch") {
            setHeadSummaries((current) => ({
              ...current,
              [judge]: {
                status: "running",
                issues: event.issues,
                scores: event.scores ?? null,
              },
            }));
          } else if (event.type === "done") {
            setHeadSummaries((current) => ({
              ...current,
              [judge]: { ...current[judge], status: "current" },
            }));
            void queryClient.invalidateQueries({ queryKey: sessionKey });
          }
        },
      });
      await queryClient.invalidateQueries({ queryKey: judgeRunQueryKey(sessionId, judge) });
      await queryClient.invalidateQueries({ queryKey: sessionKey });
    } catch (error) {
      setSaveError(getApiErrorMessage(error));
      setHeadSummaries((current) => ({
        ...current,
        [judge]: { ...current[judge], status: undefined },
      }));
    } finally {
      setGeneratingNode((current) => (current === judge ? null : current));
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
          {FIVE_JUDGE_NODES.map((judge, index) => {
            const head = session.node_heads.find((item) => item.node === judge);
            const status = head?.status ?? NodeHeadStatus.empty;
            const summary = headSummaries[judge];
            const displayStatus = generatingNode === judge ? "running" : (summary?.status ?? status);
            const run = judgeRuns[index]?.data;
            const issues = summary?.issues ?? run?.issues ?? [];
            const scores = summary?.scores ?? run?.scores ?? null;
            const counts = severityCounts(issues);
            const empty = displayStatus === NodeHeadStatus.empty;
            const label = WORKFLOW_NODE_LABELS[judge];
            const canGenerateHead = generatingNode == null && !stream.running;
            return (
              <li
                key={judge}
                className="rounded-md border border-border bg-card px-3 py-2"
              >
                <p className="text-sm font-medium text-navy">{label}</p>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">{displayStatus}</p>
                {displayStatus !== "running" && judge === WorkflowNode.conference_judge && scores != null ? (
                  <p className="mt-1 text-xs tabular-nums text-muted-foreground">
                    <span>{scores.originality}/10</span>
                    {" · "}
                    <span>{scores.significance}/10</span>
                    {" · "}
                    <span>{scores.soundness}/10</span>
                    {" · "}
                    <span>{scores.clarity}/10</span>
                    {" · "}
                    <span>{scores.reproducibility}/10</span>
                  </p>
                ) : null}
                {displayStatus !== "running" && judge !== WorkflowNode.conference_judge ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {counts.CRITICAL > 0 ? `${counts.CRITICAL} CRITICAL` : null}
                    {counts.CRITICAL > 0 && counts.MAJOR > 0 ? " " : null}
                    {counts.MAJOR > 0 ? `${counts.MAJOR} MAJOR` : null}
                    {counts.CRITICAL + counts.MAJOR > 0 && counts.MINOR > 0 ? " " : null}
                    {counts.MINOR > 0 ? `${counts.MINOR} MINOR` : null}
                  </p>
                ) : null}
                {canGenerateHead ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-2"
                    onClick={() => void generateJudge(judge)}
                  >
                    {empty ? `Generate ${label}` : `Regenerate ${label}`}
                  </Button>
                ) : null}
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
        {staleDialogJudge ? (
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="judge-stale-reaccept-title"
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          >
            <div className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-lg">
              <h2 id="judge-stale-reaccept-title" className="font-serif text-lg text-navy">
                Stale Workflow Node
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                This Judge was restored from a Stale Stage Revision. Generate again to
                refresh it from upstream, with Stale re-accept.
              </p>
              <div className="mt-4 grid gap-2">
                <Button
                  type="button"
                  onClick={() => void generateJudge(staleDialogJudge, { staleReaccept: true })}
                >
                  Generate
                </Button>
                <Button type="button" variant="ghost" onClick={() => setStaleDialogJudge(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          </div>
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
