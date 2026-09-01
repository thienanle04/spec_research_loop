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
import type {
  ExportScratchDiffResponse,
  ExportScratchSection,
  LoopSessionResponse,
} from "@/lib/api/generated/model";
import { customFetch } from "@/lib/api/mutator";

import { ConferenceScoreList } from "./ConferenceScoreList";
import type { ConferenceScores, ReadinessState } from "./types";

const STATE_LABEL: Record<ReadinessState, string> = {
  not_evaluated: "Not evaluated",
  blocked: "Blocked",
  ready: "Ready",
};

type ScratchDiff = ExportScratchDiffResponse;

export function ReadinessStageView({
  session,
  sessionId,
}: {
  session: LoopSessionResponse;
  sessionId: string;
}) {
  const queryClient = useQueryClient();
  const readiness = session.readiness;
  const state: ReadinessState =
    (readiness?.state as ReadinessState | undefined) ?? "not_evaluated";
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
  const specVersions = session.spec_versions ?? [];
  const [selectedSpecId, setSelectedSpecId] = useState(
    session.valid_spec_version_id ?? specVersions[0]?.id ?? "",
  );
  const [viewed, setViewed] = useState(session);
  const [previousDiff, setPreviousDiff] = useState<ScratchDiff | null>(null);
  const [originalDiff, setOriginalDiff] = useState<ScratchDiff | null>(null);

  useEffect(() => {
    setSections(session.export_scratch?.document.sections ?? []);
    setExpectedVersion(session.version);
    setViewed(session);
    setSelectedSpecId(session.valid_spec_version_id ?? session.spec_versions?.[0]?.id ?? "");
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

  async function loadScratchDiffs(specVersionId: string | undefined) {
    if (!specVersionId) {
      setPreviousDiff(null);
      setOriginalDiff(null);
      return;
    }
    try {
      const [previous, original] = await Promise.all([
        customFetch<{ status: number; data: ScratchDiff }>(
          `/api/loop/sessions/${sessionId}/export-scratch/diff?against=previous&spec_version_id=${specVersionId}`,
          { method: "GET" },
        ),
        customFetch<{ status: number; data: ScratchDiff }>(
          `/api/loop/sessions/${sessionId}/export-scratch/diff?against=original&spec_version_id=${specVersionId}`,
          { method: "GET" },
        ),
      ]);
      setPreviousDiff(previous.status === 200 ? previous.data : null);
      setOriginalDiff(original.status === 200 ? original.data : null);
    } catch {
      setPreviousDiff(null);
      setOriginalDiff(null);
    }
  }

  async function saveExportScratchSnapshot() {
    setScratchError(null);
    setScratchOk(false);
    try {
      const response = await customFetch<{ status: number; data: LoopSessionResponse }>(
        `/api/loop/sessions/${sessionId}/export-scratch/snapshots`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_version: expectedVersion,
            spec_version_id: selectedSpecId || session.export_scratch?.spec_version_id,
          }),
        },
      );
      if (response.status === 200) {
        const next = response.data;
        setExpectedVersion(next.version);
        setViewed(next);
        setSections(next.export_scratch?.document.sections ?? sections);
        setScratchOk(true);
        await queryClient.invalidateQueries({
          queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        });
        await loadScratchDiffs(selectedSpecId || next.export_scratch?.spec_version_id);
      }
    } catch (error) {
      setScratchError(getApiErrorMessage(error));
    }
  }

  async function restoreSnapshot(snapshotId: string) {
    setScratchError(null);
    try {
      const response = await customFetch<{ status: number; data: LoopSessionResponse }>(
        `/api/loop/sessions/${sessionId}/export-scratch/snapshots/${snapshotId}/restore`,
        {
          method: "POST",
          body: JSON.stringify({ expected_version: expectedVersion }),
        },
      );
      if (response.status === 200) {
        const next = response.data;
        setExpectedVersion(next.version);
        setViewed(next);
        setSections(next.export_scratch?.document.sections ?? []);
        await queryClient.invalidateQueries({
          queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        });
        await loadScratchDiffs(selectedSpecId || next.export_scratch?.spec_version_id);
      }
    } catch (error) {
      setScratchError(getApiErrorMessage(error));
    }
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
          spec_version_id: selectedSpecId || session.export_scratch?.spec_version_id,
        },
      );
      if (response.status === 200) {
        const next = response.data;
        setExpectedVersion(next.version);
        setViewed(next);
        setSections(next.export_scratch?.document.sections ?? sections);
        setScratchOk(true);
        await queryClient.invalidateQueries({
          queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        });
        await loadScratchDiffs(selectedSpecId || next.export_scratch?.spec_version_id);
      }
    } catch (error) {
      setScratchError(getApiErrorMessage(error));
    }
  }

  async function selectSpecVersion(specVersionId: string) {
    setSelectedSpecId(specVersionId);
    setScratchError(null);
    try {
      const response = await customFetch<{ status: number; data: LoopSessionResponse }>(
        `/api/loop/sessions/${sessionId}?spec_version_id=${specVersionId}`,
        { method: "GET" },
      );
      if (response.status === 200) {
        const next = response.data;
        setViewed(next);
        setExpectedVersion(next.version);
        setSections(next.export_scratch?.document.sections ?? []);
        await loadScratchDiffs(specVersionId);
      }
    } catch (error) {
      setScratchError(getApiErrorMessage(error));
    }
  }

  const selectedValid =
    specVersions.find((item) => item.id === selectedSpecId)?.valid ??
    selectedSpecId === session.valid_spec_version_id;
  const review = viewed.clarification_review ?? session.clarification_review;

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
          {specVersions.length ? (
            <label className="grid gap-2 text-sm font-medium">
              Spec Version
              <select
                aria-label="Spec Version"
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                value={selectedSpecId}
                onChange={(event) => void selectSpecVersion(event.target.value)}
              >
                {specVersions.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.valid ? "Valid" : "Not Valid"} · {item.created_at}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {!selectedValid && selectedSpecId ? (
            <p role="status" aria-label="Spec Version not Valid" className="text-sm">
              This Spec Version is not Valid. Readiness still follows the current Valid Spec
              Version and Aggregator Report.
            </p>
          ) : null}
          {review ? (
            <section aria-label="Clarification Review" className="grid gap-3 md:grid-cols-2">
              <div className="grid gap-1">
                <p className="text-sm font-medium">Original research idea</p>
                <p className="text-sm text-muted-foreground">{review.original_idea}</p>
              </div>
              <div className="grid gap-2">
                <p className="text-sm font-medium">Confirmed on this Spec Version</p>
                <p className="text-sm">
                  <span className="font-medium">Gap. </span>
                  {review.gap}
                </p>
                <p className="text-sm">
                  <span className="font-medium">Contribution. </span>
                  {review.contribution}
                </p>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {review.claims.map((claim) => (
                    <li key={claim}>{claim}</li>
                  ))}
                </ul>
              </div>
            </section>
          ) : null}
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
              <Button
                type="button"
                variant="secondary"
                className="justify-self-start"
                onClick={() => void saveExportScratchSnapshot()}
              >
                Save Snapshot
              </Button>
              {(viewed.export_scratch_snapshots ?? []).length ? (
                <ul aria-label="Export Scratch Snapshots" className="grid gap-2 text-sm">
                  {(viewed.export_scratch_snapshots ?? []).map((snapshot) => (
                    <li key={snapshot.id} className="flex items-center justify-between gap-2">
                      <span>Snapshot {snapshot.snapshot_n}</span>
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => void restoreSnapshot(snapshot.id)}
                      >
                        Load Snapshot {snapshot.snapshot_n}
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : null}
              {previousDiff?.sections?.length ? (
                <section aria-label="Diff versus previous Snapshot" className="grid gap-2">
                  <p className="text-sm font-medium">Diff versus previous Snapshot</p>
                  {previousDiff.sections.map((row) => (
                    <p key={row.id} className="text-sm">
                      {row.title}: {row.after}
                    </p>
                  ))}
                </section>
              ) : null}
              {originalDiff?.sections?.length ? (
                <section aria-label="Diff versus Snapshot 1" className="grid gap-2">
                  <p className="text-sm font-medium">Diff versus Snapshot 1</p>
                  {originalDiff.sections.map((row) => (
                    <p key={row.id} className="text-sm">
                      {row.title}: {row.after}
                    </p>
                  ))}
                </section>
              ) : null}
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
