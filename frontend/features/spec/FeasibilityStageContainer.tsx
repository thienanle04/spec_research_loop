import React, { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  useCheckFeasibilityApiSpecSessionsSessionIdFeasibilityCheckPost,
} from "@/lib/api/generated/endpoints";
import {
  type LoopSessionResponse,
} from "@/lib/api/generated/model";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { Beaker, CheckCircle2, ChevronRight, AlertTriangle } from "lucide-react";

type ExperimentItem = {
  claim: string;
  action: string;
  objective: string;
  significance: string;
};

type ExperimentPlan = {
  experiments: ExperimentItem[];
};

type FeasibilityReport = {
  is_feasible: boolean;
  required_resources: string[];
  potential_bottlenecks: string[];
  mitigation_strategies: string[];
  conclusion: string;
};

function FormattedText({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="space-y-2">
      {text.split("\n").filter(l => l.trim().length > 0).map((line, lineIndex) => {
        const trimmed = line.trim();
        const bulletMatch = trimmed.match(/^[-*]\s+(.*)$/);
        const numberMatch = trimmed.match(/^(\d+\.)\s+(.*)$/);

        let prefix = null;
        let contentStr = trimmed;

        if (bulletMatch) {
          prefix = <span className="text-slate-400 font-bold w-4 inline-block mt-0.5 shrink-0">•</span>;
          contentStr = bulletMatch[1];
        } else if (numberMatch) {
          prefix = <span className="text-slate-500 font-medium w-6 inline-block shrink-0 mt-0.5">{numberMatch[1]}</span>;
          contentStr = numberMatch[2];
        }

        const strongRegex = /\*\*(.*?)\*\*/g;
        const parts = contentStr.split(strongRegex);
        const content = parts.map((part, partIndex) =>
          partIndex % 2 === 1 ? <strong key={partIndex} className="font-semibold text-foreground">{part}</strong> : part
        );

        if (prefix) {
          return (
            <div key={lineIndex} className="flex items-start gap-1">
              {prefix}
              <div className="flex-1 leading-relaxed">{content}</div>
            </div>
          );
        }

        return (
          <p key={lineIndex} className="leading-relaxed">
            {content}
          </p>
        );
      })}
    </div>
  );
}

export function FeasibilityStageContainer({
  sessionId,
  session,
  onRunningChange,
  onConfirmabilityChange,
}: {
  sessionId: string;
  session: LoopSessionResponse;
  onRunningChange?: (running: boolean) => void;
  onConfirmabilityChange?: (confirmable: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const checkFeasibility = useCheckFeasibilityApiSpecSessionsSessionIdFeasibilityCheckPost();
  const { queue, status } = useLoopSessionSave();
  const saving = status === "saving";
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  const [error, setError] = useState<string | null>(null);
  
  const narrative = session.working_draft_narrative as any;
  const expHead = session.node_heads?.find(h => h.node === "experiment_plan");
  const expRev = expHead?.stage_revision_id ? (session as any).stage_revisions?.find((r: any) => r.id === expHead.stage_revision_id) : null;
  const committedNarrative = expRev?.narrative as any;
  
  const experimentPlan = (narrative?.plan || committedNarrative?.plan) as ExperimentPlan | undefined;
  const feasibilityReport = narrative?.feasibility_report as FeasibilityReport | undefined;
  
  const running = checkFeasibility.isPending || saving;

  function currentSession(): LoopSessionResponse {
    const cached = queryClient.getQueryData(sessionKey) as any;
    return cached?.status === 200 ? cached.data : session;
  }

  function updateSession(updater: (prev: LoopSessionResponse) => LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, (old: any) => {
      if (old?.status === 200) {
        return { ...old, data: updater(old.data) };
      }
      return old;
    });
  }

  useEffect(() => {
    onRunningChange?.(running);
  }, [running, onRunningChange]);

  useEffect(() => {
    onConfirmabilityChange?.(!!feasibilityReport);
    return () => onConfirmabilityChange?.(false);
  }, [!!feasibilityReport, onConfirmabilityChange]);

  async function runFeasibilityCheck() {
    setError(null);
    try {
      const response: any = await queue.enqueue(() =>
        checkFeasibility.mutateAsync({
          sessionId,
          data: { expected_version: currentSession().version, plan: experimentPlan as any },
        })
      );
      if (response.status !== 200) throw new Error("Could not check feasibility");
      updateSession((current) => ({
        ...current,
        version: response.data.version,
        working_draft_narrative: { ...current.working_draft_narrative as object, feasibility_report: response.data.report },
      }));
    } catch (caught) {
      setError(getApiErrorMessage(caught));
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <CardTitle className="text-xl font-serif text-navy flex items-center gap-2">
              <Beaker className="w-5 h-5 text-indigo-600" /> Feasibility Assessment
            </CardTitle>
            <CardDescription>
              Check the feasibility of your experiment plan.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="default"
              disabled={saving || running || !experimentPlan}
              onClick={() => void runFeasibilityCheck()}
            >
              {feasibilityReport ? "Re-check Feasibility" : "Check Feasibility"}
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="grid gap-5">
        {error ? (
          <div className="p-4 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> {error}
          </div>
        ) : null}
        
        {!experimentPlan && !error ? (
          <div className="p-4 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> No experiment plan found. Please go back to the Experiment Plan stage to generate it.
          </div>
        ) : null}

        {feasibilityReport && (
          <div className="mt-4">
            <div className={`p-4 rounded-lg mb-6 flex items-start gap-3 shadow-sm ${feasibilityReport.is_feasible ? 'bg-emerald-50 border border-emerald-200' : 'bg-destructive/10 border border-destructive/20'}`}>
              {feasibilityReport.is_feasible ? (
                <CheckCircle2 className="w-6 h-6 text-emerald-600 mt-0.5 shrink-0" />
              ) : (
                <AlertTriangle className="w-6 h-6 text-destructive mt-0.5 shrink-0" />
              )}
              <div>
                <p className={`font-semibold text-base ${feasibilityReport.is_feasible ? 'text-emerald-800' : 'text-destructive'}`}>
                  {feasibilityReport.is_feasible ? "Experiment Plan is Feasible" : "Significant Feasibility Concerns"}
                </p>
                <p className="text-sm mt-1.5 text-slate-700 leading-relaxed">{feasibilityReport.conclusion}</p>
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-6 mb-6">
              <div className="bg-white border rounded-lg p-5 shadow-sm">
                <h5 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5 mb-3">
                  <ChevronRight className="w-4 h-4 text-indigo-500" /> Required Resources
                </h5>
                <ul className="text-sm text-slate-600 space-y-2 list-none">
                  {feasibilityReport.required_resources?.map((item: string, idx: number) => (
                    <li key={idx} className="flex gap-2">
                      <span className="text-indigo-400 font-bold mt-0.5">•</span>
                      <span className="leading-snug"><FormattedText text={item} /></span>
                    </li>
                  ))}
                </ul>
              </div>
              
              <div className="bg-white border rounded-lg p-5 shadow-sm">
                <h5 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5 mb-3">
                  <AlertTriangle className="w-4 h-4 text-amber-500" /> Potential Bottlenecks
                </h5>
                <ul className="text-sm text-slate-600 space-y-2 list-none">
                  {feasibilityReport.potential_bottlenecks?.map((item: string, idx: number) => (
                    <li key={idx} className="flex gap-2">
                      <span className="text-amber-500 font-bold mt-0.5">•</span>
                      <span className="leading-snug"><FormattedText text={item} /></span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {feasibilityReport.mitigation_strategies?.length > 0 && (
              <div className="bg-white border rounded-lg p-5 shadow-sm">
                <h5 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5 mb-3">
                  <CheckCircle2 className="w-4 h-4 text-emerald-500" /> Mitigation Strategies
                </h5>
                <ul className="text-sm text-slate-600 space-y-2 list-none">
                  {feasibilityReport.mitigation_strategies.map((item: string, idx: number) => (
                    <li key={idx} className="flex gap-2">
                      <span className="text-emerald-500 font-bold mt-0.5">✓</span>
                      <span className="leading-snug"><FormattedText text={item} /></span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
