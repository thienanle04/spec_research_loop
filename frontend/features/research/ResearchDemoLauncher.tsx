"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAccount } from "@/features/identity";
import { getApiErrorMessage } from "@/lib/api";
import {
  confirmApiLoopSessionsSessionIdConfirmPost,
  createCardApiLoopSessionsSessionIdCardsPost,
  createSessionApiLoopSessionsPost,
  patchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
  recomputePrepareApiLoopSessionsSessionIdRecomputePreparePost,
} from "@/lib/api/generated/endpoints";
import { CardKind, LoopStage, WorkflowNode } from "@/lib/api/generated/model";
import { loginDestination } from "@/lib/auth-return";

import { RESEARCH_DEMO_FIXTURE } from "./research-demo-fixture";

type BootstrapStep =
  | "idle"
  | "creating"
  | "interpretation"
  | "decomposition"
  | "preparing"
  | "done";

const STEP_LABEL: Record<BootstrapStep, string> = {
  idle: "Ready",
  creating: "Creating Loop Session…",
  interpretation: "Confirming the prepared Idea interpretation…",
  decomposition: "Adding the prepared Idea decomposition Cards…",
  preparing: "Opening Research Inputs…",
  done: "Research demo ready. Redirecting…",
};

export function ResearchDemoLauncher() {
  const router = useRouter();
  const pathname = usePathname();
  const account = useAccount();
  const [step, setStep] = useState<BootstrapStep>("idle");
  const [error, setError] = useState<string | null>(null);
  const running = step !== "idle" && step !== "done";

  useEffect(() => {
    if (account.ready && !account.hasToken) {
      router.replace(loginDestination(pathname));
    }
  }, [account.hasToken, account.ready, pathname, router]);

  async function createDemo() {
    setError(null);
    setStep("creating");
    try {
      const created = await createSessionApiLoopSessionsPost({
        title: RESEARCH_DEMO_FIXTURE.title,
      });
      if (created.status !== 201) throw new Error(`Could not create the demo Loop Session (${created.status})`);
      const sessionId = created.data.id;

      setStep("interpretation");
      const interpretedDraft = await patchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch(
        sessionId,
        {
          expected_version: created.data.version,
          narrative: RESEARCH_DEMO_FIXTURE.interpretation,
        },
      );
      if (interpretedDraft.status !== 200) throw new Error(`Could not save the prepared Idea interpretation (${interpretedDraft.status})`);
      const interpreted = await confirmApiLoopSessionsSessionIdConfirmPost(
        sessionId,
        {
          node: WorkflowNode.idea_interpretation,
          expected_version: interpretedDraft.data.version,
        },
      );
      if (interpreted.status !== 200) throw new Error(`Could not confirm the Idea interpretation (${interpreted.status})`);

      setStep("decomposition");
      const problem = await createCardApiLoopSessionsSessionIdCardsPost(
        sessionId,
        {
          kind: CardKind.problem,
          body: RESEARCH_DEMO_FIXTURE.problem,
          expected_version: interpreted.data.version,
        },
      );
      if (problem.status !== 201) throw new Error(`Could not create the prepared Problem Card (${problem.status})`);
      const researchQuestion = await createCardApiLoopSessionsSessionIdCardsPost(
        sessionId,
        {
          kind: CardKind.research_question,
          body: RESEARCH_DEMO_FIXTURE.researchQuestion,
          expected_version: problem.data.version,
        },
      );
      if (researchQuestion.status !== 201) throw new Error(`Could not create the prepared Research Question Card (${researchQuestion.status})`);
      const constraint = await createCardApiLoopSessionsSessionIdCardsPost(
        sessionId,
        {
          kind: CardKind.constraint,
          body: RESEARCH_DEMO_FIXTURE.constraint,
          expected_version: researchQuestion.data.version,
        },
      );
      if (constraint.status !== 201) throw new Error(`Could not create the prepared Constraint Card (${constraint.status})`);
      const openQuestion = await createCardApiLoopSessionsSessionIdCardsPost(
        sessionId,
        {
          kind: CardKind.open_question,
          body: RESEARCH_DEMO_FIXTURE.openQuestion,
          expected_version: constraint.data.version,
        },
      );
      if (openQuestion.status !== 201) throw new Error(`Could not create the prepared Open Question Card (${openQuestion.status})`);
      const decomposed = await confirmApiLoopSessionsSessionIdConfirmPost(
        sessionId,
        {
          node: WorkflowNode.idea_decomposition,
          expected_version: openQuestion.data.version,
        },
      );
      if (decomposed.status !== 200) throw new Error(`Could not confirm the Idea decomposition (${decomposed.status})`);

      setStep("preparing");
      const prepared = await recomputePrepareApiLoopSessionsSessionIdRecomputePreparePost(
        sessionId,
        {
          stage: LoopStage.related_work,
          expected_version: decomposed.data.version,
        },
      );
      if (prepared.status !== 200) throw new Error(`Could not prepare Research Inputs (${prepared.status})`);
      setStep("done");
      router.push(`/sessions/${sessionId}?stage=related_work`);
    } catch (caught) {
      setError(getApiErrorMessage(caught));
      setStep("idle");
    }
  }

  if (!account.ready || account.isLoading || (account.hasToken && !account.signedIn)) {
    return <p className="text-muted-foreground">Checking Account…</p>;
  }
  if (!account.hasToken) {
    return <p className="text-muted-foreground">Redirecting to sign in…</p>;
  }

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="font-display text-4xl text-navy">Research frontend demo</h1>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          Create a small, deterministic research idea and open the real Related Work workflow.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{RESEARCH_DEMO_FIXTURE.title}</CardTitle>
          <CardDescription>Prepared input used to unlock the Related work Loop Stage.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <dl className="grid gap-4">
            <FixtureField label="Idea" value={RESEARCH_DEMO_FIXTURE.idea} />
            <FixtureField label="Problem" value={RESEARCH_DEMO_FIXTURE.problem.text} />
            <FixtureField label="Research Question" value={RESEARCH_DEMO_FIXTURE.researchQuestion.text} />
            <FixtureField label="Gap Candidate" value={RESEARCH_DEMO_FIXTURE.gapCandidate.text} />
            <FixtureField label="Contribution" value={RESEARCH_DEMO_FIXTURE.contribution.text} />
            <FixtureField label="Claim" value={RESEARCH_DEMO_FIXTURE.claim.text} />
            <FixtureField label="Evidence" value={RESEARCH_DEMO_FIXTURE.evidence.text} />
            <FixtureField label="Constraint" value={RESEARCH_DEMO_FIXTURE.constraint.text} />
            <FixtureField label="Open Question" value={RESEARCH_DEMO_FIXTURE.openQuestion.text} />
          </dl>
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={running} onClick={() => void createDemo()}>
              {running ? "Preparing demo…" : "Create and open Research demo"}
            </Button>
            <p role="status" className="text-sm text-muted-foreground">{STEP_LABEL[step]}</p>
          </div>
          {error ? (
            <div role="alert" className="rounded-md border border-destructive p-3">
              <p className="text-sm text-destructive">{error}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Any Loop Session created before the failure remains available on the Sessions page.
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function FixtureField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-sm font-medium text-navy">{label}</dt>
      <dd className="mt-1 text-sm">{value}</dd>
    </div>
  );
}
