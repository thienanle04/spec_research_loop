"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAccount } from "@/features/identity";
import { loginDestination } from "@/lib/auth-return";
import { getApiErrorMessage } from "@/lib/api";
import {
  useCreateSessionApiLoopSessionsPost,
  useListSessionsApiLoopSessionsGet,
} from "@/lib/api/generated/endpoints";

function recentActivity(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function SessionsDashboard() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const account = useAccount();
  const returnTo = `${pathname}${searchParams.size ? `?${searchParams.toString()}` : ""}`;

  useEffect(() => {
    if (account.ready && !account.hasToken) {
      router.replace(loginDestination(returnTo));
    }
  }, [account.hasToken, account.ready, returnTo, router]);

  const sessions = useListSessionsApiLoopSessionsGet({
    query: { enabled: account.signedIn },
  });
  const createSession = useCreateSessionApiLoopSessionsPost({
    mutation: {
      onSuccess: (response) => {
        if (response.status === 201) {
          router.push(`/sessions/${response.data.id}`);
        }
      },
    },
  });

  if (!account.ready || account.isLoading || (account.hasToken && !account.signedIn)) {
    return <p className="text-muted-foreground">Checking Account…</p>;
  }
  if (!account.hasToken) {
    return <p className="text-muted-foreground">Redirecting to sign in…</p>;
  }
  if (sessions.isLoading) {
    return <p className="text-muted-foreground">Loading Loop Sessions…</p>;
  }
  if (sessions.isError) {
    return (
      <div role="alert" className="rounded-md border border-destructive bg-card p-4">
        <p>We could not load your Loop Sessions.</p>
        <Button className="mt-3" variant="outline" onClick={() => sessions.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const rows = sessions.data?.status === 200 ? sessions.data.data : [];

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl text-navy">Loop Sessions</h1>
          <p className="mt-2 text-muted-foreground">
            Open a research project or create a new Loop Session.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link href="/research-demo">Open Research demo</Link>
          </Button>
          <Button
            disabled={createSession.isPending}
            onClick={() => createSession.mutate({ data: { title: null } })}
          >
            {createSession.isPending ? "Creating…" : "Create Loop Session"}
          </Button>
        </div>
      </div>

      {createSession.error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {getApiErrorMessage(createSession.error)}
        </p>
      ) : null}

      {rows.length === 0 ? (
        <Card className="mt-8">
          <CardHeader>
            <CardTitle>No Loop Sessions yet</CardTitle>
            <CardDescription>Create one when you are ready to shape a research idea.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <ul className="mt-8 grid gap-4 sm:grid-cols-2">
          {rows.map((session) => (
            <li key={session.id}>
              <Card className="h-full transition-shadow hover:shadow-md">
                <CardHeader>
                  <CardTitle>
                    <Link className="underline-offset-4 hover:underline" href={`/sessions/${session.id}`}>
                      {session.title || "Untitled Loop Session"}
                    </Link>
                  </CardTitle>
                  <CardDescription>Updated {recentActivity(session.updated_at)}</CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">
                    Working Draft: {session.working_draft_node.replaceAll("_", " ")}
                  </p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
