"use client";

import Link from "next/link";

import { API_BASE_URL } from "@/lib/api";
import { useAccount } from "@/features/identity";
import { LOOP_STAGE_CATALOG } from "@/features/loop/catalog";
import { LOOP_STAGE_ICONS } from "@/features/loop/stage-icons";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function HomePage() {
  const { signedIn } = useAccount();

  return (
    <div>
      <section className="border-b bg-card">
        <div className="mx-auto grid max-w-5xl gap-6 px-6 py-16 lg:grid-cols-12">
          <div className="lg:col-span-8">
            <h1 className="font-display text-4xl leading-tight text-navy sm:text-5xl">
              Turn a vague research idea into a verified Research Spec.
            </h1>
            <p className="mt-4 max-w-2xl text-lg text-muted-foreground">
              SpecResearch Loop is a human-in-the-loop workflow: grilling, related work,
              gap, contribution, claims and evidence, experiment planning, Spec Draft,
              independent judges, and readiness.
            </p>
            <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
              The system evaluates readiness criteria. It does not guarantee conference acceptance.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/sessions" className={cn(buttonVariants({ size: "lg" }))}>
                {signedIn ? "Open Loop Sessions" : "Start a Loop Session"}
              </Link>
              {signedIn ? null : (
                <Link href="/login" className={cn(buttonVariants({ variant: "outline", size: "lg" }))}>
                  Sign in
                </Link>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-12">
        <h2 className="font-serif text-2xl text-navy">How a Loop Session works</h2>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          You confirm each stage. Nothing is autopilot research.
        </p>
        <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {LOOP_STAGE_CATALOG.map((stage, index) => {
            const Icon = LOOP_STAGE_ICONS[stage.id];
            return (
              <li key={stage.id} className="rounded-md border bg-card p-4 shadow-sm">
                <Icon aria-hidden="true" className="size-5 text-navy" />
                <p className="mt-3 text-sm font-medium text-muted-foreground">Stage {index + 1}</p>
                <h3 className="font-serif text-xl text-navy">{stage.name}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{stage.description}</p>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="border-y bg-muted">
        <div className="mx-auto max-w-5xl px-6 py-12">
          <blockquote className="font-display text-2xl text-navy sm:text-3xl">
            Readiness is a criteria check, not a conference decision.
          </blockquote>
          <p className="mt-4 max-w-2xl text-muted-foreground">
            Independent judges and a Research Spec you confirm. Export a Spec Artifact when the
            Loop Session is ready — not a promise that a venue will accept the work.
          </p>
          <p className="mt-4 text-xs text-muted-foreground">API base: {API_BASE_URL}</p>
        </div>
      </section>
    </div>
  );
}
