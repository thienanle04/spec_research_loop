import type { ConferenceScores } from "./types";

const CRITERIA = [
  ["originality", "Originality"],
  ["significance", "Significance"],
  ["soundness", "Soundness"],
  ["clarity", "Clarity"],
  ["reproducibility", "Reproducibility"],
] as const;

export function ConferenceScoreList({ scores }: { scores: ConferenceScores | null }) {
  if (scores == null) {
    return <p className="text-sm text-muted-foreground">No criterion scores on this Judge Run.</p>;
  }
  return (
    <dl className="grid gap-3" aria-label="Conference Judge criterion scores">
      {CRITERIA.map(([key, label]) => (
        <div key={key} className="flex items-baseline justify-between gap-3 rounded-md border border-border p-3">
          <dt className="text-sm font-medium">{label}</dt>
          <dd className="text-sm tabular-nums">{scores[key]}/10</dd>
        </div>
      ))}
    </dl>
  );
}
