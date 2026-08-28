"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { CitationResponse, RelatedWorkFindingResponse, WorkflowNode } from "@/lib/api/generated/model";

import { CitationSearchPanel } from "./CitationSearchPanel";
import { GapCandidatePicker } from "./GapCandidatePicker";
import { RelatedWorkMatrix } from "./RelatedWorkMatrix";
import { ResearchInputsEditor } from "./ResearchInputsEditor";
import type { GapCandidate, ResearchInputs } from "./types";

type Props = {
  node: WorkflowNode;
  inputs: ResearchInputs;
  citations: CitationResponse[];
  findings: RelatedWorkFindingResponse[];
  gapCandidate: GapCandidate | null;
  selectedGap: GapCandidate | null;
  running: boolean;
  progress: number;
  progressMessage: string | null;
  warnings: string[];
  error: string | null;
  saveError: string | null;
  disabled?: boolean;
  onInputsChange: (inputs: ResearchInputs) => void;
  onGenerate: () => void;
  onAbort: () => void;
  pinningCitationId?: string | null;
  onToggleCitationPin?: (citation: CitationResponse) => void;
  onSelectGap: (candidate: GapCandidate) => Promise<void> | void;
};

export function ResearchStagePanel(props: Props) {
  const locked = props.disabled || props.running;

  if (props.node === "research_inputs") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Research Inputs</CardTitle>
          <CardDescription>
            Review the suggested keywords, add any missing concepts, select preferred source categories, then Confirm.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <ResearchInputsEditor value={props.inputs} disabled={locked} onChange={props.onInputsChange} />
          {props.running ? (
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="outline" onClick={props.onAbort}>Stop suggestions</Button>
              <p role="status" className="text-sm text-muted-foreground">{props.progressMessage ?? "Suggesting keywords…"}</p>
            </div>
          ) : (
            <Button
              type="button"
              variant="outline"
              className="justify-self-start"
              disabled={props.disabled}
              onClick={props.onGenerate}
            >
              {props.inputs.keywords.length > 0
                ? "Regenerate keyword suggestions"
                : "Generate keyword suggestions"}
            </Button>
          )}
          <Messages warnings={props.warnings} error={props.error ?? props.saveError} />
        </CardContent>
      </Card>
    );
  }

  if (props.node === "related_work") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Related Work</CardTitle>
          <CardDescription>
            Search and analyze scholarly sources, review the source-grounded comparison, then Confirm.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-7">
          <CitationSearchPanel
            running={props.running}
            progress={props.progress}
            progressMessage={props.progressMessage}
            warnings={props.warnings}
            error={props.error}
            disabled={props.disabled}
            onSearch={props.onGenerate}
            onAbort={props.onAbort}
          />
          {props.saveError ? <p role="alert" className="text-sm text-destructive">{props.saveError}</p> : null}
          <RelatedWorkMatrix
            citations={props.citations}
            findings={props.findings}
            pinningCitationId={props.pinningCitationId}
            onToggleCitationPin={props.onToggleCitationPin}
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Research Gap</CardTitle>
        <CardDescription>
          Review the potential Gap and its source-supported limitations, edit it if needed, save it, then Confirm.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        {props.running ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="outline" onClick={props.onAbort}>Stop generation</Button>
            <p role="status" className="text-sm text-muted-foreground">{props.progressMessage ?? "Generating the Gap Candidate…"}</p>
          </div>
        ) : (
          <Button type="button" className="justify-self-start" disabled={props.disabled} onClick={props.onGenerate}>
            {props.gapCandidate || props.selectedGap
              ? "Regenerate Gap Candidate"
              : "Generate Gap Candidate"}
          </Button>
        )}
        <Messages
          warnings={gapWarningsForDisplay(props.warnings)}
          error={props.error ?? props.saveError}
        />
        <GapCandidatePicker
          candidate={props.gapCandidate}
          selectedGap={props.selectedGap}
          disabled={locked}
          onSelect={props.onSelectGap}
        />
      </CardContent>
    </Card>
  );
}

function gapWarningsForDisplay(warnings: string[]): string[] {
  const messages: string[] = [];
  const joined = warnings.join(" ").toLocaleLowerCase();
  if (
    joined.includes("provider search failed") ||
    joined.includes("request timed out") ||
    joined.includes("could not connect")
  ) {
    messages.push(
      "The literature service was temporarily unavailable, so the counter-evidence review may be incomplete. Try regenerating later.",
    );
  }
  if (
    joined.includes("source text could not") ||
    joined.includes("download") ||
    joined.includes("object storage")
  ) {
    messages.push(
      "Some source content could not be checked. Only evidence that passed the source checks is shown.",
    );
  }
  if (joined.includes("no semantically supported atomic gap claim remained")) {
    messages.push(
      "No limitation was supported clearly enough to form a potential Gap. Review or add Related Work sources.",
    );
  }
  return messages;
}

function Messages({ warnings, error }: { warnings: string[]; error: string | null }) {
  return (
    <>
      {warnings.length > 0 ? (
        <ul className="list-disc pl-5 text-sm text-pending">
          {warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
        </ul>
      ) : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </>
  );
}
