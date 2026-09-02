"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Beaker,
  CheckCircle2,
  ChevronRight,
  FileText,
  Lightbulb,
  Target,
} from "lucide-react";

import type {
  CitationResponse,
  RelatedWorkFindingResponse,
} from "@/lib/api/generated/model";
import { customFetch } from "@/lib/api/mutator";

import { RelatedWorkMatrix } from "@/features/research/RelatedWorkMatrix";
import type { PreferredSources, ResearchInputs } from "@/features/research/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function DevLeftovers({
  value,
  label = "Raw leftovers",
  show = true,
}: {
  value: unknown;
  label?: string;
  show?: boolean;
}) {
  if (!show || value == null) return null;
  if (isRecord(value) && Object.keys(value).length === 0) return null;
  return (
    <details className="rounded-md border border-dashed bg-muted/30 p-2 text-xs text-muted-foreground">
      <summary className="cursor-pointer font-medium">{label}</summary>
      <pre className="mt-2 max-w-full overflow-x-auto whitespace-pre-wrap">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

const SOURCE_LABELS: Array<[keyof PreferredSources, string]> = [
  ["peer_reviewed_papers", "Peer-reviewed papers"],
  ["official_proceedings", "Official proceedings"],
  ["author_materials", "Author materials"],
  ["sourced_surveys", "Surveys with clear sources"],
];

export function parseResearchInputs(narrative: Record<string, unknown>): ResearchInputs | null {
  if (!Array.isArray(narrative.keywords) || !isRecord(narrative.preferred_sources)) {
    return null;
  }
  const preferred = narrative.preferred_sources;
  const keywords = narrative.keywords.filter((item): item is string => typeof item === "string");
  return {
    keywords,
    preferred_sources: {
      peer_reviewed_papers: Boolean(preferred.peer_reviewed_papers),
      official_proceedings: Boolean(preferred.official_proceedings),
      author_materials: Boolean(preferred.author_materials),
      sourced_surveys: Boolean(preferred.sourced_surveys),
    },
  };
}

export function ResearchInputsView({ value }: { value: ResearchInputs }) {
  return (
    <div className="grid gap-4 text-sm">
      <section className="grid gap-2" aria-label="Keywords">
        <h4 className="font-medium">Keywords</h4>
        {value.keywords.length > 0 ? (
          <ul className="flex flex-wrap gap-2">
            {value.keywords.map((keyword) => (
              <li key={keyword} className="rounded-md border bg-muted/40 px-3 py-1">
                {keyword}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">No keywords.</p>
        )}
      </section>
      <section className="grid gap-2" aria-label="Preferred Sources">
        <h4 className="font-medium">Preferred Sources</h4>
        <ul className="grid gap-1 sm:grid-cols-2">
          {SOURCE_LABELS.map(([key, label]) => (
            <li key={key} className="rounded-md border px-3 py-2">
              {value.preferred_sources[key] ? "✓ " : "○ "}
              {label}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

type ExperimentItem = {
  claim: string;
  action: string;
  objective: string;
  significance: string;
};

export function parseExperimentPlan(
  narrative: Record<string, unknown>,
): { experiments: ExperimentItem[] } | null {
  if (!isRecord(narrative.plan) || !Array.isArray(narrative.plan.experiments)) {
    return null;
  }
  const experiments = narrative.plan.experiments.filter(
    (item): item is ExperimentItem =>
      isRecord(item) &&
      typeof item.claim === "string" &&
      typeof item.action === "string" &&
      typeof item.objective === "string" &&
      typeof item.significance === "string",
  );
  return { experiments };
}

export function ExperimentPlanView({ plan }: { plan: { experiments: ExperimentItem[] } }) {
  if (plan.experiments.length === 0) {
    return <p className="text-sm text-muted-foreground">No experiments in this Stage Revision.</p>;
  }
  return (
    <div className="grid gap-4">
      {plan.experiments.map((exp, idx) => (
        <article key={idx} className="overflow-hidden rounded-lg border bg-background">
          <header className="border-b bg-muted/40 px-4 py-3">
            <h4 className="flex items-start gap-2 text-sm font-semibold">
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="leading-snug">{exp.claim}</span>
            </h4>
          </header>
          <div className="grid gap-4 p-4 text-sm">
            <div>
              <h5 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <Target className="h-3.5 w-3.5" /> Action
              </h5>
              <p className="whitespace-pre-wrap">{exp.action}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h5 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <Activity className="h-3.5 w-3.5" /> Objective
                </h5>
                <p className="whitespace-pre-wrap">{exp.objective}</p>
              </div>
              <div>
                <h5 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <Lightbulb className="h-3.5 w-3.5" /> Significance
                </h5>
                <p className="whitespace-pre-wrap">{exp.significance}</p>
              </div>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

type FeasibilityReport = {
  is_feasible: boolean;
  required_resources: string[];
  potential_bottlenecks: string[];
  mitigation_strategies: string[];
  conclusion: string;
};

export function parseFeasibilityReport(narrative: Record<string, unknown>): FeasibilityReport | null {
  if (!isRecord(narrative.feasibility_report)) return null;
  const report = narrative.feasibility_report;
  if (typeof report.is_feasible !== "boolean" || typeof report.conclusion !== "string") {
    return null;
  }
  const asStrings = (value: unknown) =>
    Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  return {
    is_feasible: report.is_feasible,
    conclusion: report.conclusion,
    required_resources: asStrings(report.required_resources),
    potential_bottlenecks: asStrings(report.potential_bottlenecks),
    mitigation_strategies: asStrings(report.mitigation_strategies),
  };
}

export function FeasibilityReportView({ report }: { report: FeasibilityReport }) {
  return (
    <div className="grid gap-4 text-sm">
      <div
        className={`flex items-start gap-3 rounded-lg border p-4 ${
          report.is_feasible
            ? "border-emerald-200 bg-emerald-50"
            : "border-destructive/20 bg-destructive/10"
        }`}
      >
        {report.is_feasible ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
        ) : (
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
        )}
        <div>
          <p className={`font-semibold ${report.is_feasible ? "text-emerald-800" : "text-destructive"}`}>
            {report.is_feasible ? "Experiment Plan is Feasible" : "Significant Feasibility Concerns"}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-foreground/90">{report.conclusion}</p>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {(
          [
            ["Required Resources", report.required_resources],
            ["Potential Bottlenecks", report.potential_bottlenecks],
            ["Mitigation Strategies", report.mitigation_strategies],
          ] as const
        ).map(([title, items]) => (
          <section key={title} className="rounded-lg border p-4">
            <h5 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
              {title}
            </h5>
            {items.length > 0 ? (
              <ul className="grid gap-1.5">
                {items.map((item, index) => (
                  <li key={index} className="flex gap-2">
                    <span className="text-muted-foreground">•</span>
                    <span className="whitespace-pre-wrap">{item}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">None listed.</p>
            )}
          </section>
        ))}
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Beaker className="h-3.5 w-3.5" /> Feasibility Assessment
      </p>
    </div>
  );
}

export function GapBodyView({
  body,
  showLeftovers = true,
}: {
  body: Record<string, unknown>;
  showLeftovers?: boolean;
}) {
  const statement = typeof body.statement === "string" ? body.statement : null;
  const status = typeof body.status === "string" ? body.status : null;
  const supporting = Array.isArray(body.supporting_citation_keys)
    ? body.supporting_citation_keys.filter((item): item is string => typeof item === "string")
    : [];
  const leftover = Object.fromEntries(
    Object.entries(body).filter(
      ([key]) => !["statement", "status", "supporting_citation_keys"].includes(key),
    ),
  );
  return (
    <div className="grid gap-2 text-sm">
      {statement ? <p className="whitespace-pre-wrap">{statement}</p> : null}
      {status ? <p className="text-muted-foreground">Status: {status}</p> : null}
      {supporting.length > 0 ? (
        <p className="text-muted-foreground">Supporting citations: {supporting.join(", ")}</p>
      ) : null}
      <DevLeftovers
        show={showLeftovers}
        value={Object.keys(leftover).length > 0 ? leftover : null}
        label="Gap audit leftovers"
      />
    </div>
  );
}

export function RelatedWorkRevisionView({
  sessionId,
  stageRevisionId,
}: {
  sessionId: string;
  stageRevisionId: string | null;
}) {
  if (!stageRevisionId) {
    return (
      <p className="text-sm text-muted-foreground">
        Related Work matrix needs a re-minted Spec Version (or a Node Head Stage Revision) with a
        stage_revision_id pointer.
      </p>
    );
  }
  return <RelatedWorkRevisionLoaded sessionId={sessionId} stageRevisionId={stageRevisionId} />;
}

function RelatedWorkRevisionLoaded({
  sessionId,
  stageRevisionId,
}: {
  sessionId: string;
  stageRevisionId: string;
}) {
  const citationsQuery = useQuery({
    queryKey: ["/api/research/citations", sessionId, stageRevisionId],
    queryFn: async () => {
      const response = await customFetch<{ data: CitationResponse[]; status: number }>(
        `/api/research/sessions/${sessionId}/citations?stage_revision_id=${encodeURIComponent(stageRevisionId)}`,
        { method: "GET" },
      );
      return response.data;
    },
  });
  const findingsQuery = useQuery({
    queryKey: ["/api/research/findings", sessionId, stageRevisionId],
    queryFn: async () => {
      const response = await customFetch<{ data: RelatedWorkFindingResponse[]; status: number }>(
        `/api/research/sessions/${sessionId}/findings?stage_revision_id=${encodeURIComponent(stageRevisionId)}`,
        { method: "GET" },
      );
      return response.data;
    },
  });

  if (citationsQuery.isLoading || findingsQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading Related Work…</p>;
  }
  if (citationsQuery.isError || findingsQuery.isError) {
    return (
      <p className="text-sm text-destructive">
        Could not load frozen Related Work for this Stage Revision.
      </p>
    );
  }

  const citations = Array.isArray(citationsQuery.data) ? citationsQuery.data : [];
  const findings = Array.isArray(findingsQuery.data) ? findingsQuery.data : [];

  return <RelatedWorkMatrix citations={citations} findings={findings} />;
}
