import React, { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  useGenerateExperimentApiSpecSessionsSessionIdExperimentPlanGeneratePost,
} from "@/lib/api/generated/endpoints";
import {
  type LoopSessionResponse,
} from "@/lib/api/generated/model";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { Target, Activity, FlaskConical, AlertTriangle, FileText } from "lucide-react";

type ExperimentItem = {
  claim: string;
  action: string;
  objective: string;
  significance: string;
};

type ExperimentPlan = {
  experiments: ExperimentItem[];
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

export function ExperimentPlanStageContainer({
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
  const generateExperiment = useGenerateExperimentApiSpecSessionsSessionIdExperimentPlanGeneratePost();
  const { queue, status } = useLoopSessionSave();
  const saving = status === "saving";
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  const [error, setError] = useState<string | null>(null);
  
  const narrative = session.working_draft_narrative as any;
  const expHead = session.node_heads?.find(h => h.node === "experiment_plan");
  const expRev = expHead?.stage_revision_id ? (session as any).stage_revisions?.find((r: any) => r.id === expHead.stage_revision_id) : null;
  const committedNarrative = expRev?.narrative as any;
  
  const experimentPlan = (narrative?.plan || committedNarrative?.plan) as ExperimentPlan | undefined;
  
  const running = generateExperiment.isPending || saving;

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
    onConfirmabilityChange?.(!!experimentPlan);
    return () => onConfirmabilityChange?.(false);
  }, [!!experimentPlan, onConfirmabilityChange]);

  async function loadExperimentPlan() {
    setError(null);
    try {
      const response: any = await queue.enqueue(() =>
        generateExperiment.mutateAsync({
          sessionId,
          data: { expected_version: currentSession().version },
        })
      );
      if (response.status !== 200) throw new Error("Could not generate experiment plan");
      updateSession((current) => ({
        ...current,
        version: response.data.version,
        working_draft_narrative: { ...current.working_draft_narrative as object, plan: response.data.plan },
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
              <FlaskConical className="w-5 h-5 text-indigo-600" /> Experiment Planning
            </CardTitle>
            <CardDescription>
              Plan your experiments to validate the claims.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="default"
              disabled={saving || running}
              onClick={() => void loadExperimentPlan()}
            >
              {experimentPlan ? "Regenerate Plan" : "Generate Plan"}
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

        {(experimentPlan?.experiments?.length ?? 0) > 0 && (
          <div className="space-y-6">
            {experimentPlan?.experiments?.map((exp: ExperimentItem, idx: number) => (
              <div key={idx} className="bg-white border rounded-lg shadow-sm overflow-hidden">
                <div className="bg-slate-50 border-b px-5 py-3">
                  <h4 className="flex items-start gap-2 font-semibold text-slate-800 text-sm">
                    <FileText className="w-4 h-4 text-slate-500 mt-0.5 shrink-0" />
                    <span className="leading-snug">{exp.claim}</span>
                  </h4>
                </div>
                <div className="p-6 space-y-6">
                  <div>
                    <h5 className="text-xs uppercase tracking-wider font-bold text-slate-500 mb-2.5 flex items-center gap-1.5">
                      <Target className="w-4 h-4 text-indigo-500" /> Action (Làm gì - Thời gian/Mẫu)
                    </h5>
                    <div className="text-sm text-slate-800 bg-indigo-50/40 p-4 rounded-md border border-indigo-100/60 shadow-sm">
                      <FormattedText text={exp.action} />
                    </div>
                  </div>
                  
                  <div className="grid md:grid-cols-2 gap-6">
                    <div>
                      <h5 className="text-xs uppercase tracking-wider font-bold text-slate-500 mb-2.5 flex items-center gap-1.5">
                        <Activity className="w-4 h-4 text-emerald-500" /> Objective (Mục tiêu)
                      </h5>
                      <div className="text-sm text-slate-800 bg-emerald-50/40 p-4 rounded-md border border-emerald-100/60 h-full shadow-sm">
                        <FormattedText text={exp.objective} />
                      </div>
                    </div>
                    <div>
                      <h5 className="text-xs uppercase tracking-wider font-bold text-slate-500 mb-2.5 flex items-center gap-1.5">
                        <AlertTriangle className="w-4 h-4 text-amber-500" /> Significance (Ý nghĩa)
                      </h5>
                      <div className="text-sm text-slate-800 bg-amber-50/40 p-4 rounded-md border border-amber-100/60 h-full shadow-sm">
                        <FormattedText text={exp.significance} />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
