export function suggestedPatchFromNarrative(narrative: Record<string, unknown> | undefined) {
  if (!narrative) return null;
  const prose = narrative.suggested_patch;
  if (typeof prose !== "string" || !prose.trim()) return null;
  const rawIds = narrative.target_card_ids;
  const targetCardIds = Array.isArray(rawIds)
    ? rawIds.filter((id): id is string => typeof id === "string")
    : [];
  return { prose, targetCardIds };
}

export function SuggestedPatchNotice({
  narrative,
}: {
  narrative: Record<string, unknown> | undefined;
}) {
  const patch = suggestedPatchFromNarrative(narrative);
  if (!patch) return null;
  return (
    <section aria-label="Suggested patch" className="rounded-md border border-border bg-card p-3">
      <h3 className="text-sm font-medium text-navy">Suggested patch</h3>
      <p className="mt-1 text-sm whitespace-pre-wrap">{patch.prose}</p>
      {patch.targetCardIds.length > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">Card ids: {patch.targetCardIds.join(", ")}</p>
      ) : null}
    </section>
  );
}
