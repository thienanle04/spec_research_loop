"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, getApiErrorMessage } from "@/lib/api/config";
import {
  downloadExportScratchMarkdownApiLoopSessionsSessionIdExportScratchMarkdownPost,
  downloadExportScratchPdfApiLoopSessionsSessionIdExportScratchPdfPost,
  exportScratchDiffApiLoopSessionsSessionIdExportScratchDiffGet,
  exportSpecArtifactApiLoopSessionsSessionIdSpecArtifactPost,
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  getSessionApiLoopSessionsSessionIdGet,
  patchExportScratchApiLoopSessionsSessionIdExportScratchPatch,
  restoreExportScratchSnapshotApiLoopSessionsSessionIdExportScratchSnapshotsSnapshotIdRestorePost,
  saveExportScratchSnapshotApiLoopSessionsSessionIdExportScratchSnapshotsPost,
} from "@/lib/api/generated/endpoints";
import type {
  ExportScratchDiffResponse,
  ExportScratchSection,
  LoopSessionResponse,
} from "@/lib/api/generated/model";

import { ConferenceScoreList } from "./ConferenceScoreList";
import type { ConferenceScores, ReadinessState } from "./types";

const STATE_LABEL: Record<ReadinessState, string> = {
  not_evaluated: "Not evaluated",
  blocked: "Blocked",
  ready: "Ready",
};

type ScratchDiff = ExportScratchDiffResponse;
type ExportKind = "markdown" | "pdf" | "spec_artifact";

function triggerDownload(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

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
  const [exportOk, setExportOk] = useState<ExportKind | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingDownload, setPendingDownload] = useState<ExportKind>("markdown");
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

  async function persistOverlayBuffer() {
    if (!sections.length) {
      return viewed;
    }
    try {
      const response = await patchExportScratchApiLoopSessionsSessionIdExportScratchPatch(
        sessionId,
        {
          expected_version: expectedVersion,
          document: { sections },
          spec_version_id: selectedSpecId || session.export_scratch?.spec_version_id,
        },
      );
      if (response.status !== 200) {
        throw new Error("Export Scratch overlay was not saved");
      }
      const next = response.data;
      setExpectedVersion(next.version);
      setViewed(next);
      setSections(next.export_scratch?.document.sections ?? sections);
      return next;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return viewed;
      }
      throw error;
    }
  }

  async function exportScratch(format: "markdown" | "pdf", ack: boolean) {
    setExportError(null);
    setExportOk(null);
    try {
      const next = await persistOverlayBuffer();
      const specVersionId =
        selectedSpecId || next.export_scratch?.spec_version_id || session.export_scratch?.spec_version_id;
      const params = specVersionId ? { spec_version_id: specVersionId } : undefined;
      const body = ack ? { critical_export_ack: true } : undefined;
      if (format === "pdf") {
        const response = await downloadExportScratchPdfApiLoopSessionsSessionIdExportScratchPdfPost(
          sessionId,
          body,
          params,
        );
        const disposition = response.headers?.get?.("content-disposition") ?? "";
        const matched = /filename="([^"]+)"/.exec(disposition);
        const filename =
          matched?.[1] ?? `export-scratch-${specVersionId || "download"}.pdf`;
        triggerDownload(
          filename,
          new Blob([response.data as BlobPart], { type: "application/pdf" }),
        );
      } else {
        const response = await downloadExportScratchMarkdownApiLoopSessionsSessionIdExportScratchMarkdownPost(
          sessionId,
          body,
          params,
        );
        const disposition = response.headers?.get?.("content-disposition") ?? "";
        const matched = /filename="([^"]+)"/.exec(disposition);
        const filename =
          matched?.[1] ?? `export-scratch-${specVersionId || "download"}.md`;
        triggerDownload(
          filename,
          new Blob(
            [typeof response.data === "string" ? response.data : ""],
            { type: "text/markdown;charset=utf-8" },
          ),
        );
      }
      setConfirmOpen(false);
      setExportOk(format);
    } catch (error) {
      setExportError(getApiErrorMessage(error));
    }
  }

  async function exportSpecArtifact(ack: boolean) {
    setExportError(null);
    setExportOk(null);
    try {
      const response = await exportSpecArtifactApiLoopSessionsSessionIdSpecArtifactPost(
        sessionId,
        ack ? { critical_export_ack: true } : undefined,
      );
      if (response.status !== 200) {
        throw new Error("Spec Artifact export failed");
      }
      const specId = response.data.spec_version_id;
      triggerDownload(
        `spec-artifact-${specId}.json`,
        new Blob([JSON.stringify(response.data, null, 2)], {
          type: "application/json",
        }),
      );
      setConfirmOpen(false);
      setExportOk("spec_artifact");
    } catch (error) {
      setExportError(getApiErrorMessage(error));
    }
  }

  function onExportClick(kind: ExportKind) {
    setExportError(null);
    setExportOk(null);
    if (state === "blocked") {
      setPendingDownload(kind);
      setConfirmOpen(true);
      return;
    }
    if (kind === "spec_artifact") {
      void exportSpecArtifact(false);
      return;
    }
    void exportScratch(kind, false);
  }

  async function loadScratchDiffs(specVersionId: string | undefined) {
    if (!specVersionId) {
      setPreviousDiff(null);
      setOriginalDiff(null);
      return;
    }
    try {
      const [previous, original] = await Promise.all([
        exportScratchDiffApiLoopSessionsSessionIdExportScratchDiffGet(sessionId, {
          against: "previous",
          spec_version_id: specVersionId,
        }),
        exportScratchDiffApiLoopSessionsSessionIdExportScratchDiffGet(sessionId, {
          against: "original",
          spec_version_id: specVersionId,
        }),
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
      const response = await saveExportScratchSnapshotApiLoopSessionsSessionIdExportScratchSnapshotsPost(
        sessionId,
        {
          expected_version: expectedVersion,
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

  async function restoreSnapshot(snapshotId: string) {
    setScratchError(null);
    try {
      const response = await restoreExportScratchSnapshotApiLoopSessionsSessionIdExportScratchSnapshotsSnapshotIdRestorePost(
        sessionId,
        snapshotId,
        { expected_version: expectedVersion },
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
      const response = await getSessionApiLoopSessionsSessionIdGet(sessionId, {
        spec_version_id: specVersionId,
      });
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
            <div className="flex flex-wrap gap-2">
              <Button type="button" className="justify-self-start" onClick={() => onExportClick("markdown")}>
                Export Scratch markdown
              </Button>
              <Button
                type="button"
                variant="outline"
                className="justify-self-start"
                onClick={() => onExportClick("pdf")}
              >
                Download PDF
              </Button>
              <Button
                type="button"
                variant="secondary"
                className="justify-self-start"
                onClick={() => onExportClick("spec_artifact")}
              >
                Spec Artifact JSON
              </Button>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Readiness is derived from the current Aggregator Report.
            </p>
          )}
          {state === "blocked" ? (
            <p className="text-sm text-muted-foreground">
              CRITICAL Judge Issues fail Readiness. Spec Artifact JSON and Export Scratch
              markdown and PDF download require a Critical Export Confirmation.
            </p>
          ) : null}
          {exportOk === "markdown" ? (
            <p role="status" aria-label="Export Scratch markdown" className="text-sm text-muted-foreground">
              Export Scratch markdown downloaded.
            </p>
          ) : null}
          {exportOk === "pdf" ? (
            <p role="status" aria-label="Download PDF" className="text-sm text-muted-foreground">
              Export Scratch PDF downloaded.
            </p>
          ) : null}
          {exportOk === "spec_artifact" ? (
            <p role="status" aria-label="Spec Artifact JSON" className="text-sm text-muted-foreground">
              Spec Artifact JSON downloaded.
            </p>
          ) : null}
          {exportError ? (
            <p role="alert" className="text-sm text-destructive">
              {exportError}
            </p>
          ) : null}
        </CardContent>
      </Card>
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="font-serif text-navy">Critical Export Confirmation</DialogTitle>
            <DialogDescription>
              Readiness stays blocked. This records a Critical Export Confirmation
              {pendingDownload === "spec_artifact"
                ? " and downloads Spec Artifact JSON of the Valid Spec Version."
                : ` and downloads the current Export Scratch as ${pendingDownload === "pdf" ? "PDF" : "markdown"}.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="grid gap-2 sm:flex sm:flex-col">
            <Button
              type="button"
              onClick={() =>
                pendingDownload === "spec_artifact"
                  ? void exportSpecArtifact(true)
                  : void exportScratch(pendingDownload, true)
              }
            >
              Confirm export
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
