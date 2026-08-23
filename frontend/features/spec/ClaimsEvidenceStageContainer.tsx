"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  useCreateCardApiLoopSessionsSessionIdCardsPost,
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  useGenerateClaimsApiSpecSpecSessionsSessionIdClaimsGeneratePost,
} from "@/lib/api/generated/endpoints";
import {
  CardKind,
  type ClaimEvidenceCard,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { MessageSquareQuote, CheckCircle2 } from "lucide-react";

export function ClaimsEvidenceStageContainer({
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
  const generateClaims = useGenerateClaimsApiSpecSpecSessionsSessionIdClaimsGeneratePost();
  const createCard = useCreateCardApiLoopSessionsSessionIdCardsPost();
  const { queue, status } = useLoopSessionSave();
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);
  const saving = status === "saving";

  const [error, setError] = useState<string | null>(null);
  
  const narrative = session.working_draft_narrative as any;
  const generatedCards = (narrative?.cards || []) as ClaimEvidenceCard[];
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

  function updateSession(update: (current: LoopSessionResponse) => LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, (current: any) => {
      if (!current || current.status !== 200) return current;
      return { ...current, data: update(current.data) };
    });
  }

  async function loadClaims() {
    setError(null);
    try {
      const response = await queue.enqueue(() =>
        generateClaims.mutateAsync({
          sessionId,
          data: { expected_version: currentSession().version },
        })
      );
      if (response.status !== 200) throw new Error("Could not generate claims");
      updateSession((current) => ({
        ...current,
        version: response.data.version,
        working_draft_narrative: { cards: response.data.cards },
      }));
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  async function saveSelection() {
    setError(null);
    try {
      for (const card of generatedCards) {
        const bodyText = `Claim: ${card.claim}\nBaseline: ${card.baseline}\nMetric: ${card.metric}\nEvidence: ${card.evidence}\nRejection Condition: ${card.rejection_condition}`;
        const response = await queue.enqueue(() =>
          createCard.mutateAsync({
            sessionId,
            data: {
              kind: CardKind.claim,
              body: { text: bodyText, metadata: card },
              expected_version: currentSession().version,
            },
          })
        );
        if (response.status !== 201) throw new Error("Could not save the Claim Card");
        updateSession((current) => ({
          ...current,
          version: response.data.version,
          cards: [
            ...current.cards,
            response.data,
          ],
        }));
      }
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Claims & Evidence</CardTitle>
        <CardDescription>
          Generate claims and expected evidence to support your contribution.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <Button
          type="button"
          variant="outline"
          className="justify-self-start"
          disabled={saving || running}
          onClick={() => void loadClaims()}
        >
          {generatedCards.length > 0 ? "Regenerate Claims" : "Generate Claims"}
        </Button>

        {generatedCards.length > 0 && (
          <div className="grid gap-4 mt-2">
            {generatedCards.map((card, idx) => (
              <div key={idx} className="bg-slate-50 border border-slate-200 rounded-md p-4">
                <h4 className="flex items-start gap-2 font-bold text-navy mb-2">
                  <MessageSquareQuote className="w-4 h-4 mt-0.5 shrink-0" />
                  {card.claim}
                </h4>
                <div className="grid gap-2 text-sm ml-6">
                  <div className="flex gap-2">
                    <span className="font-semibold text-muted-foreground w-20 shrink-0">Baseline:</span>
                    <span className="text-foreground">{card.baseline}</span>
                  </div>
                  <div className="flex gap-2">
                    <span className="font-semibold text-muted-foreground w-20 shrink-0">Metric:</span>
                    <span className="text-foreground">{card.metric}</span>
                  </div>
                  <div className="flex gap-2">
                    <span className="font-semibold text-muted-foreground w-20 shrink-0">Evidence:</span>
                    <span className="text-foreground">{card.evidence}</span>
                  </div>
                  <div className="flex gap-2 items-start">
                    <span className="font-semibold text-amber-600/80 w-20 shrink-0">Reject if:</span>
                    <span className="text-amber-900/80 italic">{card.rejection_condition}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {confirmedClaimCards.length > 0 ? (
          <p role="status" className="text-sm text-muted-foreground flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4 text-green-600" />
            Saved {confirmedClaimCards.length} Claim Card(s). Confirm when ready.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">{error}</p>
        ) : null}
        <Button
          type="button"
          className="justify-self-start"
          disabled={saving || running || generatedCards.length === 0}
          onClick={() => void saveSelection()}
        >
          Save Claims
        </Button>
      </CardContent>
    </Card>
  );
}
