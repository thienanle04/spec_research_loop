import React, { useEffect, useRef, useState } from "react";
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
  WorkflowNode,
} from "@/lib/api/generated/model";
import { WORKFLOW_NODE_LABELS } from "../loop/catalog";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { withGeneratedSincePrepare } from "../loop/stage-signals";
import { CheckCircle2, AlertTriangle, Edit, Plus, Trash2, Save, X, Target, Activity, FileSearch, FileText } from "lucide-react";

function FormattedText({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="space-y-2">
      {text.split("\n").filter(l => l.trim().length > 0).map((line, lineIndex) => {
        const trimmed = line.trim();
        const bulletMatch = trimmed.match(/^[-*]\s+(.*)$/);
        const numberMatch = trimmed.match(/^(\d+\.)\s+(.*)$/);

        let prefix = null;
        let contentStr = trimmed;

        if (bulletMatch) {
          prefix = <span className="text-slate-400 font-bold w-4 inline-block mt-0.5 shrink-0">•</span>;
          contentStr = bulletMatch[1];
        } else if (numberMatch) {
          prefix = <span className="text-slate-500 font-medium w-6 inline-block shrink-0 mt-0.5">{numberMatch[1]}</span>;
          contentStr = numberMatch[2];
        }

        const strongRegex = /\*\*(.*?)\*\*/g;
        const parts = contentStr.split(strongRegex);
        const content = parts.map((part, partIndex) =>
          partIndex % 2 === 1 ? <strong key={partIndex} className="font-semibold text-foreground">{part}</strong> : part
        );

        if (prefix) {
          return (
            <div key={lineIndex} className="flex items-start gap-1">
              {prefix}
              <div className="flex-1 leading-relaxed">{content}</div>
            </div>
          );
        }

        return (
          <p key={lineIndex} className="leading-relaxed">
            {content}
          </p>
        );
      })}
    </div>
  );
}

export function ClaimsStageContainer({
  sessionId,
  session,
  onRunningChange,
  onConfirmabilityChange,
  generateRequestId = 0,
}: {
  sessionId: string;
  session: LoopSessionResponse;
  onRunningChange?: (running: boolean) => void;
  onConfirmabilityChange?: (confirmable: boolean) => void;
  generateRequestId?: number;
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
  const seenGenerateRequestIdRef = useRef(generateRequestId);

  const narrative = session.working_draft_narrative as any;
  const generatedCards = (narrative?.cards || []) as ClaimEvidenceCard[];
  const isSaved = narrative?.saved === true;
  const confirmedClaimCards = session.cards.filter(c => c.kind === CardKind.claim);
  const confirmedEvidenceCards = session.cards.filter(c => c.kind === CardKind.evidence);

  const running = generateClaims.isPending || saving;

  useEffect(() => {
    onRunningChange?.(running);
    return () => onRunningChange?.(false);
  }, [onRunningChange, running]);

  useEffect(() => {
    onConfirmabilityChange?.(confirmedClaimCards.length > 0 && confirmedEvidenceCards.length > 0);
    return () => onConfirmabilityChange?.(false);
  }, [confirmedClaimCards.length, confirmedEvidenceCards.length, onConfirmabilityChange]);

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
      updateSession((current) =>
        withGeneratedSincePrepare({
          ...current,
          version: response.data.version,
          working_draft_narrative: { ...current.working_draft_narrative as object, cards: response.data.cards, saved: false },
        }),
      );
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  useEffect(() => {
    const previous = seenGenerateRequestIdRef.current;
    seenGenerateRequestIdRef.current = generateRequestId;
    if (generateRequestId < 1 || generateRequestId <= previous) return;
    void loadClaims();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- external stale-dialog trigger only
  }, [generateRequestId]);

  async function saveSelection() {
    if (generatedCards.length === 0) return;
    setError(null);
    try {
      let latestVersion = currentSession().version;
      const claimBodies = generatedCards.map(card => {
        const bodyText = `Claim: ${card.claim}\nBaseline: ${card.baseline}\nMetric: ${card.metric}\nRejection Condition: ${card.rejection_condition}`;
        return { text: bodyText, metadata: card };
      });
      const evidenceBodies = generatedCards.map(card => {
        return { text: card.evidence, metadata: { source_claim_id: card.id } };
      });
      const claimResponse = await queue.enqueue(() =>
        replaceCards.mutateAsync({
          sessionId,
          data: {
            kind: CardKind.claim,
            bodies: claimBodies,
            expected_version: latestVersion,
          },
        })
      );
      if (claimResponse.status !== 200) throw new Error("Could not save the Claim Cards");
      latestVersion = claimResponse.data.version;
      const evidenceResponse = await queue.enqueue(() =>
        replaceCards.mutateAsync({
          sessionId,
          data: {
            kind: CardKind.evidence,
            bodies: evidenceBodies,
            expected_version: latestVersion,
          },
        })
      );
      if (evidenceResponse.status !== 200) throw new Error("Could not save the Evidence Cards");
      latestVersion = evidenceResponse.data.version;
      const savedClaims = claimResponse.data.cards;
      const savedEvidence = evidenceResponse.data.cards;

      updateSession((current) => ({
        ...current,
        version: latestVersion,
        working_draft_narrative: { ...current.working_draft_narrative as object, saved: true },
        cards: [
          ...current.cards.filter(c => c.kind !== CardKind.claim && c.kind !== CardKind.evidence),
          ...savedClaims,
          ...savedEvidence,
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
              {WORKFLOW_NODE_LABELS[WorkflowNode.claims]}
            </CardTitle>
            <CardDescription>
              Generate claims and expected evidence to support your contribution.
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
                <div className="bg-slate-50 border-b px-5 py-3">
                  <h4 className="flex items-start gap-2 font-semibold text-slate-800 text-sm">
                    <FileText className="w-4 h-4 text-slate-500 mt-0.5 shrink-0" />
                    <span className="leading-snug">{card.claim}</span>
                  </h4>
                </div>
                <div className="p-6 space-y-6">
                  <div className="grid md:grid-cols-2 gap-6 items-stretch">
                    <div className="flex min-h-0 flex-col">
                      <h5 className="text-xs uppercase tracking-wider font-bold text-slate-500 mb-2.5 flex items-center gap-1.5">
                        <Target className="w-4 h-4 text-indigo-500" /> Baseline
                      </h5>
                      <div className="flex-1 text-sm text-slate-800 bg-indigo-50/40 p-4 rounded-md border border-indigo-100/60 shadow-sm">
                        <FormattedText text={card.baseline} />
                      </div>
                    </div>
                    <div className="flex min-h-0 flex-col">
                      <h5 className="text-xs uppercase tracking-wider font-bold text-slate-500 mb-2.5 flex items-center gap-1.5">
                        <Activity className="w-4 h-4 text-indigo-500" /> Metric
                      </h5>
                      <div className="flex-1 text-sm text-slate-800 bg-indigo-50/40 p-4 rounded-md border border-indigo-100/60 shadow-sm">
                        <FormattedText text={card.metric} />
                      </div>
                    </div>
                  </div>

                  <div>
                    <h5 className="text-xs uppercase tracking-wider font-bold text-slate-500 mb-2.5 flex items-center gap-1.5">
                      <FileSearch className="w-4 h-4 text-emerald-500" /> Expected Evidence
                    </h5>
                    <div className="text-sm text-slate-800 bg-emerald-50/40 p-4 rounded-md border border-emerald-100/60 shadow-sm">
                      <FormattedText text={card.evidence} />
                    </div>
                  </div>

                  <div>
                    <h5 className="text-xs uppercase tracking-wider font-bold text-slate-500 mb-2.5 flex items-center gap-1.5">
                      <AlertTriangle className="w-4 h-4 text-amber-500" /> Rejection Condition
                    </h5>
                    <div className="text-sm text-slate-800 bg-amber-50/40 p-4 rounded-md border border-amber-100/60 shadow-sm">
                      <FormattedText text={card.rejection_condition} />
                    </div>
                  </div>
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
