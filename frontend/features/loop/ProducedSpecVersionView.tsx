"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CardKind, type SpecVersionResponse, WorkflowNode } from "@/lib/api/generated/model";

import { CARD_KIND_LABELS, LOOP_STAGE_CATALOG, WORKFLOW_NODE_LABELS } from "./catalog";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function unknownFields(value: Record<string, unknown>, knownKeys: readonly string[]): Record<string, unknown> | null {
  const rest: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (!knownKeys.includes(key)) {
      rest[key] = entry;
    }
  }
  return Object.keys(rest).length > 0 ? rest : null;
}

function JsonFallback({ value }: { value: unknown }) {
  return (
    <pre className="max-w-full overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function fieldText(value: unknown): string | null {
  if (!isRecord(value) || typeof value.text !== "string") {
    return null;
  }
  return value.text;
}

function cardKindLabel(kind: unknown): string {
  if (typeof kind === "string" && Object.values(CardKind).includes(kind as CardKind)) {
    return CARD_KIND_LABELS[kind as CardKind];
  }
  return typeof kind === "string" ? kind : "Card";
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function sourceHref(citation: Record<string, unknown> | undefined): string | null {
  const url = nonEmptyText(citation?.url);
  const doi = nonEmptyText(citation?.doi);
  return url ?? (doi ? `https://doi.org/${doi}` : null);
}

function EvidenceExcerpt({
  finding,
  field,
}: {
  finding: Record<string, unknown>;
  field: "what_was_done" | "method_or_feedback" | "limitation";
}) {
  const evidence = isRecord(finding.evidence) && isRecord(finding.evidence[field])
    ? finding.evidence[field]
    : null;
  const passage = nonEmptyText(evidence?.passage) ?? nonEmptyText(finding.supporting_passage);
  const location = nonEmptyText(evidence?.location) ?? nonEmptyText(finding.source_location);
  if (!passage) return null;

  return (
    <details className="mt-2 rounded-md border bg-muted/40 p-2 text-xs">
      <summary className="cursor-pointer font-medium">
        Evidence{location ? ` · ${location}` : ""}
      </summary>
      <blockquote className="mt-2 whitespace-pre-wrap border-l-2 pl-2 leading-5 text-muted-foreground">
        {passage}
      </blockquote>
    </details>
  );
}

function RelatedWorkSpecNode({ payload }: { payload: Record<string, unknown> }) {
  const narrative = isRecord(payload.narrative) ? payload.narrative : {};
  const projection = isRecord(payload.projection) ? payload.projection : null;
  const citations = Array.isArray(projection?.citations)
    ? projection.citations.filter(isRecord)
    : [];
  const findings = Array.isArray(projection?.related_work)
    ? projection.related_work.filter(isRecord)
    : [];
  const citationsById = new Map(
    citations.flatMap((citation) => {
      const id = nonEmptyText(citation.id);
      return id ? [[id, citation] as const] : [];
    }),
  );
  const analyzedCount =
    numberValue(narrative.analyzed_result_count) ??
    numberValue(narrative.citation_count) ??
    citations.length;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-3">
      <div>
        <p className="text-sm font-medium">Related work</p>
        <p className="text-sm text-muted-foreground">
          {findings.length > 0
            ? `${findings.length} source-grounded ${findings.length === 1 ? "study" : "studies"} compared.`
            : analyzedCount > 0
              ? `${analyzedCount} ${analyzedCount === 1 ? "source was" : "sources were"} analyzed for this Spec Version.`
              : "No Related Work findings are available in this Spec Version."}
        </p>
      </div>
      {findings.length === 0 && analyzedCount > 0 ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          The detailed comparison is unavailable in this older Spec Version.
        </p>
      ) : null}
      {findings.map((finding, index) => {
        const citationId = nonEmptyText(finding.citation_id);
        const citation = citationId ? citationsById.get(citationId) : undefined;
        const title = nonEmptyText(citation?.title) ?? `Study ${index + 1}`;
        const href = sourceHref(citation);
        const year = numberValue(citation?.year);
        const citationKey = nonEmptyText(citation?.citation_key);
        const whatWasDone = nonEmptyText(finding.what_was_done);
        const method = nonEmptyText(finding.method_or_feedback);
        const limitation = nonEmptyText(finding.limitation);

        return (
          <article key={nonEmptyText(finding.id) ?? `${citationId ?? "study"}-${index}`} className="rounded-lg border p-4">
            <header>
              <h4 className="font-semibold leading-6">
                {href ? (
                  <a className="text-in-progress hover:underline" href={href} target="_blank" rel="noreferrer">
                    {title}
                  </a>
                ) : title}
              </h4>
              {year || citationKey ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  {[year, citationKey].filter(Boolean).join(" · ")}
                </p>
              ) : null}
            </header>
            <dl className="mt-4 grid gap-4 lg:grid-cols-3">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">What was done</dt>
                <dd className="mt-1 whitespace-pre-wrap text-sm leading-6">{whatWasDone ?? "Not specified"}</dd>
                {whatWasDone ? <EvidenceExcerpt finding={finding} field="what_was_done" /> : null}
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Method or feedback</dt>
                <dd className="mt-1 whitespace-pre-wrap text-sm leading-6">{method ?? "Not stated in the source"}</dd>
                {method ? <EvidenceExcerpt finding={finding} field="method_or_feedback" /> : null}
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Remaining limitation</dt>
                <dd className="mt-1 whitespace-pre-wrap text-sm leading-6">{limitation ?? "Not specified"}</dd>
                {limitation ? <EvidenceExcerpt finding={finding} field="limitation" /> : null}
              </div>
            </dl>
          </article>
        );
      })}
    </div>
  );
}

const GAP_OUTCOME_LABELS: Record<string, string> = {
  no_direct_counter_evidence: "No direct counter-evidence found",
  gap_narrowed: "Gap narrowed by existing work",
  gap_not_supported: "Existing work appears to address this limitation",
  inconclusive: "Not enough evidence to decide",
};

function GapSpecNode({ payload }: { payload: Record<string, unknown> }) {
  const narrative = isRecord(payload.narrative) ? payload.narrative : null;
  const cards = Array.isArray(payload.card_snapshot) ? payload.card_snapshot.filter(isRecord) : [];
  const gapCard = cards.find((card) => card.kind === CardKind.gap);
  const cardBody = isRecord(gapCard?.body) ? gapCard.body : null;
  const legacyCandidate = isRecord(narrative?.candidate) ? narrative.candidate : null;
  const gap = cardBody ?? legacyCandidate;
  const statement = nonEmptyText(gap?.statement) ?? nonEmptyText(gap?.text);
  const status = nonEmptyText(gap?.status);
  const audit = isRecord(gap?.search_audit) ? gap.search_audit : null;
  const evidenceCheck = isRecord(gap?.evidence_check) ? gap.evidence_check : null;
  const claimAssessments = Array.isArray(audit?.claim_assessments)
    ? audit.claim_assessments.filter(isRecord)
    : [];
  const counterEvidence = Array.isArray(audit?.counter_evidence_results)
    ? audit.counter_evidence_results.filter(isRecord)
    : [];
  const supportingKeys = Array.isArray(gap?.supporting_citation_keys)
    ? gap.supporting_citation_keys.map(nonEmptyText).filter((key): key is string => Boolean(key))
    : [];
  const relatedCount = numberValue(audit?.related_work_analyzed_count);
  const counterCount = numberValue(audit?.counter_evidence_analyzed_count);
  const evidenceReady = status === "candidate" && audit?.complete === true && evidenceCheck?.ready === true;
  const statusLabel = evidenceReady
    ? "Evidence-ready Gap"
    : status === "proposed"
      ? "Proposed Gap"
      : "Potential Gap — further validation needed";

  if (!gap || !statement) {
    return <p className="text-sm text-muted-foreground">No confirmed Gap is available in this Spec Version.</p>;
  }

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="rounded-lg border border-navy p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold">{statusLabel}</p>
          {relatedCount !== null || counterCount !== null ? (
            <p className="text-xs text-muted-foreground">
              {relatedCount ?? 0} Related Work · {counterCount ?? 0} counter-evidence
            </p>
          ) : null}
        </div>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{statement}</p>
        {supportingKeys.length > 0 ? (
          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Supporting sources</p>
            <ul className="mt-2 flex flex-wrap gap-2" aria-label="Supporting sources">
              {supportingKeys.map((key) => (
                <li key={key} className="rounded-full bg-muted px-2.5 py-1 text-xs">{key}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {nonEmptyText(audit?.counter_evidence_assessment) ? (
        <section aria-label="Counter-evidence assessment">
          <h4 className="text-sm font-semibold">Counter-evidence assessment</h4>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
            {nonEmptyText(audit?.counter_evidence_assessment)}
          </p>
        </section>
      ) : null}

      {claimAssessments.length > 0 ? (
        <section aria-label="Gap claims">
          <h4 className="text-sm font-semibold">Gap claims</h4>
          <ul className="mt-2 grid gap-3">
            {claimAssessments.map((claim, index) => {
              const claimId = nonEmptyText(claim.claim_id) ?? `claim-${index + 1}`;
              const outcome = nonEmptyText(claim.outcome);
              const supportingEvidence = Array.isArray(claim.supporting_evidence)
                ? claim.supporting_evidence.filter(isRecord)
                : [];
              return (
                <li key={claimId} className="rounded-md border p-3 text-sm">
                  <p className="font-medium">{nonEmptyText(claim.statement) ?? `Claim ${index + 1}`}</p>
                  {outcome ? (
                    <p className="mt-1 text-muted-foreground">
                      Counter-evidence review: {GAP_OUTCOME_LABELS[outcome] ?? outcome.replaceAll("_", " ")}
                    </p>
                  ) : null}
                  {nonEmptyText(claim.assessment) ? (
                    <p className="mt-1 text-muted-foreground">{nonEmptyText(claim.assessment)}</p>
                  ) : null}
                  {supportingEvidence.map((evidence, evidenceIndex) => {
                    const passage = nonEmptyText(evidence.passage);
                    if (!passage) return null;
                    const source = [nonEmptyText(evidence.location), nonEmptyText(evidence.citation_key)]
                      .filter(Boolean)
                      .join(" · ");
                    return (
                      <blockquote key={`${claimId}-${evidenceIndex}`} className="mt-2 border-l-2 pl-3 text-muted-foreground">
                        {passage}{source ? ` — ${source}` : ""}
                      </blockquote>
                    );
                  })}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {counterEvidence.length > 0 ? (
        <section aria-label="Counter-evidence sources">
          <h4 className="text-sm font-semibold">Counter-evidence sources</h4>
          <ul className="mt-2 grid gap-3 sm:grid-cols-2">
            {counterEvidence.map((result, index) => {
              const title = nonEmptyText(result.title) ?? `Source ${index + 1}`;
              const href = sourceHref(result);
              const outcome = nonEmptyText(result.impact);
              const sourceDetails = [numberValue(result.year), nonEmptyText(result.venue)].filter(Boolean).join(" · ");
              const passage = nonEmptyText(result.evidence_passage);
              return (
                <li key={nonEmptyText(result.result_key) ?? `${title}-${index}`} className="rounded-md border p-3 text-sm">
                  <p className="font-medium">
                    {href ? <a href={href} target="_blank" rel="noreferrer" className="underline">{title}</a> : title}
                  </p>
                  {sourceDetails ? <p className="mt-1 text-xs text-muted-foreground">{sourceDetails}</p> : null}
                  {outcome ? <p className="mt-2">{GAP_OUTCOME_LABELS[outcome] ?? outcome.replaceAll("_", " ")}</p> : null}
                  {nonEmptyText(result.rationale) ? <p className="mt-1 text-muted-foreground">{nonEmptyText(result.rationale)}</p> : null}
                  {passage ? (
                    <blockquote className="mt-2 border-l-2 pl-3 text-muted-foreground">
                      {passage}{nonEmptyText(result.evidence_location) ? ` — ${nonEmptyText(result.evidence_location)}` : ""}
                    </blockquote>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function SpecNode({ node, payload }: { node: WorkflowNode; payload: unknown }) {
  if (!isRecord(payload)) {
    return (
      <div className="grid min-w-0 grid-cols-1 gap-2">
        <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p>
        <JsonFallback value={payload} />
      </div>
    );
  }

  if (node === WorkflowNode.related_work) {
    return <RelatedWorkSpecNode payload={payload} />;
  }

  if (node === WorkflowNode.gap) {
    return <GapSpecNode payload={payload} />;
  }

  const narrative = isRecord(payload.narrative) ? payload.narrative : null;
  const narrativeText = narrative ? fieldText(narrative) : null;
  const cards = Array.isArray(payload.card_snapshot) ? payload.card_snapshot : null;
  const unknownNarrative = narrative
    ? unknownFields(narrative, ["text"])
    : null;
  const unknownNode = unknownFields(payload, ["narrative", "card_snapshot", "projection"]);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-2">
      <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p>
      {narrativeText ? <p className="text-sm whitespace-pre-wrap">{narrativeText}</p> : null}
      {unknownNarrative ? <JsonFallback value={unknownNarrative} /> : null}
      {narrative === null && payload.narrative !== undefined ? (
        <JsonFallback value={payload.narrative} />
      ) : null}
      {cards
        ? cards.map((card, index) => {
            if (!isRecord(card)) {
              return <JsonFallback key={index} value={card} />;
            }
            const body = isRecord(card.body) ? card.body : null;
            const text = body ? fieldText(body) : null;
            const unknownBody = body ? unknownFields(body, ["text"]) : null;
            const unknownCard = unknownFields(card, ["id", "kind", "body"]);
            return (
              <div key={typeof card.id === "string" ? card.id : index} className="min-w-0 rounded-md border bg-muted/40 px-3 py-2">
                <p className="text-sm font-medium">{cardKindLabel(card.kind)}</p>
                {text ? <p className="text-sm whitespace-pre-wrap">{text}</p> : null}
                {unknownBody ? <JsonFallback value={unknownBody} /> : null}
                {body === null && card.body !== undefined ? <JsonFallback value={card.body} /> : null}
                {unknownCard ? <JsonFallback value={unknownCard} /> : null}
              </div>
            );
          })
        : payload.card_snapshot !== undefined
          ? <JsonFallback value={payload.card_snapshot} />
          : null}
      {unknownNode ? <JsonFallback value={unknownNode} /> : null}
    </div>
  );
}

function SpecDocument({ document }: { document: Record<string, unknown> }) {
  const nodes = isRecord(document.nodes) ? document.nodes : null;
  const unknownRoot = unknownFields(document, ["nodes"]);
  const catalogNodes = new Set<string>(
    LOOP_STAGE_CATALOG.flatMap((stage) => [...stage.nodes]),
  );
  const extraNodes = nodes
    ? Object.fromEntries(Object.entries(nodes).filter(([key]) => !catalogNodes.has(key)))
    : null;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      {nodes ? (
        <>
          {LOOP_STAGE_CATALOG.filter((stage) => stage.nodes.length > 0).map((stage) => {
            const present = stage.nodes.filter((node) => nodes[node] !== undefined);
            if (present.length === 0) {
              return null;
            }
            return (
              <section key={stage.id} className="min-w-0" aria-label={`${stage.name} in Produced Spec Version`}>
                <h3 className="font-serif text-navy">{stage.name}</h3>
                <div className="mt-2 grid min-w-0 grid-cols-1 gap-3">
                  {present.map((node) => (
                    <SpecNode key={node} node={node} payload={nodes[node]} />
                  ))}
                </div>
              </section>
            );
          })}
          {extraNodes && Object.keys(extraNodes).length > 0 ? <JsonFallback value={extraNodes} /> : null}
          {unknownRoot ? <JsonFallback value={unknownRoot} /> : null}
        </>
      ) : (
        <JsonFallback value={document} />
      )}
    </div>
  );
}

export function ProducedSpecVersionView({
  produced,
  validSpecVersionId,
}: {
  produced: SpecVersionResponse | null;
  validSpecVersionId: string | null;
}) {
  const stale = Boolean(produced && produced.id !== validSpecVersionId);

  return (
    <section aria-label="Produced Spec Version">
      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-navy">Produced Spec Version</CardTitle>
          <CardDescription>
            {produced
              ? stale
                ? "Stale. This Produced Spec Version is not the Valid Spec Version."
                : "This Produced Spec Version is the Valid Spec Version."
              : "No Produced Spec Version"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {produced ? (
            <div className="grid min-w-0 grid-cols-1 gap-4">
              {stale ? <p className="text-sm font-medium text-pending">Stale</p> : null}
              <SpecDocument document={produced.document} />
            </div>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}
