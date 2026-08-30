"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiErrorMessage } from "@/lib/api/config";
import type { LoopSessionResponse } from "@/lib/api/generated/model";
import { customFetch } from "@/lib/api/mutator";

import { ConferenceScoreList } from "./ConferenceScoreList";
import type { ConferenceScores, ReadinessState } from "./types";

const STATE_LABEL: Record<ReadinessState, string> = {
  not_evaluated: "Not evaluated",
  blocked: "Blocked",
  ready: "Ready",
};

export function ReadinessStageView({
  session,
  sessionId,
}: {
  session: LoopSessionResponse;
  sessionId: string;
}) {
  const readiness = session.readiness;
  const state: ReadinessState = readiness?.state ?? "not_evaluated";
  const notice = readiness?.notice ?? "This is not conference acceptance.";
  const scores = (readiness?.scores ?? null) as ConferenceScores | null;
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportOk, setExportOk] = useState(false);

  async function exportArtifact() {
    setExportError(null);
    setExportOk(false);
    try {
      await customFetch(`/api/loop/sessions/${sessionId}/spec-artifact`, { method: "POST" });
      setExportOk(true);
    } catch (error) {
      setExportError(getApiErrorMessage(error));
    }
  }

  return (
    <section aria-label="Readiness overview">
      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-navy">Readiness</CardTitle>
          <CardDescription>{notice}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <p className="text-sm font-medium">{STATE_LABEL[state]}</p>
          {scores ? <ConferenceScoreList scores={scores} /> : null}
          {state === "ready" ? (
            <Button type="button" className="justify-self-start" onClick={() => void exportArtifact()}>
              Export Spec Artifact
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
              {state === "blocked"
                ? "CRITICAL Judge Issues block Spec Artifact export until they are gone from the current Aggregator Report."
                : "Readiness is derived from the current Aggregator Report."}
            </p>
          )}
          {exportOk ? (
            <p role="status" className="text-sm text-muted-foreground">
              Spec Artifact exported.
            </p>
          ) : null}
          {exportError ? (
            <p role="alert" className="text-sm text-destructive">
              {exportError}
            </p>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}
