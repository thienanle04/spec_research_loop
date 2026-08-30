import React, { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  useReplaceCardsApiLoopSessionsSessionIdCardsPut,
  useGenerateClaimsApiSpecSessionsSessionIdClaimsGeneratePost,
} from "@/lib/api/generated/endpoints";
import {
  CardKind,
  type ClaimEvidenceCard,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { MessageSquareQuote, CheckCircle2, AlertTriangle, Edit, Plus, Trash2, Save, X } from "lucide-react";

export function ClaimsStageContainer({
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
  const generateClaims = useGenerateClaimsApiSpecSessionsSessionIdClaimsGeneratePost();
  const replaceCards = useReplaceCardsApiLoopSessionsSessionIdCardsPut();
  const { queue, status } = useLoopSessionSave();
  const saving = status === "saving";
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editCards, setEditCards] = useState<ClaimEvidenceCard[]>([]);

  const narrative = session.working_draft_narrative as any;
  const generatedCards = (narrative?.cards || []) as ClaimEvidenceCard[];
  const isSaved = narrative?.saved === true;
  const confirmedClaimCards = session.cards.filter(c => c.kind === CardKind.claim);

  const running = generateClaims.isPending || saving;

  useEffect(() => {
    onRunningChange?.(running);
    return () => onRunningChange?.(false);
  }, [onRunningChange, running]);

  useEffect(() => {
    onConfirmabilityChange?.(confirmedClaimCards.length > 0);
    return () => onConfirmabilityChange?.(false);
  }, [confirmedClaimCards.length, onConfirmabilityChange]);

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

  async function loadClaims() {
    setError(null);
    try {
      const response: any = await queue.enqueue(() =>
        generateClaims.mutateAsync({
          sessionId,
          data: { expected_version: currentSession().version },
        })
      );
      if (response.status !== 200) throw new Error("Could not generate claims");
      updateSession((current) => ({
        ...current,
        version: response.data.version,
        working_draft_narrative: { ...current.working_draft_narrative as object, cards: response.data.cards, saved: false },
      }));
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  async function saveSelection() {
    if (generatedCards.length === 0) return;
    setError(null);
    try {
      let latestVersion = currentSession().version;
      const bodies = generatedCards.map(card => {
        const bodyText = `Claim: ${card.claim}\nBaseline: ${card.baseline}\nMetric: ${card.metric}\nEvidence: ${card.evidence}\nRejection Condition: ${card.rejection_condition}`;
        return { text: bodyText, metadata: card };
      });
      const response = await queue.enqueue(() =>
        replaceCards.mutateAsync({
          sessionId,
          data: {
            kind: CardKind.claim,
            bodies,
            expected_version: latestVersion,
          },
        })
      );
      if (response.status !== 200) throw new Error("Could not save the Claim Cards");
      latestVersion = response.data.version;
      const savedCards = response.data.cards;

      updateSession((current) => ({
        ...current,
        version: latestVersion,
        working_draft_narrative: { ...current.working_draft_narrative as object, saved: true },
        cards: [
          ...current.cards.filter(c => c.kind !== CardKind.claim),
          ...savedCards,
        ],
      }));
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  function startEditing() {
    setEditCards(JSON.parse(JSON.stringify(generatedCards)));
    setIsEditing(true);
  }

  function saveEdits() {
    updateSession((current) => ({
      ...current,
      working_draft_narrative: { ...current.working_draft_narrative as object, cards: editCards, saved: false },
    }));
    setIsEditing(false);
  }

  function addNewClaim() {
    setEditCards([...editCards, { id: "new-" + Math.random().toString(), claim: "", baseline: "", metric: "", evidence: "", rejection_condition: "" } as ClaimEvidenceCard]);
  }

  function updateEditCard(index: number, field: keyof ClaimEvidenceCard, value: string) {
    const newCards = [...editCards];
    newCards[index] = { ...newCards[index], [field]: value };
    setEditCards(newCards);
  }

  function removeEditCard(index: number) {
    setEditCards(editCards.filter((_, i) => i !== index));
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <CardTitle className="text-xl font-serif text-navy flex items-center gap-2">
              <MessageSquareQuote className="w-5 h-5 text-indigo-600" /> Claims Generation
            </CardTitle>
            <CardDescription>
              Generate and review the core claims for your spec.
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="default"
            disabled={saving || running || isEditing}
            onClick={() => void loadClaims()}
          >
            {generatedCards.length > 0 ? "Regenerate Claims" : "Generate Claims"}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="grid gap-5">
        {error ? (
          <div className="p-4 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> {error}
          </div>
        ) : null}

        {isEditing ? (
          <div className="space-y-6">
            {editCards.map((card, idx) => (
              <div key={idx} className="bg-slate-50 border rounded-lg shadow-sm p-4 relative">
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute top-2 right-2 text-slate-400 hover:text-destructive"
                  onClick={() => removeEditCard(idx)}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
                <div className="grid gap-4 mt-2 pr-8">
                  <div className="space-y-1.5">
                    <label className="text-sm font-semibold text-slate-700">Claim</label>
                    <Textarea
                      value={card.claim}
                      onChange={(e) => updateEditCard(idx, "claim", e.target.value)}
                      rows={2}
                    />
                  </div>
                </div>
              </div>
            ))}
            <div className="flex justify-between items-center pt-2">
              <Button type="button" variant="outline" onClick={addNewClaim}>
                <Plus className="w-4 h-4 mr-2" /> Add New Claim
              </Button>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" onClick={() => setIsEditing(false)}>
                  <X className="w-4 h-4 mr-2" /> Cancel
                </Button>
                <Button type="button" variant="default" onClick={saveEdits}>
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
              </div>
            ))}
          </div>
        )}

        {confirmedClaimCards.length > 0 && !isEditing ? (
          <p role="status" className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 p-3 rounded-md flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4" />
            Saved <strong>{confirmedClaimCards.length}</strong> Claim(s) in project context. Confirm at the sidebar when ready.
          </p>
        ) : null}

        {generatedCards.length > 0 && !isEditing && (
          <div className="flex gap-2 justify-start pt-2 border-t mt-4">
            <Button
              type="button"
              variant="default"
              disabled={saving || running || isSaved || generatedCards.length === 0}
              onClick={() => void saveSelection()}
            >
              {isSaved ? "Claims Saved" : "Save Claims"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={startEditing}
            >
              <Edit className="w-4 h-4 mr-2" /> Edit Claims
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
