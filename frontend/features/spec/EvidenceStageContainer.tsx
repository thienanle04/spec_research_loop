import React, { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  usePatchCardApiLoopSessionsSessionIdCardsCardIdPatch,
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
} from "@/lib/api/generated/endpoints";
import {
  CardKind,
  type ClaimEvidenceCard,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { FileSearch, CheckCircle2, Target, Activity, AlertTriangle, Edit, Save, X } from "lucide-react";

export function EvidenceStageContainer({
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
  const patchCard = usePatchCardApiLoopSessionsSessionIdCardsCardIdPatch();
  const patchWorkingDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const { queue, status } = useLoopSessionSave();
  const saving = status === "saving";
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  
  const claimCards = session.cards.filter(c => c.kind === CardKind.claim);
  const generatedCards = claimCards.map(c => ({ ...(c.body?.metadata as any), id: c.id } as ClaimEvidenceCard & { id: string }));
  const [editCards, setEditCards] = useState<(ClaimEvidenceCard & { id: string })[]>([]);
  
  const narrative = session.working_draft_narrative as any;
  const isSaved = narrative?.evidence_saved === true;
  
  const running = saving || patchCard.isPending || patchWorkingDraft.isPending;

  useEffect(() => {
    onRunningChange?.(running);
    return () => onRunningChange?.(false);
  }, [onRunningChange, running]);

  useEffect(() => {
    onConfirmabilityChange?.(isSaved && generatedCards.length > 0);
    return () => onConfirmabilityChange?.(false);
  }, [isSaved, generatedCards.length, onConfirmabilityChange]);

  function currentSession(): LoopSessionResponse {
    const cached = queryClient.getQueryData(sessionKey) as any;
    return cached?.status === 200 ? cached.data : session;
  }

  function updateSession(updater: (prev: LoopSessionResponse) => LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, (old: any) => {
      if (old?.status === 200) {
        return { ...old, data: updater(old.data) };
      }
      return old;
    });
  }

  async function markAsVerified() {
    setError(null);
    try {
      const response = await queue.enqueue(() => 
        patchWorkingDraft.mutateAsync({
          sessionId,
          data: {
            node: session.working_draft_node,
            expected_version: currentSession().version,
            narrative: { ...narrative, evidence_saved: true }
          }
        })
      );
      if (response.status === 200) {
         updateSession(curr => ({ ...curr, version: response.data.version, working_draft_narrative: { ...curr.working_draft_narrative as any, evidence_saved: true }}));
      } else {
         throw new Error("Could not update working draft");
      }
    } catch (e) {
      setError(getApiErrorMessage(e));
    }
  }

  async function saveEdits() {
    if (editCards.length === 0) return;
    setError(null);
    try {
      let latestVersion = currentSession().version;
      const patchedCards: any[] = [];
      for (const card of editCards) {
        const bodyText = `Claim: ${card.claim}\nBaseline: ${card.baseline}\nMetric: ${card.metric}\nEvidence: ${card.evidence}\nRejection Condition: ${card.rejection_condition}`;
        const metadata = { ...card };
        // don't save DB id into metadata
        delete (metadata as any).id;
        
        const response = await queue.enqueue(() =>
          patchCard.mutateAsync({
            sessionId,
            cardId: card.id,
            data: {
              body: { text: bodyText, metadata },
              expected_version: latestVersion,
            },
          })
        );
        if (response.status !== 200) throw new Error("Could not update the Evidence Card");
        latestVersion = response.data.version;
        patchedCards.push(response.data);
      }
      
      updateSession((current) => {
        const newCardsList = current.cards.map(c => {
          const patched = patchedCards.find(p => p.id === c.id);
          return patched ? patched : c;
        });
        return {
          ...current,
          version: latestVersion,
          working_draft_narrative: { ...current.working_draft_narrative as object, evidence_saved: true },
          cards: newCardsList,
        };
      });
      setIsEditing(false);
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  function startEditing() {
    setEditCards(JSON.parse(JSON.stringify(generatedCards)));
    setIsEditing(true);
  }

  function updateEditCard(index: number, field: keyof ClaimEvidenceCard, value: string) {
    const newCards = [...editCards];
    newCards[index] = { ...newCards[index], [field]: value };
    setEditCards(newCards);
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <CardTitle className="text-xl font-serif text-navy flex items-center gap-2">
              <FileSearch className="w-5 h-5 text-indigo-600" /> Evidence Planning
            </CardTitle>
            <CardDescription>
              Review and refine the evidence, baselines, and metrics for your claims.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="grid gap-5">
        {error ? (
          <div className="p-4 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> {error}
          </div>
        ) : null}

        {generatedCards.length === 0 && !isEditing ? (
          <div className="p-4 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> No claims found. Please go back to the Claims stage to generate them.
          </div>
        ) : null}

        {isEditing ? (
          <div className="space-y-6">
            {editCards.map((card, idx) => (
              <div key={idx} className="bg-slate-50 border rounded-lg shadow-sm p-4 relative">
                <h4 className="flex items-start gap-2 font-semibold text-slate-800 text-base leading-snug mb-4">
                  <span className="bg-indigo-100 text-indigo-700 w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0 mt-0.5">{idx + 1}</span>
                  {card.claim}
                </h4>
                <div className="grid gap-4 mt-2 pr-2">
                  <div className="grid md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-sm font-semibold text-slate-700">Baseline</label>
                      <Textarea 
                        value={card.baseline} 
                        onChange={(e) => updateEditCard(idx, "baseline", e.target.value)} 
                        rows={1} 
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-sm font-semibold text-slate-700">Metric</label>
                      <Textarea 
                        value={card.metric} 
                        onChange={(e) => updateEditCard(idx, "metric", e.target.value)} 
                        rows={1} 
                      />
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-slate-700">Expected Evidence</label>
                    <Textarea 
                      value={card.evidence} 
                      onChange={(e) => updateEditCard(idx, "evidence", e.target.value)} 
                      rows={2} 
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-slate-700">Rejection Condition</label>
                    <Textarea 
                      value={card.rejection_condition} 
                      onChange={(e) => updateEditCard(idx, "rejection_condition", e.target.value)} 
                      rows={2} 
                    />
                  </div>
                </div>
              </div>
            ))}
            <div className="flex justify-end items-center pt-2">
              <div className="flex gap-2">
                <Button type="button" variant="ghost" onClick={() => setIsEditing(false)}>
                  <X className="w-4 h-4 mr-2" /> Cancel
                </Button>
                <Button type="button" variant="default" onClick={saveEdits} disabled={running}>
                  <Save className="w-4 h-4 mr-2" /> Save Edits
                </Button>
              </div>
            </div>
          </div>
        ) : generatedCards.length > 0 && (
          <div className="space-y-6">
            {generatedCards.map((card, idx) => (
              <div key={idx} className="bg-white border rounded-lg shadow-sm overflow-hidden">
                <div className="bg-indigo-50/50 border-b px-5 py-4">
                  <h4 className="flex items-start gap-2 font-semibold text-slate-800 text-base leading-snug">
                    <span className="bg-indigo-100 text-indigo-700 w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0 mt-0.5">{idx + 1}</span>
                    {card.claim}
                  </h4>
                </div>
                <div className="p-5 space-y-4">
                  <div className="grid md:grid-cols-2 gap-4">
                    <div className="bg-slate-50/80 p-3 rounded-md border border-slate-100 flex items-start gap-2">
                      <Target className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                      <div>
                        <span className="block text-xs uppercase font-semibold text-slate-500 mb-0.5">Baseline</span>
                        <span className="text-sm text-slate-700">{card.baseline}</span>
                      </div>
                    </div>
                    <div className="bg-slate-50/80 p-3 rounded-md border border-slate-100 flex items-start gap-2">
                      <Activity className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                      <div>
                        <span className="block text-xs uppercase font-semibold text-slate-500 mb-0.5">Metric</span>
                        <span className="text-sm text-slate-700">{card.metric}</span>
                      </div>
                    </div>
                  </div>
                  
                  <div className="bg-emerald-50/50 p-4 rounded-md border border-emerald-100">
                    <h5 className="text-xs uppercase tracking-wider font-semibold text-emerald-700 mb-1.5 flex items-center gap-1.5">
                      <FileSearch className="w-3.5 h-3.5" /> Expected Evidence
                    </h5>
                    <p className="text-sm text-emerald-900/80">{card.evidence}</p>
                  </div>
                  
                  <div className="bg-amber-50/50 p-4 rounded-md border border-amber-100 flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                    <div>
                      <h5 className="text-xs uppercase tracking-wider font-semibold text-amber-700 mb-0.5">
                        Rejection Condition (Reject if...)
                      </h5>
                      <p className="text-sm text-amber-900/80 italic">{card.rejection_condition}</p>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {isSaved && !isEditing ? (
          <p role="status" className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 p-3 rounded-md flex items-center gap-1.5 mt-4">
            <CheckCircle2 className="w-4 h-4" />
            Evidence has been verified and saved. Confirm at the sidebar when ready.
          </p>
        ) : null}
        
        {generatedCards.length > 0 && !isEditing && (
          <div className="flex gap-2 justify-start pt-2 border-t mt-4">
            <Button
              type="button"
              variant="outline"
              disabled={running}
              onClick={startEditing}
            >
              <Edit className="w-4 h-4 mr-2" /> Edit Evidence
            </Button>
            {!isSaved && (
              <Button
                type="button"
                variant="default"
                disabled={running}
                onClick={markAsVerified}
              >
                Mark as Verified
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
