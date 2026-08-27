"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { GrillingWorkspace, generateIdea, isGrillingNode } from "@/features/idea";
import type { GrillingAnswer } from "@/features/idea";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  getListDecisionsApiLoopSessionsSessionIdDecisionsGetQueryKey,
  getListSessionsApiLoopSessionsGetQueryKey,
  useConfirmApiLoopSessionsSessionIdConfirmPost,
  useGetSessionApiLoopSessionsSessionIdGet,
  useListDecisionsApiLoopSessionsSessionIdDecisionsGet,
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
import { ClaimsEvidenceStageContainer } from "@/features/spec/ClaimsEvidenceStageContainer";
import { ExperimentPlanningStageContainer } from "@/features/spec/ExperimentPlanningStageContainer";

import {
  LOOP_STAGE_CATALOG,
  WORKFLOW_NODE_LABELS,
  ancestors,
  catalogStage,
  resolveSelectedStage,
  stageForWorkflowNode,
} from "./catalog";
import { LoopSessionTitleEditor } from "./LoopSessionTitleEditor";
import { WorkingDraftCardCanvas } from "./WorkingDraftCardCanvas";
import { WorkingDraftNarrativeEditor } from "./WorkingDraftNarrativeEditor";
import { LoopSessionSaveProvider, useLoopSessionSave } from "./loop-session-save";
import { type SaveStatus } from "./mutation-queue";
import { operationalError } from "./operational-error";
import { LOOP_STAGE_ICONS } from "./stage-icons";
import {
  deriveStageActions,
  deriveStageSignals,
  hasConfirmableWorkingDraft,
  incompleteUpstreamNodes,
  staleInvalidationStages,
  type CompletionSignal,
} from "./stage-signals";

const COMPLETION_LABEL: Record<CompletionSignal, string> = {
  complete: "Complete",
  needs_work: "Needs work",
  stale: "Stale",
  not_evaluated: "Not evaluated",
};

const NODE_HEAD_LABEL: Record<NodeHeadStatus, string> = {
  [NodeHeadStatus.empty]: "Empty",
  [NodeHeadStatus.current]: "Current",
  [NodeHeadStatus.stale]: "Stale",
};

const SAVE_STATUS_LABEL: Record<SaveStatus, string | null> = {
  idle: null,
  saving: "Saving…",
  saved: "Saved",
  failed: "Save failed",
  conflict: "Resolve conflict",
};

function completionClass(completion: CompletionSignal): string {
  switch (completion) {
    case "complete":
      return "text-navy";
    case "stale":
      return "text-pending";
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
  const decisionsQuery = useListDecisionsApiLoopSessionsSessionIdDecisionsGet(sessionId);
  const prepareMutation = useRecomputePrepareApiLoopSessionsSessionIdRecomputePreparePost();
  const patchWorkingDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const confirmMutation = useConfirmApiLoopSessionsSessionIdConfirmPost();
  const [appliedSession, setAppliedSession] = useState<LoopSessionResponse | null>(null);
  const [transitionError, setTransitionError] = useState<OperationalError | null>(null);
  const [continueTarget, setContinueTarget] = useState<ContinueTarget | null>(null);
  const [confirmationMessage, setConfirmationMessage] = useState<string | null>(null);
  const [continueWarning, setContinueWarning] = useState<string | null>(null);
  const [researchRunning, setResearchRunning] = useState(false);
  const [researchConfirmable, setResearchConfirmable] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatePreview, setGeneratePreview] = useState("");
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [grillEditing, setGrillEditing] = useState(false);
  const [grillDirty, setGrillDirty] = useState(false);

  const queriedSession = sessionQuery.data?.status === 200 ? sessionQuery.data.data : null;
  const session = newerSession(queriedSession, appliedSession);
  const selectedStage = session
    ? resolveSelectedStage(searchParams.get("stage"), session.working_draft_node)
    : null;

  useEffect(() => {
    if (!session || !selectedStage) return;
    if (searchParams.get("stage") === selectedStage) return;
    router.replace(`/sessions/${sessionId}?stage=${selectedStage}`, { scroll: false });
  }, [router, searchParams, selectedStage, session, sessionId]);

  useEffect(() => {
    setContinueTarget(null);
    setConfirmationMessage(null);
    setContinueWarning(null);
  }, [selectedStage]);

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
  const selectedSignals = deriveStageSignals({
    stage: selectedStage,
    nodeHeads: session.node_heads,
    workingDraftNode: session.working_draft_node,
  });
  const incompleteUpstream = incompleteUpstreamNodes({
    stage: selectedStage,
    nodeHeads: session.node_heads,
  });
  const actions = deriveStageActions({
    stage: selectedStage,
    nodeHeads: session.node_heads,
  });
  const workingDraftNode = session.working_draft_node;
  const interpretation = workingDraftNode === WorkflowNode.idea_interpretation;
  const workingDraftHead = session.node_heads.find((head) => head.node === workingDraftNode);
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);
  const editingWorkingDraft = stageForWorkflowNode(workingDraftNode) === selectedStage;
  const warningStages = editingWorkingDraft
    ? staleInvalidationStages({
        node: workingDraftNode,
        nodeHeads: session.node_heads,
      })
    : [];
  const editingResearchDraft =
    editingWorkingDraft &&
    (workingDraftNode === WorkflowNode.research_inputs ||
      workingDraftNode === WorkflowNode.related_work ||
      workingDraftNode === WorkflowNode.gap);
  const editingContributionDraft =
    editingWorkingDraft && workingDraftNode === WorkflowNode.contribution;
  const editingClaimsDraft =
    editingWorkingDraft && (workingDraftNode === WorkflowNode.claims || workingDraftNode === WorkflowNode.evidence);
  const editingExperimentDraft =
    editingWorkingDraft && (workingDraftNode === WorkflowNode.experiment_plan || workingDraftNode === WorkflowNode.feasibility);
  const editingStructuredDraft = editingResearchDraft || editingContributionDraft || editingClaimsDraft || editingExperimentDraft;
  const decisions =
    decisionsQuery.data?.status === 200 ? decisionsQuery.data.data : [];
  const latestDecision = decisions[decisions.length - 1];
  const workingDraftWasLastConfirmed =
    editingWorkingDraft &&
    workingDraftHead?.status === NodeHeadStatus.current &&
    latestDecision?.kind === "confirm" &&
    latestDecision.node === workingDraftNode &&
    new Date(latestDecision.created_at).getTime() === new Date(session.updated_at).getTime();
  const persistedContinueTarget = workingDraftWasLastConfirmed
    ? continueTargetAfterConfirm(session, workingDraftNode)
    : null;
  const availableContinueTarget = continueTarget ?? persistedContinueTarget;
  const continuing = prepareMutation.isPending || patchWorkingDraft.isPending;
  const draftConfirmable = editingStructuredDraft
    ? researchConfirmable
    : hasConfirmableWorkingDraft(session);
  const showConfirm =
    editingWorkingDraft && selected.nodes.length > 0 && draftConfirmable;
  const confirmDisabled =
    generating ||
    grillEditing ||
    grillDirty ||
    status === "saving" ||
    status === "failed" ||
    status === "conflict" ||
    researchRunning ||
    !draftConfirmable;
  const stageNodes = [...selected.nodes];
  const selectedNode = stageNodes.includes(workingDraftNode)
    ? workingDraftNode
    : stageNodes[0];
  const canEditSelected =
    selectedNode != null &&
    actions.editableNodes.includes(selectedNode) &&
    selectedNode !== workingDraftNode;
  const showStart =
    actions.canStart &&
    !availableContinueTarget &&
    !showConfirm &&
    !(editingWorkingDraft && workingDraftNode === WorkflowNode.idea_decomposition);
  const saveStatusLabel = editingWorkingDraft ? SAVE_STATUS_LABEL[status] : null;

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

  function startOrRecompute() {
    if (!selectedStage) return;
    if (actions.canStart && workingDraftHead?.status !== NodeHeadStatus.current) {
      setContinueWarning(
        "This work has not been confirmed. Select Confirm to save it before continuing.",
      );
      return;
    }
    setContinueWarning(null);
    const stage = selectedStage;
    setConfirmationMessage(null);
    void applyTransition((version) =>
      prepareMutation.mutateAsync({
        sessionId,
        data: { stage, expected_version: version },
      }),
    );
  }

  function editConfirmedWork(node: WorkflowNode) {
    setContinueTarget(null);
    setConfirmationMessage(null);
    setContinueWarning(null);
    void applyTransition((version) =>
      patchWorkingDraft.mutateAsync({
        sessionId,
        data: { node, expected_version: version },
      }),
    );
  }

  function selectWorkingDraftNode(node: WorkflowNode) {
    if (!session) return;
    if (node === workingDraftNode) {
      setTransitionError(null);
      return;
    }
    const blocked = workingDraftMoveError(node, session.node_heads);
    if (blocked) {
      setContinueTarget(null);
      setConfirmationMessage(null);
      setContinueWarning(null);
      setTransitionError(blocked);
      return;
    }
    editConfirmedWork(node);
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

  function confirmWorkingDraft() {
    setContinueWarning(null);
    void applyTransition((version) =>
      confirmMutation.mutateAsync({
        sessionId,
        data: { node: workingDraftNode, expected_version: version },
      }),
    ).then((next) => {
      if (!next) return;
      const autoDecompose =
        workingDraftNode === WorkflowNode.idea_interpretation &&
        next.working_draft_node === WorkflowNode.idea_decomposition &&
        next.node_heads.find((head) => head.node === WorkflowNode.idea_decomposition)
          ?.status === NodeHeadStatus.empty;
      if (autoDecompose) {
        setContinueTarget(null);
        setConfirmationMessage(null);
        void runGenerate(next);
        return;
      }
      setContinueTarget(continueTargetAfterConfirm(next, workingDraftNode));
      setConfirmationMessage("Saved. Select Continue to proceed to the next step.");
    });
  }

  function continueWork() {
    if (!availableContinueTarget) return;
    const target = availableContinueTarget;
    setContinueTarget(null);
    setConfirmationMessage(null);
    setContinueWarning(null);
    if (target.node) {
      void applyTransition((version) =>
        patchWorkingDraft.mutateAsync({
          sessionId,
          data: { node: target.node, expected_version: version },
        }),
      ).then((patched) => {
        if (patched) router.replace(`/sessions/${sessionId}?stage=${target.stage}`);
      });
      return;
    }
    if (!target.prepare) {
      router.replace(`/sessions/${sessionId}?stage=${target.stage}`);
      return;
    }
    void applyTransition((version) =>
      prepareMutation.mutateAsync({
        sessionId,
        data: { stage: target.stage, expected_version: version },
      }),
    ).then((prepared) => {
      if (prepared) router.replace(`/sessions/${sessionId}?stage=${target.stage}`);
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
          All Loop Sessions
        </Link>
        <div className="min-w-0 flex-1">
          <LoopSessionTitleEditor sessionId={sessionId} />
        </div>
      </header>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(13rem,16rem)_minmax(0,1fr)_minmax(12rem,16rem)] lg:items-start">
        <aside className="grid gap-4 lg:sticky lg:top-6">
          <p className="text-sm text-muted-foreground">
            Working Draft: {WORKFLOW_NODE_LABELS[session.working_draft_node]}
          </p>
          <nav aria-label="Loop Stages" className="rounded-md border bg-card shadow-sm">
            <ol className="flex gap-2 overflow-x-auto p-2 lg:flex-col lg:overflow-visible">
              {LOOP_STAGE_CATALOG.map((stage, index) => {
                const signals = deriveStageSignals({
                  stage: stage.id,
                  nodeHeads: session.node_heads,
                  workingDraftNode: session.working_draft_node,
                });
                const Icon = LOOP_STAGE_ICONS[stage.id];
                const active = stage.id === selectedStage;
                return (
                  <li key={stage.id} className="min-w-44 lg:min-w-0">
                    <Link
                      href={`/sessions/${sessionId}?stage=${stage.id}`}
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
        {selected.nodes.length > 1 ? (
          <WorkflowNodeTabs
            nodes={selected.nodes}
            nodeHeads={session.node_heads}
            workingDraftNode={workingDraftNode}
            onSelect={selectWorkingDraftNode}
          />
        ) : null}
        {editingWorkingDraft ? (
          <>
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
                showGenerateCards={
                  workingDraftNode === WorkflowNode.idea_decomposition && session.cards.length === 0
                }
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
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingContributionDraft ? (
              <ContributionStageContainer
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingClaimsDraft ? (
              <ClaimsEvidenceStageContainer
                key={workingDraftNode}
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingExperimentDraft ? (
              <ExperimentPlanningStageContainer
                key={workingDraftNode}
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : (
              <>
                <WorkingDraftNarrativeEditor locked={generating} sessionId={sessionId} />
                <WorkingDraftCardCanvas locked={generating} sessionId={sessionId} />
              </>
            )}
          </>
        ) : null}
        <section aria-label={`${selected.name} overview`}>
          <Card>
            <CardHeader>
              <CardTitle className="font-serif text-navy">{selected.name}</CardTitle>
              <CardDescription>{selected.description}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <StageSignalSummary signals={selectedSignals} />
              {selectedStage === LoopStage.readiness ? (
                <p>Not evaluated. Readiness is a criteria check, not a workflow-completion proxy.</p>
              ) : selectedStage === LoopStage.spec_draft ? (
                <p>The Produced Spec Version will appear here after you confirm feasibility.</p>
              ) : (
                <WorkflowNodeList
                  nodes={selected.nodes}
                  nodeHeads={session.node_heads}
                  workingDraftNode={session.working_draft_node}
                />
              )}
              {!selectedSignals.available ? (
                <div>
                  <p className="text-sm font-medium text-destructive">Unavailable</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Upstream Workflow Nodes are not current:
                  </p>
                  <ul className="mt-2 list-disc pl-5 text-sm">
                    {incompleteUpstream.map((node) => (
                      <li key={node}>{WORKFLOW_NODE_LABELS[node]}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </CardContent>
          </Card>
          </section>
        </div>

        <aside
          aria-label="Stage actions"
          className="rounded-md border bg-card p-4 shadow-sm lg:sticky lg:top-6"
        >
          <div className="grid gap-3">
            <p className="text-sm font-medium text-foreground">Stage actions</p>
            {saveStatusLabel ? (
              <p role="status" aria-label="Working Draft save" className="text-sm text-muted-foreground">
                {saveStatusLabel}
              </p>
            ) : null}
            {showConfirm && warningStages.length > 0 ? (
              <p role="note" className="text-sm text-pending">
                {formatStageList(warningStages.map((stage) => catalogStage(stage).name))} may
                become Stale. Invalidation depends on whether this confirmation changes content.
              </p>
            ) : null}
            {showConfirm ? (
              <Button disabled={confirmDisabled} onClick={confirmWorkingDraft}>
                Confirm
              </Button>
            ) : null}
            {showConfirm && interpretation ? (
              <p className="text-sm text-muted-foreground">
                Unanswered Grilling Questions are not saved as answers.
              </p>
            ) : null}
            {confirmationMessage ? (
              <p role="status" className="text-sm text-navy">
                {confirmationMessage}
              </p>
            ) : null}
            {availableContinueTarget ? (
              <Button disabled={continuing} onClick={continueWork}>
                Continue
              </Button>
            ) : null}
            {showStart ? (
              <Button onClick={startOrRecompute}>Start</Button>
            ) : null}
            {actions.canRecompute ? (
              <Button onClick={startOrRecompute}>Recompute</Button>
            ) : null}
            {canEditSelected ? (
              <Button variant="outline" onClick={() => editConfirmedWork(selectedNode)}>
                Edit {WORKFLOW_NODE_LABELS[selectedNode]}
              </Button>
            ) : null}
            {continueWarning ? (
              <div role="alert" className="rounded-md border border-pending bg-card p-3">
                <p className="text-sm">{continueWarning}</p>
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
          </div>
        </aside>
      </div>
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

function WorkflowNodeTabs({
  nodes,
  nodeHeads,
  workingDraftNode,
  onSelect,
}: {
  nodes: readonly WorkflowNode[];
  nodeHeads: NodeHeadResponse[];
  workingDraftNode: WorkflowNode;
  onSelect: (node: WorkflowNode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Workflow Nodes"
      className="flex gap-2 overflow-x-auto rounded-md border bg-card p-2 shadow-sm"
    >
      {nodes.map((node) => {
        const selected = workingDraftNode === node;
        const head = nodeHeads.find((item) => item.node === node);
        const status = head?.status ?? NodeHeadStatus.empty;
        return (
          <Button
            key={node}
            type="button"
            role="tab"
            variant="ghost"
            aria-selected={selected}
            className={cn(
              "h-auto min-w-36 shrink-0 flex-col items-start px-3 py-2 text-left",
              selected && "border-l-2 border-navy bg-muted",
            )}
            onClick={() => onSelect(node)}
          >
            <span className="block text-sm font-medium text-foreground">
              {WORKFLOW_NODE_LABELS[node]}
            </span>
            <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
              {NODE_HEAD_LABEL[status]}
              {selected ? " · Working Draft" : ""}
            </span>
          </Button>
        );
      })}
    </div>
  );
}

function WorkflowNodeList({
  nodes,
  nodeHeads,
  workingDraftNode,
}: {
  nodes: readonly WorkflowNode[];
  nodeHeads: NodeHeadResponse[];
  workingDraftNode: WorkflowNode;
}) {
  return (
    <ol className="grid gap-3">
      {nodes.map((node) => {
        const head = nodeHeads.find((item) => item.node === node);
        const status = head?.status ?? NodeHeadStatus.empty;
        return (
          <li key={node} className="rounded-md border bg-muted/40 px-3 py-2">
            <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p>
            <p className="text-sm text-muted-foreground">
              Node Head: {NODE_HEAD_LABEL[status]}
              {workingDraftNode === node ? " · Working Draft" : ""}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
