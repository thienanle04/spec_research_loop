"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { ArrowLeft, ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { GrillingWorkspace, generateIdea, isGrillingNode } from "@/features/idea";
import type { GrillingAnswer } from "@/features/idea";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  getListDecisionsApiLoopSessionsSessionIdDecisionsGetQueryKey,
  getListSessionsApiLoopSessionsGetQueryKey,
  useConfirmApiLoopSessionsSessionIdConfirmPost,
  useGetSessionApiLoopSessionsSessionIdGet,
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
  useRecomputePrepareApiLoopSessionsSessionIdRecomputePreparePost,
} from "@/lib/api/generated/endpoints";
import {
  LoopStage,
  NodeHeadStatus,
  WorkflowNode,
  type LoopSessionResponse,
  type NodeHeadResponse,
  type OperationalError,
} from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";
import {
  ContributionStageContainer,
  ResearchStageContainer,
} from "@/features/research";
import { JudgementStageContainer, ReadinessStageView } from "@/features/judgement";
import { ClaimsStageContainer } from "@/features/spec/ClaimsStageContainer";
import { EvidenceStageContainer } from "@/features/spec/EvidenceStageContainer";
import { ExperimentPlanStageContainer } from "@/features/spec/ExperimentPlanStageContainer";
import { FeasibilityStageContainer } from "@/features/spec/FeasibilityStageContainer";

import {
  LOOP_STAGE_CATALOG,
  WORKFLOW_NODE_LABELS,
  adjacentStop,
  ancestors,
  catalogStage,
  railStop,
  resolveSelectedNode,
  resolveSelectedStage,
  sessionHref,
  stageForWorkflowNode,
  stagePathNodes,
  workingDraftStop,
  type NavStop,
} from "./catalog";
import { HeadRevisionView } from "./HeadRevisionView";
import { LoopSessionTitleEditor } from "./LoopSessionTitleEditor";
import { ProducedSpecVersionView } from "./ProducedSpecVersionView";
import { SuggestedPatchNotice } from "./SuggestedPatchNotice";
import { WorkingDraftCardCanvas } from "./WorkingDraftCardCanvas";
import { WorkingDraftNarrativeEditor } from "./WorkingDraftNarrativeEditor";
import { LoopSessionSaveProvider, useLoopSessionSave } from "./loop-session-save";
import { operationalError } from "./operational-error";
import { LOOP_STAGE_ICONS } from "./stage-icons";
import {
  deriveStageActions,
  deriveStageSignals,
  hasConfirmableWorkingDraft,
  incompleteUpstreamNodes,
  invalidationWaveKey,
  isInvalidationSubjectDismissed,
  needsStaleReaccept,
  shouldAutoPrepare,
  shouldDimStaleContent,
  specInvalidationInView,
  staleInvalidationStages,
  type CompletionSignal,
} from "./stage-signals";

const COMPLETION_LABEL: Record<CompletionSignal, string> = {
  complete: "Complete",
  needs_work: "Needs work",
  stale: "Stale",
  not_evaluated: "Not evaluated",
  blocked: "Blocked",
  ready: "Ready",
};

function completionClass(completion: CompletionSignal): string {
  switch (completion) {
    case "complete":
    case "ready":
      return "text-navy";
    case "stale":
      return "text-pending";
    case "blocked":
      return "text-destructive";
    case "not_evaluated":
      return "text-muted-foreground";
    default:
      return "text-in-progress";
  }
}

function newerSession(
  current: LoopSessionResponse | null,
  candidate: LoopSessionResponse | null,
): LoopSessionResponse | null {
  if (!current) return candidate;
  if (!candidate) return current;
  return candidate.version >= current.version ? candidate : current;
}

type ContinueTarget = {
  stage: LoopStage;
  prepare: boolean;
  node?: WorkflowNode;
};

function isValidSpecVersion(session: LoopSessionResponse): boolean {
  return (
    session.produced_spec_version != null &&
    session.valid_spec_version_id === session.produced_spec_version.id
  );
}

function specDraftContinueTarget(nodeHeads: NodeHeadResponse[]): ContinueTarget {
  const judgeActions = deriveStageActions({
    stage: LoopStage.independent_judges,
    nodeHeads,
  });
  return {
    stage: LoopStage.independent_judges,
    prepare: judgeActions.canStart || judgeActions.canRecompute,
  };
}

function continueTargetAfterConfirm(
  next: LoopSessionResponse,
  confirmedNode: WorkflowNode,
): ContinueTarget | null {
  const currentStage = stageForWorkflowNode(confirmedNode);
  const currentStageNodes = catalogStage(currentStage).nodes as readonly WorkflowNode[];
  const confirmedIndex = currentStageNodes.indexOf(confirmedNode);
  const nextNode = currentStageNodes[confirmedIndex + 1];
  const nextNodeHead = next.node_heads.find((head) => head.node === nextNode);
  if (nextNode && nextNodeHead?.status === NodeHeadStatus.current) {
    return { stage: currentStage, prepare: false, node: nextNode };
  }

  const currentActions = deriveStageActions({
    stage: currentStage,
    nodeHeads: next.node_heads,
  });
  if (currentActions.canStart || currentActions.canRecompute) {
    return { stage: currentStage, prepare: true };
  }

  const currentIndex = LOOP_STAGE_CATALOG.findIndex((stage) => stage.id === currentStage);
  const following = LOOP_STAGE_CATALOG[currentIndex + 1];
  if (!following) return null;
  if (following.nodes.length === 0) {
    return { stage: following.id, prepare: false };
  }
  const followingActions = deriveStageActions({
    stage: following.id,
    nodeHeads: next.node_heads,
  });
  return followingActions.canStart || followingActions.canRecompute
    ? { stage: following.id, prepare: true }
    : null;
}

function transitionMessage(error: OperationalError): string {
  switch (error.code) {
    case "version_conflict":
      return "Another request changed this Loop Session (version conflict). Your current Working Draft was kept.";
    case "upstream_not_current":
      return "Upstream Workflow Nodes are not current. Your current Working Draft was kept.";
    case "stage_already_current":
      return "Every Workflow Node in this Loop Stage is already current. Your current Working Draft was kept.";
    case "invalid_working_draft_target":
      return "Confirm must target the current Working Draft Workflow Node. Your current Working Draft was kept.";
    default:
      return error.detail;
  }
}

function workingDraftMoveError(
  node: WorkflowNode,
  nodeHeads: NodeHeadResponse[],
): OperationalError | null {
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  for (const ancestor of ancestors(node)) {
    if (statusByNode.get(ancestor) !== NodeHeadStatus.current) {
      return {
        code: "upstream_not_current",
        detail: "Upstream Node Heads must be current",
      };
    }
  }
  if (statusByNode.get(node) !== NodeHeadStatus.current) {
    return {
      code: "",
      detail:
        "Working Draft can only move to a current Workflow Node. Your current Working Draft was kept.",
    };
  }
  return null;
}

/** After Confirm with nowhere to advance, park Working Draft on another current node so the confirmed node can show as HeadRevisionView. */
function parkWorkingDraftAfterConfirm(
  session: LoopSessionResponse,
  confirmedNode: WorkflowNode,
): WorkflowNode | null {
  const order = LOOP_STAGE_CATALOG.flatMap((stage) => [...stage.nodes]);
  const candidates = order.filter(
    (node) =>
      node !== confirmedNode && workingDraftMoveError(node, session.node_heads) == null,
  );
  return candidates.length > 0 ? candidates[candidates.length - 1]! : null;
}

function formatStageList(names: string[]): string {
  if (names.length === 1) {
    return names[0];
  }
  if (names.length === 2) {
    return `${names[0]} and ${names[1]}`;
  }
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

export function LoopSessionWorkbench({ sessionId }: { sessionId: string }) {
  return (
    <LoopSessionSaveProvider>
      <LoopSessionWorkbenchView sessionId={sessionId} />
    </LoopSessionSaveProvider>
  );
}

function LoopSessionWorkbenchView({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { queue, status } = useLoopSessionSave();
  const sessionQuery = useGetSessionApiLoopSessionsSessionIdGet(sessionId);
  const prepareMutation = useRecomputePrepareApiLoopSessionsSessionIdRecomputePreparePost();
  const patchWorkingDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const confirmMutation = useConfirmApiLoopSessionsSessionIdConfirmPost();
  const [appliedSession, setAppliedSession] = useState<LoopSessionResponse | null>(null);
  const [transitionError, setTransitionError] = useState<OperationalError | null>(null);
  const [researchRunning, setResearchRunning] = useState(false);
  const prepareAttemptRef = useRef<string | null>(null);
  const [researchConfirmable, setResearchConfirmable] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatePreview, setGeneratePreview] = useState("");
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [grillEditing, setGrillEditing] = useState(false);
  const [grillDirty, setGrillDirty] = useState(false);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [generateRequestId, setGenerateRequestId] = useState(0);
  const [generateRequestNode, setGenerateRequestNode] = useState<WorkflowNode | null>(null);
  /** subject → waveKey dismissed for; cleared implicitly when waveKey changes. */
  const [dismissedBySubject, setDismissedBySubject] = useState<Record<string, string>>({});

  const queriedSession = sessionQuery.data?.status === 200 ? sessionQuery.data.data : null;
  const session = newerSession(queriedSession, appliedSession);
  const selectedStage = session
    ? resolveSelectedStage(searchParams.get("stage"), session.working_draft_node)
    : null;
  const selectedNode =
    session && selectedStage
      ? resolveSelectedNode(selectedStage, searchParams.get("node"), session.working_draft_node)
      : undefined;
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  function expectedVersion(): number {
    const cached = queryClient.getQueryData(sessionKey) as
      | { status: number; data: LoopSessionResponse }
      | undefined;
    if (cached?.status === 200) {
      return cached.data.version;
    }
    return session?.version ?? 1;
  }

  async function applyTransition(
    mutate: (expectedVersion: number) => Promise<{ status: number; data: unknown }>,
  ): Promise<LoopSessionResponse | null> {
    try {
      await queue.flush();
    } catch {
      return null;
    }
    try {
      const response = await queue.enqueue(() => mutate(expectedVersion()));
      if (response.status === 200) {
        queryClient.setQueryData(sessionKey, response);
        await queryClient.invalidateQueries({
          queryKey: getListDecisionsApiLoopSessionsSessionIdDecisionsGetQueryKey(sessionId),
        });
        await queryClient.invalidateQueries({
          queryKey: getListSessionsApiLoopSessionsGetQueryKey(),
        });
        const next = response.data as LoopSessionResponse;
        setAppliedSession(next);
        setTransitionError(null);
        return next;
      }
    } catch (error) {
      const typed = operationalError(error);
      setTransitionError(typed ?? { code: "", detail: getApiErrorMessage(error) });
    }
    return null;
  }

  function hrefForSession(next: LoopSessionResponse): string {
    return sessionHref(sessionId, workingDraftStop(next.working_draft_node));
  }

  useEffect(() => {
    if (!session || !selectedStage) return;
    const canonicalStop =
      selectedStage === LoopStage.independent_judges
        ? { stage: selectedStage }
        : { stage: selectedStage, node: selectedNode };
    const stageMatches = searchParams.get("stage") === selectedStage;
    const nodeMatches = canonicalStop.node
      ? searchParams.get("node") === canonicalStop.node
      : !searchParams.get("node");
    if (stageMatches && nodeMatches) return;
    router.replace(sessionHref(sessionId, canonicalStop), {
      scroll: false,
    });
  }, [router, searchParams, selectedNode, selectedStage, session, sessionId]);

  useEffect(() => {
    if (!session || !selectedStage) return;
    if (
      generating ||
      researchRunning ||
      prepareMutation.isPending ||
      patchWorkingDraft.isPending ||
      confirmMutation.isPending ||
      status === "saving" ||
      status === "failed" ||
      status === "conflict"
    ) {
      return;
    }
    if (
      !shouldAutoPrepare({
        stage: selectedStage,
        selectedNode,
        workingDraftNode: session.working_draft_node,
        nodeHeads: session.node_heads,
      })
    ) {
      return;
    }
    const key = `${session.version}:${selectedStage}:${selectedNode}`;
    if (prepareAttemptRef.current === key) return;
    prepareAttemptRef.current = key;
    const stage = selectedStage;
    void applyTransition((version) =>
      prepareMutation.mutateAsync({
        sessionId,
        data: { stage, expected_version: version },
      }),
    ).then((prepared) => {
      if (prepared) router.replace(hrefForSession(prepared), { scroll: false });
    });
  }, [
    confirmMutation.isPending,
    generating,
    patchWorkingDraft.isPending,
    prepareMutation,
    researchRunning,
    router,
    selectedNode,
    selectedStage,
    session,
    sessionId,
    status,
  ]);

  if (sessionQuery.isLoading) {
    return <p className="text-muted-foreground">Loading Loop Session…</p>;
  }
  if (!session || !selectedStage) {
    return (
      <div role="alert" className="rounded-md border border-destructive bg-card p-4">
        <p>We could not load this Loop Session.</p>
        <Button className="mt-3" variant="outline" onClick={() => sessionQuery.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const selected = catalogStage(selectedStage);
  const workingDraftNode = session.working_draft_node;
  const interpretation = workingDraftNode === WorkflowNode.idea_interpretation;
  const viewingWorkingDraft = selectedNode != null && selectedNode === workingDraftNode;
  const warningStages = viewingWorkingDraft
    ? staleInvalidationStages({
        node: workingDraftNode,
        nodeHeads: session.node_heads,
      })
    : [];
  const editingResearchDraft =
    viewingWorkingDraft &&
    (workingDraftNode === WorkflowNode.research_inputs ||
      workingDraftNode === WorkflowNode.related_work ||
      workingDraftNode === WorkflowNode.gap);
  const editingContributionDraft =
    viewingWorkingDraft && workingDraftNode === WorkflowNode.contribution;
  const editingClaimsDraft =
    viewingWorkingDraft && workingDraftNode === WorkflowNode.claims;
  const editingEvidenceDraft =
    viewingWorkingDraft && workingDraftNode === WorkflowNode.evidence;
  const editingExperimentPlanDraft =
    viewingWorkingDraft && workingDraftNode === WorkflowNode.experiment_plan;
  const editingFeasibilityDraft =
    viewingWorkingDraft && workingDraftNode === WorkflowNode.feasibility;
  const editingJudgementDraft = selectedStage === LoopStage.independent_judges;
  const editingStructuredDraft =
    editingResearchDraft ||
    editingContributionDraft ||
    editingClaimsDraft ||
    editingEvidenceDraft ||
    editingExperimentPlanDraft ||
    editingFeasibilityDraft ||
    editingJudgementDraft;
  const specDraftTarget =
    selectedStage === LoopStage.spec_draft ? specDraftContinueTarget(session.node_heads) : null;
  const availableContinueTarget = specDraftTarget;
  const continuing = prepareMutation.isPending || patchWorkingDraft.isPending;
  const continueDisabled =
    continuing || (selectedStage === LoopStage.spec_draft && !isValidSpecVersion(session));
  const draftConfirmable = editingStructuredDraft
    ? researchConfirmable
    : hasConfirmableWorkingDraft(session);
  const showConfirm =
    viewingWorkingDraft && selected.nodes.length > 0 && draftConfirmable;
  const confirmDisabled =
    generating ||
    grillEditing ||
    grillDirty ||
    status === "saving" ||
    status === "failed" ||
    status === "conflict" ||
    researchRunning ||
    !draftConfirmable;
  const stageAvailable = incompleteUpstreamNodes({
    stage: selectedStage,
    nodeHeads: session.node_heads,
  }).length === 0;
  const viewedHead = selectedNode
    ? session.node_heads.find((head) => head.node === selectedNode)
    : undefined;
  const workingDraftHead = session.node_heads.find((head) => head.node === workingDraftNode);
  const waveKey = invalidationWaveKey(session);
  const viewedNodeStale = viewedHead?.status === NodeHeadStatus.stale;
  const specVersionStale =
    session.produced_spec_version != null &&
    session.valid_spec_version_id !== session.produced_spec_version.id;
  const nodeBannerSubject =
    viewedNodeStale && selectedNode != null ? selectedNode : null;
  const specBannerInView = specInvalidationInView({
    selectedNode,
    selectedStage,
    viewedNodeStale,
    specVersionStale,
  });
  const showNodeInvalidationLine =
    nodeBannerSubject != null &&
    !isInvalidationSubjectDismissed(nodeBannerSubject, waveKey, dismissedBySubject);
  const showSpecInvalidationLine =
    specBannerInView &&
    !isInvalidationSubjectDismissed("spec_draft", waveKey, dismissedBySubject);
  const showInvalidationBanner =
    waveKey !== "" && (showNodeInvalidationLine || showSpecInvalidationLine);
  const dimStaleContent = shouldDimStaleContent(
    viewingWorkingDraft ? workingDraftHead : viewedHead,
    showInvalidationBanner,
  );
  const confirmNeedsReaccept = needsStaleReaccept(workingDraftHead);
  const stagedGenerateRequestId =
    generateRequestNode === workingDraftNode ? generateRequestId : 0;
  const canEditSelected =
    selectedNode != null &&
    selectedNode !== workingDraftNode &&
    workingDraftMoveError(selectedNode, session.node_heads) == null;
  const currentStop: NavStop = { stage: selectedStage, node: selectedNode };
  const previousStop = adjacentStop(currentStop, -1);
  const nextStop = adjacentStop(currentStop, 1);

  function editConfirmedWork(node: WorkflowNode) {
    void applyTransition((version) =>
      patchWorkingDraft.mutateAsync({
        sessionId,
        data: { node, expected_version: version },
      }),
    ).then((patched) => {
      if (patched) router.replace(hrefForSession(patched), { scroll: false });
    });
  }

  function browseTo(stop: NavStop) {
    router.replace(sessionHref(sessionId, stop), { scroll: false });
  }

  async function runGenerate(
    target: LoopSessionResponse,
    payload?: { message?: string; answers?: GrillingAnswer[]; note?: string },
  ) {
    setGenerating(true);
    setGeneratePreview("");
    setGenerateError(null);
    try {
      await queue.flush();
      await generateIdea({
        sessionId,
        expectedVersion: target.version,
        message: payload?.message,
        answers: payload?.answers,
        note: payload?.note,
        onToken: (text) => setGeneratePreview((current) => current + text),
      });
      const refreshed = await sessionQuery.refetch();
      if (refreshed.data?.status === 200) {
        queryClient.setQueryData(sessionKey, refreshed.data);
        setAppliedSession(refreshed.data.data);
      }
    } catch (error) {
      const typed = operationalError(error);
      setGenerateError(typed?.detail ?? getApiErrorMessage(error));
    } finally {
      setGenerating(false);
      setGeneratePreview("");
    }
  }

  function confirmWorkingDraft(options?: { stale_reaccept?: boolean }) {
    if (confirmNeedsReaccept && !options?.stale_reaccept) {
      setConfirmDialogOpen(true);
      return;
    }
    setConfirmDialogOpen(false);
    void applyTransition((version) =>
      confirmMutation.mutateAsync({
        sessionId,
        data: {
          node: workingDraftNode,
          expected_version: version,
          ...(options?.stale_reaccept ? { stale_reaccept: true } : {}),
        },
      }),
    ).then((next) => {
      if (!next) return;
      const target = continueTargetAfterConfirm(next, workingDraftNode);
      if (target) {
        continueWork(target, next.version);
        return;
      }
      const parkAt = parkWorkingDraftAfterConfirm(next, workingDraftNode);
      if (parkAt) {
        const confirmedStop = workingDraftStop(workingDraftNode);
        void applyTransition(() =>
          patchWorkingDraft.mutateAsync({
            sessionId,
            data: { node: parkAt, expected_version: next.version },
          }),
        ).then((patched) => {
          if (patched) {
            router.replace(sessionHref(sessionId, confirmedStop), { scroll: false });
          }
        });
        return;
      }
      router.replace(hrefForSession(next), { scroll: false });
    });
  }

  function confirmDialogGenerate() {
    setConfirmDialogOpen(false);
    if (!isGrillingNode(workingDraftNode)) {
      setGenerateRequestNode(workingDraftNode);
      setGenerateRequestId((current) => current + 1);
      return;
    }
    if (!session) return;
    void runGenerate(session);
  }

  function continueWork(target: ContinueTarget, expectedVersionOverride?: number) {
    const version = () => expectedVersionOverride ?? expectedVersion();
    if (target.node) {
      void applyTransition(() =>
        patchWorkingDraft.mutateAsync({
          sessionId,
          data: { node: target.node, expected_version: version() },
        }),
      ).then((patched) => {
        if (patched) router.replace(hrefForSession(patched), { scroll: false });
      });
      return;
    }
    if (!target.prepare) {
      router.replace(sessionHref(sessionId, { stage: target.stage }), { scroll: false });
      return;
    }
    void applyTransition(() =>
      prepareMutation.mutateAsync({
        sessionId,
        data: { stage: target.stage, expected_version: version() },
      }),
    ).then((prepared) => {
      if (prepared) router.replace(hrefForSession(prepared), { scroll: false });
    });
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 pb-12">
      <header
        aria-label="Loop Session"
        className="flex flex-wrap items-center gap-3 border-b border-border pb-3"
      >
        <Link
          className="text-sm text-in-progress underline-offset-4 hover:underline"
          href="/sessions"
        >
          ← Back to Loop Sessions
        </Link>
        <div className="min-w-0 flex-1">
          <LoopSessionTitleEditor sessionId={sessionId} />
        </div>
      </header>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(13rem,16rem)_minmax(0,1fr)] lg:items-start">
        <aside className="grid gap-4 lg:sticky lg:top-6">
          <nav aria-label="Loop Stages" className="rounded-md border bg-card shadow-sm">
            <ol className="flex gap-2 overflow-x-auto p-2 lg:flex-col lg:overflow-visible">
              {LOOP_STAGE_CATALOG.map((stage, index) => {
                const signals = deriveStageSignals({
                  stage: stage.id,
                  nodeHeads: session.node_heads,
                  workingDraftNode: session.working_draft_node,
                  readinessState: session.readiness?.state,
                });
                const Icon = LOOP_STAGE_ICONS[stage.id];
                const active = stage.id === selectedStage;
                return (
                  <li key={stage.id} className="min-w-44 lg:min-w-0">
                    <Link
                      href={sessionHref(sessionId, railStop(stage.id))}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-start gap-2 rounded-md px-2 py-2",
                        active && "border-l-2 border-navy bg-muted lg:rounded-l-none",
                      )}
                    >
                      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-navy" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-foreground">
                          {index + 1}. {stage.name}
                        </p>
                        <StageSignalSummary signals={signals} />
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ol>
          </nav>
        </aside>

      <div className="grid min-w-0 grid-cols-1 gap-4">
        <StagePathNav
          emptyTabLabel={
            selectedStage === LoopStage.spec_draft ? selected.name : undefined
          }
          nodes={stagePathNodes(selectedStage)}
          nodeHeads={session.node_heads}
          viewedNode={selectedNode}
          previous={previousStop}
          next={nextStop}
          onBrowse={browseTo}
        />
        {showInvalidationBanner ? (
          <div
            role="status"
            className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-pending bg-card p-3"
          >
            <div className="grid gap-1 text-sm text-pending">
              {showNodeInvalidationLine && nodeBannerSubject ? (
                <p>
                  <span className="font-medium">
                    {WORKFLOW_NODE_LABELS[nodeBannerSubject]}
                  </span>{" "}
                  is Stale. Generate again before Confirm, or use Stale re-accept.
                </p>
              ) : null}
              {showSpecInvalidationLine ? (
                <p>Spec Draft has no Valid Spec Version after upstream invalidation.</p>
              ) : null}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="shrink-0 text-pending hover:bg-pending/10 hover:text-pending"
              onClick={() =>
                setDismissedBySubject((prev) => {
                  const next = { ...prev };
                  if (nodeBannerSubject) {
                    next[nodeBannerSubject] = waveKey;
                  }
                  if (specBannerInView) {
                    next.spec_draft = waveKey;
                  }
                  return next;
                })
              }
            >
              Dismiss
            </Button>
          </div>
        ) : null}
        {transitionError ? (
          <div role="alert" className="rounded-md border border-pending bg-card p-3">
            <p className="text-sm">{transitionMessage(transitionError)}</p>
            {transitionError.code === "version_conflict" ? (
              <Button
                className="mt-3"
                variant="outline"
                onClick={() => {
                  void sessionQuery.refetch().then((refreshed) => {
                    if (refreshed.data?.status === 200) {
                      queryClient.setQueryData(sessionKey, refreshed.data);
                      setAppliedSession(refreshed.data.data);
                      setTransitionError(null);
                    }
                  });
                }}
              >
                Load current Loop Session
              </Button>
            ) : null}
          </div>
        ) : null}
        {viewingWorkingDraft ? (
          <div className={cn(dimStaleContent && "opacity-50")}>
            <SuggestedPatchNotice
              narrative={session.working_draft_narrative as Record<string, unknown>}
            />
            {isGrillingNode(workingDraftNode) ? (
              <GrillingWorkspace
                error={generateError}
                generating={generating}
                locked={generating}
                preview={generatePreview}
                saveBlocked={
                  generating || status === "saving" || status === "failed" || status === "conflict"
                }
                session={session}
                sessionId={sessionId}
                showGenerateCards={workingDraftNode === WorkflowNode.idea_decomposition}
                onEditState={({ editing, dirty }) => {
                  setGrillEditing(editing);
                  setGrillDirty(dirty);
                }}
                onGenerate={(payload) => void runGenerate(session, payload)}
              />
            ) : editingResearchDraft ? (
              <ResearchStageContainer
                key={workingDraftNode}
                sessionId={sessionId}
                session={session}
                generateRequestId={stagedGenerateRequestId}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingContributionDraft ? (
              <ContributionStageContainer
                sessionId={sessionId}
                session={session}
                generateRequestId={stagedGenerateRequestId}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingClaimsDraft ? (
              <ClaimsStageContainer
                sessionId={sessionId}
                session={session}
                generateRequestId={stagedGenerateRequestId}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingEvidenceDraft ? (
              <EvidenceStageContainer
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingExperimentPlanDraft ? (
              <ExperimentPlanStageContainer
                sessionId={sessionId}
                session={session}
                generateRequestId={stagedGenerateRequestId}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingFeasibilityDraft ? (
              <FeasibilityStageContainer
                sessionId={sessionId}
                session={session}
                generateRequestId={stagedGenerateRequestId}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingJudgementDraft ? (
              <JudgementStageContainer
                key={workingDraftNode}
                sessionId={sessionId}
                session={session}
                generateRequestId={stagedGenerateRequestId}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
                onPicked={(next) => {
                  queryClient.setQueryData(sessionKey, { status: 200, data: next });
                  setAppliedSession(next);
                  void queryClient.invalidateQueries({
                    queryKey: getListDecisionsApiLoopSessionsSessionIdDecisionsGetQueryKey(sessionId),
                  });
                  router.replace(hrefForSession(next), { scroll: false });
                }}
              />
            ) : (
              <>
                <WorkingDraftNarrativeEditor locked={generating} sessionId={sessionId} />
                <WorkingDraftCardCanvas locked={generating} sessionId={sessionId} />
              </>
            )}
          </div>
        ) : selectedNode ? (
          <HeadRevisionView
            node={selectedNode}
            status={viewedHead?.status ?? NodeHeadStatus.empty}
            revision={viewedHead?.head_revision ?? null}
            available={stageAvailable}
            dimmed={dimStaleContent}
            upstreamNames={incompleteUpstreamNodes({
              stage: selectedStage,
              nodeHeads: session.node_heads,
            }).map((node) => WORKFLOW_NODE_LABELS[node])}
            onEdit={canEditSelected ? () => editConfirmedWork(selectedNode) : undefined}
            sessionId={sessionId}
            stageRevisionId={viewedHead?.stage_revision_id ?? null}
          />
        ) : null}
        {selectedStage === LoopStage.spec_draft && session.produced_spec_version ? (
          <ProducedSpecVersionView
            produced={session.produced_spec_version}
            validSpecVersionId={session.valid_spec_version_id}
            sessionId={sessionId}
          />
        ) : null}
        {selectedStage === LoopStage.readiness ? (
          <ReadinessStageView session={session} sessionId={sessionId} />
        ) : null}
        {showConfirm || availableContinueTarget ? (
          <div className="grid gap-3 border-t border-border pt-4">
            {showConfirm && warningStages.length > 0 ? (
              <p role="note" className="text-sm text-pending">
                {formatStageList(warningStages.map((stage) => catalogStage(stage).name))} may
                become Stale. Invalidation depends on whether this confirmation changes content.
              </p>
            ) : null}
            {showConfirm ? (
              <Button className="w-full" disabled={confirmDisabled} onClick={() => confirmWorkingDraft()}>
                Confirm
              </Button>
            ) : null}
            {showConfirm && interpretation ? (
              <p className="text-sm text-muted-foreground">
                Unanswered Grilling Questions are not saved as answers.
              </p>
            ) : null}
            {availableContinueTarget ? (
              <Button
                className="w-full"
                disabled={continueDisabled}
                onClick={() => continueWork(availableContinueTarget)}
              >
                Continue
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      </div>
      {confirmDialogOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="stale-reaccept-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-lg">
            <h2 id="stale-reaccept-title" className="font-serif text-lg text-navy">
              Stale Workflow Node
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              This Working Draft was restored from a Stale Stage Revision. Generate again to
              refresh it from upstream, or Confirm anyway as a Stale re-accept.
            </p>
            <div className="mt-4 grid gap-2">
              <Button type="button" disabled={confirmDisabled} onClick={confirmDialogGenerate}>
                Generate
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={confirmDisabled}
                onClick={() => confirmWorkingDraft({ stale_reaccept: true })}
              >
                Confirm anyway
              </Button>
              <Button type="button" variant="ghost" onClick={() => setConfirmDialogOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StageSignalSummary({
  signals,
}: {
  signals: ReturnType<typeof deriveStageSignals>;
}) {
  return (
    <p className={cn("text-xs", completionClass(signals.completion))}>
      {COMPLETION_LABEL[signals.completion]}
      {signals.editing ? " · Editing" : ""}
      {!signals.available ? " · Unavailable" : ""}
    </p>
  );
}

function StagePathNav({
  emptyTabLabel,
  nodes,
  nodeHeads,
  viewedNode,
  previous,
  next,
  onBrowse,
}: {
  emptyTabLabel?: string;
  nodes: readonly WorkflowNode[];
  nodeHeads: NodeHeadResponse[];
  viewedNode: WorkflowNode | undefined;
  previous: NavStop | null;
  next: NavStop | null;
  onBrowse: (stop: NavStop) => void;
}) {
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  const tabs =
    nodes.length > 0
      ? nodes.map((node) => {
          const stale = statusByNode.get(node) === NodeHeadStatus.stale;
          return {
            key: node,
            label: WORKFLOW_NODE_LABELS[node],
            stale,
            selected: viewedNode === node,
            onSelect: () => onBrowse({ stage: stageForWorkflowNode(node), node }),
          };
        })
      : emptyTabLabel
        ? [{ key: emptyTabLabel, label: emptyTabLabel, stale: false, selected: true, onSelect: undefined }]
        : [];

  return (
    <nav
      aria-label="Stage path"
      className="flex flex-wrap items-center gap-x-1"
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Back"
        className="shrink-0"
        disabled={!previous}
        onClick={() => previous && onBrowse(previous)}
      >
        <ArrowLeft aria-hidden="true" />
      </Button>
      {tabs.length > 0 ? (
        <div
          role="tablist"
          aria-label="Workflow Nodes"
          className="flex min-w-0 flex-1 items-center overflow-x-auto"
        >
          {tabs.map((tab) => (
            <Button
              key={tab.key}
              type="button"
              role="tab"
              variant="ghost"
              size="sm"
              aria-selected={tab.selected}
              className={cn(
                "h-auto shrink-0 rounded-none px-3 py-2 text-base shadow-none hover:bg-transparent",
                tab.selected
                  ? "border-b-2 border-navy text-navy hover:text-navy"
                  : "border-b-2 border-transparent text-muted-foreground hover:text-navy",
                tab.stale && "font-medium text-pending hover:text-pending",
                tab.stale && tab.selected && "border-pending",
              )}
              onClick={tab.onSelect}
            >
              <span className="inline-flex items-center gap-1.5">
                {tab.label}
                {tab.stale ? <span className="text-xs uppercase tracking-wide">Stale</span> : null}
              </span>
            </Button>
          ))}
        </div>
      ) : (
        <div className="min-w-0 flex-1" />
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Next"
        className="shrink-0"
        disabled={!next}
        onClick={() => next && onBrowse(next)}
      >
        <ArrowRight aria-hidden="true" />
      </Button>
    </nav>
  );
}
