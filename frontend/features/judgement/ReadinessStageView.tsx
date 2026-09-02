"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
import {
  LoopStage,
  type ExportScratchDiffResponse,
  type LoopSessionResponse,
} from "@/lib/api/generated/model";
import { isExportScratchEditorOpen, sessionHref } from "@/features/loop/catalog";

import { ConferenceScoreList } from "./ConferenceScoreList";
import { ExportScratchMarkdownEditor } from "./ExportScratchMarkdownEditor";
import type { ConferenceScores, ReadinessState } from "./types";

export const EXPORT_SCRATCH_AUTOSAVE_MS = 800;

const STATE_LABEL: Record<ReadinessState, string> = {
  not_evaluated: "Not evaluated",
  blocked: "Blocked",
  ready: "Ready",
};

type ScratchDiff = ExportScratchDiffResponse;
type ExportKind = "markdown" | "pdf" | "spec_artifact";
type AutosaveStatus = "idle" | "saving" | "saved" | "error";

function clarificationReviewBrief(review: {
  gap: string;
  contribution: string;
  claims: string[];
}): string {
  const chunks = [review.gap, review.contribution, ...review.claims]
    .map((part) => part.trim())
    .filter(Boolean);
  const sentences: string[] = [];
  for (const chunk of chunks) {
    const pieces = chunk
      .split(/(?<=[.!?])(?:\s+|$)/)
      .map((piece) => piece.trim())
      .filter(Boolean);
    for (const piece of pieces) {
      sentences.push(/[.!?]$/.test(piece) ? piece : `${piece}.`);
      if (sentences.length >= 4) {
        return sentences.join(" ");
      }
    }
  }
  return sentences.join(" ");
}

function triggerDownload(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function overlayPersistFailed(error: unknown): boolean {
  return (
    (error instanceof ApiError && (error.status === 409 || error.status === 422)) ||
    (error instanceof Error && error.message === "Export Scratch overlay was not saved")
  );
}

export function ReadinessStageView({
  session,
  sessionId,
}: {
  session: LoopSessionResponse;
  sessionId: string;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const editingScratch = isExportScratchEditorOpen(LoopStage.readiness, searchParams);
  const readiness = session.readiness;
  const state: ReadinessState =
    (readiness?.state as ReadinessState | undefined) ?? "not_evaluated";
  const notice = readiness?.notice ?? "This is not conference acceptance.";
  const scores = (readiness?.scores ?? null) as ConferenceScores | null;
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportOk, setExportOk] = useState<ExportKind | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingDownload, setPendingDownload] = useState<ExportKind>("markdown");
  const [markdown, setMarkdown] = useState(
    session.export_scratch?.document.markdown ?? "",
  );
  const [persistedMarkdown, setPersistedMarkdown] = useState(markdown);
  const [expectedVersion, setExpectedVersion] = useState(session.version);
  const [scratchError, setScratchError] = useState<string | null>(null);
  const [snapshotOk, setSnapshotOk] = useState(false);
  const [autosaveStatus, setAutosaveStatus] = useState<AutosaveStatus>("idle");
  const specVersions = session.spec_versions ?? [];
  const [selectedSpecId, setSelectedSpecId] = useState(
    session.valid_spec_version_id ?? specVersions[0]?.id ?? "",
  );
  const [viewed, setViewed] = useState(session);
  const [previousDiff, setPreviousDiff] = useState<ScratchDiff | null>(null);
  const [originalDiff, setOriginalDiff] = useState<ScratchDiff | null>(null);

  const stopAutosaveRef = useRef(false);
  const inflightRef = useRef<Promise<LoopSessionResponse> | null>(null);
  const markdownRef = useRef(markdown);
  const persistedMarkdownRef = useRef(persistedMarkdown);
  const expectedVersionRef = useRef(expectedVersion);
  const selectedSpecIdRef = useRef(selectedSpecId);
  const viewedRef = useRef(viewed);

  markdownRef.current = markdown;
  persistedMarkdownRef.current = persistedMarkdown;
  expectedVersionRef.current = expectedVersion;
  selectedSpecIdRef.current = selectedSpecId;
  viewedRef.current = viewed;

  useEffect(() => {
    if (editingScratch) return;
    if (viewedRef.current.version > session.version) return;
    const nextMarkdown = session.export_scratch?.document.markdown ?? "";
    setMarkdown(nextMarkdown);
    setPersistedMarkdown(nextMarkdown);
    setExpectedVersion(session.version);
    setViewed(session);
    setSelectedSpecId(session.valid_spec_version_id ?? session.spec_versions?.[0]?.id ?? "");
  }, [session, editingScratch]);

  function applyScratchSession(next: LoopSessionResponse, fallbackMarkdown: string) {
    const nextMarkdown = next.export_scratch?.document.markdown ?? fallbackMarkdown;
    expectedVersionRef.current = next.version;
    viewedRef.current = next;
    markdownRef.current = nextMarkdown;
    persistedMarkdownRef.current = nextMarkdown;
    setExpectedVersion(next.version);
    setViewed(next);
    setMarkdown(nextMarkdown);
    setPersistedMarkdown(nextMarkdown);
    return next;
  }

  async function persistOverlayDocument(currentMarkdown: string) {
    if (!viewedRef.current.export_scratch && !session.export_scratch) {
      return viewedRef.current;
    }
    const response = await patchExportScratchApiLoopSessionsSessionIdExportScratchPatch(
      sessionId,
      {
        expected_version: expectedVersionRef.current,
        document: { markdown: currentMarkdown },
        spec_version_id: selectedSpecIdRef.current || session.export_scratch?.spec_version_id,
      },
    );
    if (response.status !== 200) {
      throw new Error("Export Scratch overlay was not saved");
    }
    return applyScratchSession(response.data, currentMarkdown);
  }

  async function persistOverlayBuffer() {
    try {
      return await persistOverlayDocument(markdownRef.current);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return viewedRef.current;
      }
      throw error;
    }
  }

  function closeEditor() {
    router.replace(sessionHref(sessionId, { stage: LoopStage.readiness }), { scroll: false });
  }

  function openEditor() {
    const specId =
      selectedSpecId ||
      session.valid_spec_version_id ||
      session.export_scratch?.spec_version_id;
    if (!specId) return;
    stopAutosaveRef.current = false;
    setAutosaveStatus("idle");
    setScratchError(null);
    router.replace(
      sessionHref(sessionId, {
        stage: LoopStage.readiness,
        exportScratch: true,
        specVersionId: specId,
      }),
      { scroll: false },
    );
  }

  async function finishExportScratchEditor() {
    setScratchError(null);
    try {
      if (inflightRef.current) {
        await inflightRef.current;
      }
      if (markdownRef.current !== persistedMarkdownRef.current && !stopAutosaveRef.current) {
        await persistOverlayDocument(markdownRef.current);
        await queryClient.invalidateQueries({
          queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        });
      }
      closeEditor();
    } catch (error) {
      if (overlayPersistFailed(error)) {
        stopAutosaveRef.current = true;
        setAutosaveStatus("error");
      }
      setScratchError(getApiErrorMessage(error));
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
    setSnapshotOk(false);
    try {
      const current =
        markdownRef.current !== persistedMarkdownRef.current
          ? await persistOverlayDocument(markdownRef.current)
          : viewedRef.current;
      const response = await saveExportScratchSnapshotApiLoopSessionsSessionIdExportScratchSnapshotsPost(
        sessionId,
        {
          expected_version: current.version,
          spec_version_id: selectedSpecIdRef.current || session.export_scratch?.spec_version_id,
        },
      );
      if (response.status === 200) {
        const next = applyScratchSession(
          response.data,
          current.export_scratch?.document.markdown ?? markdownRef.current,
        );
        setSnapshotOk(true);
        setAutosaveStatus("saved");
        await queryClient.invalidateQueries({
          queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        });
        await loadScratchDiffs(selectedSpecIdRef.current || next.export_scratch?.spec_version_id);
      }
    } catch (error) {
      if (overlayPersistFailed(error)) {
        stopAutosaveRef.current = true;
        setAutosaveStatus("error");
      }
      setScratchError(getApiErrorMessage(error));
    }
  }

  async function restoreSnapshot(snapshotId: string) {
    setScratchError(null);
    try {
      const response = await restoreExportScratchSnapshotApiLoopSessionsSessionIdExportScratchSnapshotsSnapshotIdRestorePost(
        sessionId,
        snapshotId,
        { expected_version: expectedVersionRef.current },
      );
      if (response.status === 200) {
        const next = applyScratchSession(response.data, "");
        await queryClient.invalidateQueries({
          queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        });
        await loadScratchDiffs(selectedSpecIdRef.current || next.export_scratch?.spec_version_id);
      }
    } catch (error) {
      setScratchError(getApiErrorMessage(error));
    }
  }

  async function selectSpecVersion(specVersionId: string) {
    setScratchError(null);
    try {
      if (markdownRef.current !== persistedMarkdownRef.current && !editingScratch) {
        await persistOverlayDocument(markdownRef.current);
      }
      const response = await getSessionApiLoopSessionsSessionIdGet(sessionId, {
        spec_version_id: specVersionId,
      });
      if (response.status === 200) {
        applyScratchSession(response.data, "");
        setSelectedSpecId(specVersionId);
        await loadScratchDiffs(specVersionId);
      }
    } catch (error) {
      setScratchError(getApiErrorMessage(error));
    }
  }

  useEffect(() => {
    if (!editingScratch) return;
    const hasScratch = Boolean(viewed.export_scratch || session.export_scratch);
    if (!hasScratch) {
      router.replace(sessionHref(sessionId, { stage: LoopStage.readiness }), { scroll: false });
      return;
    }
    const urlSpec = searchParams.get("spec_version");
    const fallback =
      selectedSpecIdRef.current ||
      session.valid_spec_version_id ||
      session.export_scratch?.spec_version_id;
    if (!urlSpec && fallback) {
      router.replace(
        sessionHref(sessionId, {
          stage: LoopStage.readiness,
          exportScratch: true,
          specVersionId: fallback,
        }),
        { scroll: false },
      );
      return;
    }
    if (urlSpec && urlSpec !== viewed.export_scratch?.spec_version_id) {
      void selectSpecVersion(urlSpec);
    }
  }, [editingScratch, searchParams, session.export_scratch, session.valid_spec_version_id, sessionId, router, viewed.export_scratch?.spec_version_id]);

  useEffect(() => {
    if (!editingScratch) return;
    stopAutosaveRef.current = false;
    setAutosaveStatus("idle");
    return () => {
      if (
        !stopAutosaveRef.current &&
        markdownRef.current !== persistedMarkdownRef.current
      ) {
        void persistOverlayDocument(markdownRef.current);
      }
    };
  }, [editingScratch]);

  useEffect(() => {
    if (!editingScratch || stopAutosaveRef.current) return;
    if (markdown === persistedMarkdown) return;
    const timer = window.setTimeout(() => {
      if (stopAutosaveRef.current) return;
      if (markdownRef.current === persistedMarkdownRef.current) return;
      setAutosaveStatus("saving");
      const pending = persistOverlayDocument(markdownRef.current);
      inflightRef.current = pending;
      void pending
        .then(async () => {
          setAutosaveStatus("saved");
          await queryClient.invalidateQueries({
            queryKey: getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
          });
        })
        .catch((error: unknown) => {
          if (overlayPersistFailed(error)) {
            stopAutosaveRef.current = true;
            setAutosaveStatus("error");
          }
          setScratchError(getApiErrorMessage(error));
        })
        .finally(() => {
          inflightRef.current = null;
        });
    }, EXPORT_SCRATCH_AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
  }, [editingScratch, markdown, persistedMarkdown, queryClient, sessionId]);

  const selectedValid =
    specVersions.find((item) => item.id === selectedSpecId)?.valid ??
    selectedSpecId === session.valid_spec_version_id;
  const review = viewed.clarification_review ?? session.clarification_review;
  const snapshots = viewed.export_scratch_snapshots ?? [];

  if (editingScratch) {
    return (
      <section
        aria-label="Export Scratch editor"
        className="flex min-h-[calc(100dvh-8rem)] flex-col gap-3"
      >
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button type="button" onClick={() => void finishExportScratchEditor()}>
            Done
          </Button>
          <Button type="button" variant="secondary" onClick={() => void saveExportScratchSnapshot()}>
            Save Snapshot
          </Button>
          {autosaveStatus === "saving" ? (
            <p role="status" aria-label="Export Scratch autosave" className="text-sm text-muted-foreground">
              Saving
            </p>
          ) : null}
          {autosaveStatus === "saved" ? (
            <p role="status" aria-label="Export Scratch autosave" className="text-sm text-muted-foreground">
              Saved
            </p>
          ) : null}
          {autosaveStatus === "error" ? (
            <p role="status" aria-label="Export Scratch autosave" className="text-sm text-destructive">
              Error
            </p>
          ) : null}
          {snapshotOk ? (
            <p className="text-sm text-muted-foreground">Export Scratch Snapshot saved.</p>
          ) : null}
        </div>
        <p role="status" aria-label="Export Scratch overlay" className="text-sm">
          You are editing the Export Scratch, not the Research Spec. Changing the loop still
          means reopen a Workflow Node.
        </p>
        {scratchError ? (
          <p role="alert" className="shrink-0 text-sm text-destructive">
            {scratchError}
          </p>
        ) : null}
        <div className="min-h-0 min-w-0 flex-1">
          <ExportScratchMarkdownEditor value={markdown} onChange={setMarkdown} />
        </div>
      </section>
    );
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
            <section aria-label="Clarification Review" className="grid gap-3">
              <div className="grid gap-1">
                <p className="text-sm font-medium">Original research idea</p>
                <p className="text-sm text-muted-foreground">{review.original_idea}</p>
              </div>
              <div className="grid gap-1">
                <p className="text-sm font-medium">This Spec Version in brief</p>
                <p className="text-sm text-muted-foreground">
                  {clarificationReviewBrief(review)}
                </p>
              </div>
            </section>
          ) : null}
          {viewed.export_scratch || session.export_scratch ? (
            <>
              <div className="grid gap-2">
                <p className="text-sm font-medium">Export Scratch</p>
                <Button
                  type="button"
                  variant="secondary"
                  className="justify-self-start"
                  onClick={openEditor}
                >
                  Edit Export Scratch
                </Button>
              </div>
              {snapshots.length ? (
                <ul aria-label="Export Scratch Snapshots" className="grid gap-2 text-sm">
                  {snapshots.map((snapshot) => (
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
              {previousDiff && previousDiff.before !== previousDiff.after ? (
                <section aria-label="Diff versus previous Snapshot" className="grid gap-2">
                  <p className="text-sm font-medium">Diff versus previous Snapshot</p>
                  <pre className="overflow-auto whitespace-pre-wrap text-sm">{previousDiff.after}</pre>
                </section>
              ) : null}
              {originalDiff && originalDiff.before !== originalDiff.after ? (
                <section aria-label="Diff versus Snapshot 1" className="grid gap-2">
                  <p className="text-sm font-medium">Diff versus Snapshot 1</p>
                  <pre className="overflow-auto whitespace-pre-wrap text-sm">{originalDiff.after}</pre>
                </section>
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
