"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

export function isGrillingNode(node: WorkflowNode): boolean {
  return (
    node === WorkflowNode.idea_interpretation || node === WorkflowNode.idea_decomposition
  );
}

export function IdeaGeneratePanel({
  mode,
  saveBlocked,
  generating,
  error,
  onGenerate,
}: {
  mode: "idea" | "recluster" | "cards";
  saveBlocked: boolean;
  generating: boolean;
  error: string | null;
  onGenerate: (message?: string) => void;
}) {
  const [message, setMessage] = useState("");
  const idea = mode === "idea";
  const canSend = !generating && !saveBlocked && (!idea || Boolean(message.trim()));
  const actionLabel = mode === "cards" ? "Generate Cards" : "Send";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-navy">{actionLabel}</CardTitle>
        <CardDescription>
          {mode === "idea"
            ? "Paste the research idea, then Send."
            : mode === "recluster"
              ? "Send to generate the next Grilling Question cluster from the corrected turn list."
              : "Generate Cards from the confirmed interpretation."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {idea ? (
          <label className="grid gap-2 text-sm font-medium">
            Your idea
            <Textarea
              disabled={generating}
              placeholder="Describe the research idea"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
            />
          </label>
        ) : null}
        <Button
          disabled={!canSend}
          onClick={() => {
            const trimmed = message.trim();
            setMessage("");
            onGenerate(idea ? trimmed : undefined);
          }}
        >
          {actionLabel}
        </Button>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function GenerateError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {error}
    </p>
  );
}
