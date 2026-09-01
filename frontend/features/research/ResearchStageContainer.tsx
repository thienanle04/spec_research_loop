"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getApiErrorMessage } from "@/lib/api/config";
import { customFetch } from "@/lib/api/mutator";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  getListCitationsApiResearchSessionsSessionIdCitationsGetQueryKey,
  getListFindingsApiResearchSessionsSessionIdFindingsGetQueryKey,
  useCreateCardApiLoopSessionsSessionIdCardsPost,
  useListCitationsApiResearchSessionsSessionIdCitationsGet,
  useListFindingsApiResearchSessionsSessionIdFindingsGet,
  usePatchCardApiLoopSessionsSessionIdCardsCardIdPatch,
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
} from "@/lib/api/generated/endpoints";
import { CardKind, type CitationResponse, type LoopSessionResponse } from "@/lib/api/generated/model";

import { useLoopSessionSave } from "../loop/loop-session-save";
import { ResearchStagePanel } from "./ResearchStagePanel";
import {
  discoveryLeadsFromNarrative,
  gapCandidateFrom,
  gapCandidateFromNarrative,
  isCompleteGap,
  researchInputsFrom,
  toolCoverageFromNarrative,
  type GapCandidate,
  type ResearchStreamEvent,
} from "./types";
import { useResearchStream } from "./useResearchStream";

type SessionQueryData = { status: number; data: LoopSessionResponse; headers?: Headers };
type ListQueryData = { status: number; data: unknown[]; headers?: Headers };

function narrative(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

export function ResearchStageContainer({
  sessionId,
  session,
  onRunningChange,
  onConfirmabilityChange,
}: {
  sessionId: string;
  session: LoopSessionResponse;
  onRunningChange?: (running: boolean) => void;
  onConfirmabilityChange?: (confirmable: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { queue, status } = useLoopSessionSave();
  const stream = useResearchStream();
  const patchWorkingDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const createCard = useCreateCardApiLoopSessionsSessionIdCardsPost();
  const patchCard = usePatchCardApiLoopSessionsSessionIdCardsCardIdPatch();
  const researchNode = session.working_draft_node;
  const readsEnabled = researchNode === "related_work" || researchNode === "gap";
  const citationsQuery = useListCitationsApiResearchSessionsSessionIdCitationsGet(sessionId, {
    query: { enabled: readsEnabled },
  });
  const findingsQuery = useListFindingsApiResearchSessionsSessionIdFindingsGet(sessionId, {
    query: { enabled: readsEnabled },
  });
  const [inputs, setInputs] = useState(() => researchInputsFrom(narrative(session.working_draft_narrative)));
  const [partialCitations, setPartialCitations] = useState<CitationResponse[]>([]);
  const [generatedGapCandidate, setGeneratedGapCandidate] = useState<GapCandidate | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [pinningCitationId, setPinningCitationId] = useState<string | null>(null);
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  useEffect(() => {
    if (researchNode === "research_inputs" && status !== "saving") {
      setInputs(researchInputsFrom(narrative(session.working_draft_narrative)));
    }
  }, [researchNode, session.working_draft_narrative, status]);

  useEffect(() => {
    onRunningChange?.(stream.running);
    return () => onRunningChange?.(false);
  }, [onRunningChange, stream.running]);

  const listedCitations = citationsQuery.data?.status === 200 ? citationsQuery.data.data : [];
  const citations = useMemo(() => {
    const byId = new Map(listedCitations.map((item) => [item.id, item]));
    for (const item of partialCitations) byId.set(item.id, item);
    return [...byId.values()];
  }, [listedCitations, partialCitations]);
  const findings = findingsQuery.data?.status === 200 ? findingsQuery.data.data : [];
  const currentNarrative = narrative(session.working_draft_narrative);
  const discoveryLeads = discoveryLeadsFromNarrative(currentNarrative);
  const toolCoverage = toolCoverageFromNarrative(currentNarrative);
  const gapCandidate = gapCandidateFromNarrative(currentNarrative);
  const gapCard = session.cards.find((card) => card.kind === CardKind.gap);
  const selectedGap = gapCandidateFrom(gapCard?.body);
  const displayedGapCandidate = generatedGapCandidate ?? gapCandidate;
  const displayedSelectedGap = generatedGapCandidate ? null : selectedGap;
  const hasPreferredSource = Object.values(inputs.preferred_sources).some(Boolean);
  const confirmable =
    researchNode === "research_inputs"
      ? inputs.keywords.length > 0 && hasPreferredSource
      : researchNode === "related_work"
        ? citations.length > 0 &&
          findings.length > 0 &&
          findings.every((finding) => citations.some((citation) => citation.id === finding.citation_id))
        : Boolean(selectedGap?.statement.trim());

  useEffect(() => {
    onConfirmabilityChange?.(confirmable);
    return () => onConfirmabilityChange?.(false);
  }, [confirmable, onConfirmabilityChange]);

  function expectedVersion(): number {
    const cached = queryClient.getQueryData(sessionKey) as SessionQueryData | undefined;
    return cached?.status === 200 ? cached.data.version : session.version;
  }

  function updateSession(update: (current: LoopSessionResponse) => LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, (current: SessionQueryData | undefined) => {
      if (!current || current.status !== 200) return current;
      return { ...current, data: update(current.data) };
    });
  }

  function setVersion(version: number) {
    updateSession((current) => ({ ...current, version }));
  }

  function clearRegeneratedWorkingSet() {
    if (researchNode === "related_work") {
      setPartialCitations([]);
      for (const queryKey of [
        getListCitationsApiResearchSessionsSessionIdCitationsGetQueryKey(sessionId),
        getListFindingsApiResearchSessionsSessionIdFindingsGetQueryKey(sessionId),
      ]) {
        queryClient.setQueryData(queryKey, (current: ListQueryData | undefined) =>
          current?.status === 200 ? { ...current, data: [] } : current,
        );
      }
    } else if (researchNode === "gap") {
      setGeneratedGapCandidate(null);
      updateSession((current) => ({
        ...current,
        working_draft_narrative: {},
        cards: current.cards.filter((card) => card.kind !== CardKind.gap),
      }));
    }
  }

  function handleInputsChange(next: typeof inputs) {
    setInputs(next);
    setSaveError(null);
    void queue
      .schedule(async () => {
        try {
          const response = await patchWorkingDraft.mutateAsync({
            sessionId,
            data: { expected_version: expectedVersion(), narrative: next },
          });
          if (response.status === 200) queryClient.setQueryData(sessionKey, response);
          return response;
        } catch (error) {
          setSaveError(getApiErrorMessage(error));
          throw error;
        }
      }, 400)
      .catch(() => undefined);
  }

  async function refreshResearchData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: sessionKey }),
      queryClient.invalidateQueries({
        queryKey: getListCitationsApiResearchSessionsSessionIdCitationsGetQueryKey(sessionId),
      }),
      queryClient.invalidateQueries({
        queryKey: getListFindingsApiResearchSessionsSessionIdFindingsGetQueryKey(sessionId),
      }),
    ]);
    setPartialCitations([]);
  }

  function handleStreamEvent(event: ResearchStreamEvent) {
    if (event.type === "citation_upsert") {
      setPartialCitations((current) => {
        const without = current.filter((item) => item.id !== event.citation.id);
        return [...without, event.citation];
      });
    } else if (event.type === "draft_patch") {
      if (event.node === "research_inputs") setInputs(researchInputsFrom(event.narrative));
      if (event.node === "gap") {
        setGeneratedGapCandidate(gapCandidateFromNarrative(event.narrative));
      }
      updateSession((current) => ({ ...current, working_draft_narrative: event.narrative }));
    } else if (event.type === "done") {
      setVersion(event.version);
    }
  }

  async function generate() {
    setSaveError(null);
    try {
      await queue.flush();
      clearRegeneratedWorkingSet();
      await stream.start({
        sessionId,
        node: researchNode as "research_inputs" | "related_work" | "gap",
        expectedVersion: expectedVersion(),
        onEvent: handleStreamEvent,
      });
      await refreshResearchData();
    } catch (error) {
      setSaveError(getApiErrorMessage(error));
    }
  }

  async function selectGap(candidate: GapCandidate) {
    setSaveError(null);
    const candidateToSave: GapCandidate = isCompleteGap(candidate)
      ? candidate
      : { ...candidate, status: "insufficient_evidence" };
    try {
      const response = await queue.enqueue(async () => {
        const version = expectedVersion();
        return gapCard
          ? patchCard.mutateAsync({
              sessionId,
              cardId: gapCard.id,
              data: { expected_version: version, body: candidateToSave },
            })
          : createCard.mutateAsync({
              sessionId,
              data: {
                expected_version: version,
                kind: CardKind.gap,
                body: candidateToSave,
              },
            });
      });
      if (response.status === 200 || response.status === 201) {
        const card = response.data;
        setGeneratedGapCandidate(null);
        updateSession((current) => ({
          ...current,
          version: card.version,
          cards: [
            ...current.cards.filter((item) => item.id !== card.id),
            {
              id: card.id,
              kind: card.kind,
              body: card.body,
              created_at: card.created_at,
              updated_at: card.updated_at,
            },
          ],
        }));
      }
    } catch (error) {
      setSaveError(getApiErrorMessage(error));
    }
  }

  async function toggleCitationPin(citation: CitationResponse) {
    const pinned = Boolean((citation as CitationResponse & { pinned?: boolean }).pinned);
    setPinningCitationId(citation.id);
    setSaveError(null);
    try {
      await customFetch(
        `/api/research/sessions/${sessionId}/citations/${citation.id}/selection`,
        {
          method: "PATCH",
          body: JSON.stringify({ pinned: !pinned }),
        },
      );
      await queryClient.invalidateQueries({
        queryKey: getListCitationsApiResearchSessionsSessionIdCitationsGetQueryKey(sessionId),
      });
    } catch (error) {
      setSaveError(getApiErrorMessage(error));
    } finally {
      setPinningCitationId(null);
    }
  }

  return (
    <ResearchStagePanel
      node={researchNode}
      inputs={inputs}
      citations={citations}
      findings={findings}
      discoveryLeads={discoveryLeads}
      toolCoverage={toolCoverage}
      gapCandidate={displayedGapCandidate}
      selectedGap={displayedSelectedGap}
      running={stream.running}
      progress={stream.progress}
      progressMessage={stream.progressMessage}
      warnings={stream.warnings}
      error={stream.error}
      saveError={saveError}
      disabled={status === "conflict" || status === "failed"}
      onInputsChange={handleInputsChange}
      onGenerate={() => void generate()}
      onAbort={stream.abort}
      pinningCitationId={pinningCitationId}
      onToggleCitationPin={(citation) => void toggleCitationPin(citation)}
      onSelectGap={selectGap}
    />
  );
}
