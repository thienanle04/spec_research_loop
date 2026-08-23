"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  useCreateCardApiLoopSessionsSessionIdCardsPost,
  useGenerateContributionDirectionsApiSpecSessionsSessionIdContributionDirectionsGeneratePost,
} from "@/lib/api/generated/endpoints";
import {
  CardKind,
  ContributionDirectionKind,
  type ContributionDirection,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";

import { useLoopSessionSave } from "../loop/loop-session-save";

type SessionQueryData = { status: number; data: LoopSessionResponse; headers?: Headers };

function directionsFrom(value: unknown): ContributionDirection[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const directions = (value as Record<string, unknown>).directions;
  if (!Array.isArray(directions)) return [];
  return directions.filter(
    (item): item is ContributionDirection =>
      Boolean(
        item &&
          typeof item === "object" &&
          typeof (item as ContributionDirection).id === "string" &&
          typeof (item as ContributionDirection).title === "string" &&
          typeof (item as ContributionDirection).description === "string",
      ),
  );
}

type SessionCard = LoopSessionResponse["cards"][number];

function bodyString(card: SessionCard | undefined, key: string): string {
  if (!card) return "";
  const value = card.body[key];
  return typeof value === "string" ? value : "";
}

function savedSelection(cards: SessionCard[]) {
  const other = cards.find((card) => bodyString(card, "direction_id") === "other");
  if (other) {
    return {
      selectedId: "other",
      primaryId: null,
      secondaryIds: [] as string[],
      otherText: bodyString(other, "text"),
    };
  }
  const primary = cards.find((card) => bodyString(card, "role") === "primary");
  const supporting = cards
    .filter((card) => bodyString(card, "role") === "supporting")
    .map((card) => bodyString(card, "direction_id"))
    .filter(Boolean);
  return {
    selectedId:
      cards.length > 1 || supporting.length > 0
        ? "combine"
        : bodyString(primary ?? cards[0], "direction_id") || null,
    primaryId: bodyString(primary ?? cards[0], "direction_id") || null,
    secondaryIds: supporting,
    otherText: "",
  };
}

export function ContributionStageContainer({
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
  const generateDirections = useGenerateContributionDirectionsApiSpecSessionsSessionIdContributionDirectionsGeneratePost();
  const createCard = useCreateCardApiLoopSessionsSessionIdCardsPost();
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);
  const contributionCards = session.cards.filter((item) => item.kind === CardKind.contribution);
  const restored = savedSelection(contributionCards);
  const [directions, setDirections] = useState(() => directionsFrom(session.working_draft_narrative));
  const [selectedId, setSelectedId] = useState<string | null>(restored.selectedId);
  const [primaryId, setPrimaryId] = useState<string | null>(restored.primaryId);
  const [secondaryIds, setSecondaryIds] = useState<string[]>(restored.secondaryIds);
  const [otherText, setOtherText] = useState(restored.otherText);
  const [error, setError] = useState<string | null>(null);

  const proposed = directions.filter(
    (item) => (item.kind ?? ContributionDirectionKind.proposed) === ContributionDirectionKind.proposed,
  );
  const selected = directions.find((item) => item.id === selectedId) ?? null;
  const saving = status === "saving";
  const running = generateDirections.isPending;

  useEffect(() => {
    setDirections(directionsFrom(session.working_draft_narrative));
    const saved = savedSelection(contributionCards);
    if (contributionCards.length === 0) return;
    setSelectedId(saved.selectedId);
    setPrimaryId(saved.primaryId);
    setSecondaryIds(saved.secondaryIds);
    setOtherText(saved.otherText);
  }, [session.cards, session.working_draft_narrative]);

  useEffect(() => {
    onRunningChange?.(running);
    return () => onRunningChange?.(false);
  }, [onRunningChange, running]);

  useEffect(() => {
    onConfirmabilityChange?.(contributionCards.length > 0);
    return () => onConfirmabilityChange?.(false);
  }, [contributionCards.length, onConfirmabilityChange]);

  function currentSession(): LoopSessionResponse {
    const cached = queryClient.getQueryData(sessionKey) as SessionQueryData | undefined;
    return cached?.status === 200 ? cached.data : session;
  }

  function updateSession(update: (current: LoopSessionResponse) => LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, (current: SessionQueryData | undefined) => {
      if (!current || current.status !== 200) return current;
      return { ...current, data: update(current.data) };
    });
  }

  async function loadDirections() {
    setError(null);
    try {
      const response = await queue.enqueue(() =>
        generateDirections.mutateAsync({
          sessionId,
          data: { expected_version: currentSession().version },
        }),
      );
      if (response.status !== 200) throw new Error("Could not generate contribution directions");
      setDirections(response.data.directions);
      updateSession((current) => ({
        ...current,
        version: response.data.version,
        working_draft_narrative: { directions: response.data.directions },
      }));
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  const saveBodies = useMemo(() => {
    if (!selected) return [];
    if ((selected.kind ?? ContributionDirectionKind.proposed) === ContributionDirectionKind.other) {
      return otherText.trim()
        ? [{ text: otherText.trim(), direction_id: selected.id, role: "primary" }]
        : [];
    }
    if ((selected.kind ?? ContributionDirectionKind.proposed) === ContributionDirectionKind.combine) {
      const primary = proposed.find((item) => item.id === primaryId);
      if (!primary || secondaryIds.length === 0) return [];
      return [
        { text: `${primary.title}. ${primary.description}`, direction_id: primary.id, role: "primary" },
        ...proposed
          .filter((item) => secondaryIds.includes(item.id) && item.id !== primary.id)
          .map((item) => ({
            text: `${item.title}. ${item.description}`,
            direction_id: item.id,
            role: "supporting",
          })),
      ];
    }
    return [{ text: `${selected.title}. ${selected.description}`, direction_id: selected.id, role: "primary" }];
  }, [otherText, primaryId, proposed, secondaryIds, selected]);

  async function saveSelection() {
    setError(null);
    try {
      for (const body of saveBodies) {
        const response = await queue.enqueue(() =>
          createCard.mutateAsync({
            sessionId,
            data: {
              kind: CardKind.contribution,
              body,
              expected_version: currentSession().version,
            },
          }),
        );
        if (response.status !== 201) throw new Error("Could not save the Contribution Card");
        updateSession((current) => ({
          ...current,
          version: response.data.version,
          cards: [
            ...current.cards,
            {
              id: response.data.id,
              kind: response.data.kind,
              body: response.data.body,
              created_at: response.data.created_at,
              updated_at: response.data.updated_at,
            },
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
        <CardTitle>Contribution Direction</CardTitle>
        <CardDescription>
          Choose one direction, combine a primary and supporting contributions, or write another direction.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        {running ? <p role="status" className="text-sm text-muted-foreground">Generating directions from the confirmed Gap…</p> : null}
        <Button
          type="button"
          variant="outline"
          className="justify-self-start"
          disabled={saving || running}
          onClick={() => void loadDirections()}
        >
          {directions.length > 0
            ? "Regenerate contribution directions"
            : "Generate contribution directions"}
        </Button>
        {directions.length > 0 ? (
          <div className="grid gap-3">
            {directions.map((direction, index) => (
              <label key={direction.id} className="flex items-start gap-3 rounded-md border p-4">
                <input
                  className="mt-1"
                  type="radio"
                  name="contribution-direction"
                  checked={selectedId === direction.id}
                  disabled={saving}
                  onChange={() => setSelectedId(direction.id)}
                />
                <span>
                  <strong>{String.fromCharCode(65 + index)}. {direction.title}</strong>
                  <span className="mt-1 block text-sm text-muted-foreground">{direction.description}</span>
                </span>
              </label>
            ))}
          </div>
        ) : null}

        {selected?.kind === ContributionDirectionKind.combine ? (
          <div className="grid gap-4 rounded-md border p-4">
            <fieldset className="grid gap-2">
              <legend className="text-sm font-medium">Primary contribution</legend>
              {proposed.map((item) => (
                <label key={item.id} className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="primary-contribution"
                    checked={primaryId === item.id}
                    onChange={() => {
                      setPrimaryId(item.id);
                      setSecondaryIds((current) => current.filter((id) => id !== item.id));
                    }}
                  />
                  {item.title}
                </label>
              ))}
            </fieldset>
            <fieldset className="grid gap-2">
              <legend className="text-sm font-medium">Supporting contributions</legend>
              {proposed.filter((item) => item.id !== primaryId).map((item) => (
                <label key={item.id} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={secondaryIds.includes(item.id)}
                    onChange={(event) => setSecondaryIds((current) =>
                      event.target.checked ? [...new Set([...current, item.id])] : current.filter((id) => id !== item.id),
                    )}
                  />
                  {item.title}
                </label>
              ))}
            </fieldset>
          </div>
        ) : null}

        {selected?.kind === ContributionDirectionKind.other ? (
          <label className="grid gap-2 text-sm font-medium">
            Other contribution direction
            <Textarea value={otherText} onChange={(event) => setOtherText(event.target.value)} />
          </label>
        ) : null}

        {contributionCards.length > 0 ? (
          <p role="status" className="text-sm text-muted-foreground">
            Saved {contributionCards.length} Contribution Card{contributionCards.length === 1 ? "" : "s"}. Confirm when ready.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">{error}</p>
        ) : null}
        <Button
          type="button"
          className="justify-self-start"
          disabled={saving || running || saveBodies.length === 0}
          onClick={() => void saveSelection()}
        >
          Save contribution direction
        </Button>
      </CardContent>
    </Card>
  );
}
