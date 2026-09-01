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
  const [confirmOpen, setConfirmOpen] = useState(false);

  async function exportArtifact(ack: boolean) {
    setExportError(null);
    setExportOk(false);
    try {
      await customFetch(
        `/api/loop/sessions/${sessionId}/spec-artifact`,
        ack
          ? { method: "POST", body: JSON.stringify({ critical_export_ack: true }) }
          : { method: "POST" },
      );
      setConfirmOpen(false);
      setExportOk(true);
    } catch (error) {
      setExportError(getApiErrorMessage(error));
    }
  }

  function onExportClick() {
    setExportError(null);
    setExportOk(false);
    if (state === "blocked") {
      setConfirmOpen(true);
      return;
    }
    void exportArtifact(false);
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
          {state === "ready" || state === "blocked" ? (
            <Button type="button" className="justify-self-start" onClick={onExportClick}>
              Export Spec Artifact
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
              Readiness is derived from the current Aggregator Report.
            </p>
          )}
          {state === "blocked" ? (
            <p className="text-sm text-muted-foreground">
              CRITICAL Judge Issues fail Readiness. Spec Artifact export of the unedited Valid Spec
              Version requires a Critical Export Confirmation.
            </p>
          ) : null}
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
      {confirmOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="critical-export-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-lg">
            <h2 id="critical-export-title" className="font-serif text-lg text-navy">
              Critical Export Confirmation
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Readiness stays blocked. This records a Critical Export Confirmation and exports the
              unedited Valid Spec Version as Spec Artifact JSON.
            </p>
            <div className="mt-4 grid gap-2">
              <Button type="button" onClick={() => void exportArtifact(true)}>
                Confirm export
              </Button>
              <Button type="button" variant="ghost" onClick={() => setConfirmOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
