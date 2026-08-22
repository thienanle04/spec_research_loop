"use client";

import { useState } from "react";
import { LoaderCircle, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { WorkflowNode } from "@/lib/api/generated/model";

const MODE_COPY = {
  idea: {
    title: "Research idea",
    description: "Paste the research idea, then Send.",
    action: "Send",
    pending: "Sending…",
  },
  recluster: {
    title: "Next Grilling Questions",
    description: "Send to generate the next Grilling Question cluster from the corrected turn list.",
    action: "Send",
    pending: "Sending…",
  },
  cards: {
    title: "Generate Cards",
    description: "Generate Cards from the confirmed interpretation.",
    action: "Generate Cards",
    pending: "Generating Cards…",
  },
} as const;

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
  const copy = MODE_COPY[mode];
  const idea = mode === "idea";
  const canSend = !generating && !saveBlocked && (!idea || Boolean(message.trim()));

  function send() {
    if (!canSend) return;
    const trimmed = message.trim();
    setMessage("");
    onGenerate(idea ? trimmed : undefined);
  }

  return (
    <Card aria-busy={generating || undefined}>
      <CardHeader>
        <CardTitle className="font-serif text-navy">{copy.title}</CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <GenerateError error={error} />
        {idea ? (
          <div className="grid gap-2">
            <label htmlFor="grilling-idea" className="text-sm font-medium">
              Your idea
            </label>
            <Textarea
              id="grilling-idea"
              aria-describedby="grilling-idea-hint"
              disabled={generating}
              placeholder="Describe the research idea"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.preventDefault();
                  send();
                }
              }}
            />
            <p id="grilling-idea-hint" className="text-sm text-muted-foreground">
              Ctrl+Enter or Cmd+Enter to Send.
            </p>
          </div>
        ) : null}
        <Button disabled={!canSend} onClick={send}>
          {generating ? <LoaderCircle aria-hidden="true" className="animate-spin" /> : <Send aria-hidden="true" />}
          {generating ? copy.pending : copy.action}
        </Button>
      </CardContent>
    </Card>
  );
}

export function GenerateError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded-md border border-destructive bg-card p-3">
      <p className="text-sm font-medium text-destructive">There is a problem</p>
      <p className="mt-1 text-sm">{error}</p>
    </div>
  );
}
