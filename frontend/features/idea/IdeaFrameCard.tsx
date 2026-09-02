import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function IdeaFrameCard({
  intent,
  problem,
  researchQuestion,
  description,
  placeholders = false,
}: {
  intent: string;
  problem: string;
  researchQuestion: string;
  description: string;
  placeholders?: boolean;
}) {
  const fields = [
    { label: "Intent", value: intent },
    { label: "Problem", value: problem },
    { label: "Research question", value: researchQuestion },
  ];
  const visible = fields.filter((field) => field.value.trim() || placeholders);
  if (visible.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-navy">Idea Frame</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {visible.map((field) => (
          <div key={field.label} className="grid gap-1">
            <p className="text-sm font-medium">{field.label}</p>
            <p className="whitespace-pre-wrap break-words text-sm">
              {field.value.trim() ? field.value : "Waiting for generate."}
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
