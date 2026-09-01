"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  patchExportScratchApiLoopSessionsSessionIdExportScratchPatch,
} from "@/lib/api/generated/endpoints";
import type { ExportScratchSection, LoopSessionResponse } from "@/lib/api/generated/model";
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
  const queryClient = useQueryClient();
  const readiness = session.readiness;
  const state: ReadinessState = readiness?.state ?? "not_evaluated";
  const notice = readiness?.notice ?? "This is not conference acceptance.";
  const scores = (readiness?.scores ?? null) as ConferenceScores | null;
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportOk, setExportOk] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sections, setSections] = useState<ExportScratchSection[]>(
    session.export_scratch?.document.sections ?? [],
  );
  const [expectedVersion, setExpectedVersion] = useState(session.version);
  const [scratchError, setScratchError] = useState<string | null>(null);
  const [scratchOk, setScratchOk] = useState(false);

  useEffect(() => {
    setSections(session.export_scratch?.document.sections ?? []);
    setExpectedVersion(session.version);
  }, [session]);

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

  async function saveExportScratch() {
    setScratchError(null);
    setScratchOk(false);
    try {
      const response = await patchExportScratchApiLoopSessionsSessionIdExportScratchPatch(
        sessionId,
        {
          expected_version: expectedVersion,
          document: { sections },
          spec_version_id: session.export_scratch?.spec_version_id,
        },
      );
      if (response.status === 200) {
        const next = response.data;
        setExpectedVersion(next.version);
        setSections(next.export_scratch?.document.sections ?? sections);
        setScratchOk(true);
        await queryClient.invalidateQueries({
          queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        });
      }
    } catch (error) {
      setScratchError(getApiErrorMessage(error));
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
          {sections.length ? (
            <>
              <p role="status" aria-label="Export Scratch overlay" className="text-sm">
                You are editing the Export Scratch, not the Research Spec. Changing the loop still
                means reopen a Workflow Node.
              </p>
              <nav aria-label="Export Scratch">
                <p className="text-sm font-medium">Export Scratch</p>
                <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
                  {sections.map((section) => (
                    <li key={section.id}>{section.title}</li>
                  ))}
                </ol>
              </nav>
              <div className="grid gap-4">
                {sections.map((section, index) => (
                  <label key={section.id} className="grid gap-2 text-sm font-medium">
                    {section.title}
                    <Textarea
                      aria-label={section.title}
                      value={section.body}
                      onChange={(event) => {
                        const next = [...sections];
                        next[index] = { ...section, body: event.target.value };
                        setSections(next);
                      }}
                    />
                  </label>
                ))}
              </div>
              <Button type="button" className="justify-self-start" onClick={() => void saveExportScratch()}>
                Save Export Scratch
              </Button>
              {scratchOk ? (
                <p className="text-sm text-muted-foreground">Export Scratch saved.</p>
              ) : null}
              {scratchError ? (
                <p role="alert" className="text-sm text-destructive">
                  {scratchError}
                </p>
              ) : null}
            </>
          ) : null}
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
            <p role="status" aria-label="Spec Artifact export" className="text-sm text-muted-foreground">
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
