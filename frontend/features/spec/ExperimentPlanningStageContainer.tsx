"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  useGenerateExperimentApiSpecSessionsSessionIdExperimentPlanGeneratePost,
  useCheckFeasibilityApiSpecSessionsSessionIdFeasibilityCheckPost,
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
} from "@/lib/api/generated/endpoints";
import {
  type LoopSessionResponse,
  type ExperimentPlan,
  type FeasibilityReport,
  WorkflowNode,
} from "@/lib/api/generated/model";
import { useLoopSessionSave } from "../loop/loop-session-save";
import { Target, Activity, FlaskConical, Beaker, Lightbulb, AlertTriangle, CheckCircle2, ChevronRight } from "lucide-react";

function FormattedText({ text }: { text: string }) {
  return <span className="whitespace-pre-wrap">{text}</span>;
}

export function ExperimentPlanningStageContainer({
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
  const checkFeasibility = useCheckFeasibilityApiSpecSessionsSessionIdFeasibilityCheckPost();
  const patchDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const { queue, status } = useLoopSessionSave();
  const saving = status === "saving";
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);

  const [error, setError] = useState<string | null>(null);
  
  const narrative = session.working_draft_narrative as any;
  const experimentPlan = narrative?.plan as ExperimentPlan | undefined;
  const feasibilityReport = narrative?.feasibility_report as FeasibilityReport | undefined;
  
  const running = generateExperiment.isPending || checkFeasibility.isPending || saving;

  const isExperimentNode = session.working_draft_node === WorkflowNode.experiment_plan;
  const isFeasibilityNode = session.working_draft_node === WorkflowNode.feasibility;

  useEffect(() => {
    onRunningChange?.(running);
    return () => onRunningChange?.(false);
  }, [onRunningChange, running]);

  useEffect(() => {
    // If we are on experiment_plan, it is confirmable if experimentPlan exists.
    // If we are on feasibility, it is confirmable if feasibilityReport exists and is_feasible is true.
    if (isExperimentNode) {
      onConfirmabilityChange?.(!!experimentPlan);
    } else if (isFeasibilityNode) {
      onConfirmabilityChange?.(!!feasibilityReport?.is_feasible);
    } else {
      onConfirmabilityChange?.(false);
    }
    return () => onConfirmabilityChange?.(false);
  }, [isExperimentNode, isFeasibilityNode, experimentPlan, feasibilityReport?.is_feasible, onConfirmabilityChange]);


  function currentSession(): LoopSessionResponse {
    const cached = queryClient.getQueryData(sessionKey) as any;
    return cached?.status === 200 ? cached.data : session;
  }

  function updateSession(update: (current: LoopSessionResponse) => LoopSessionResponse) {
    queryClient.setQueryData(sessionKey, (current: any) => {
      if (!current || current.status !== 200) return current;
      return { ...current, data: update(current.data) };
    });
  }

  async function loadExperimentPlan() {
    setError(null);
    try {
      const response = await queue.enqueue(() =>
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

  async function runFeasibilityCheck() {
    setError(null);
    try {
      const response = await queue.enqueue(() =>
        checkFeasibility.mutateAsync({
          sessionId,
          data: { expected_version: currentSession().version },
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

  // If we just want to save the experiment plan text into the narrative rather than separate cards,
  // we don't necessarily need a saveSelection button here, as the generate buttons already
  // mutate the working_draft_narrative. The user will just click "Confirm" on the Workbench.
  // But we can add a manual text editor or an "Approve Plan" internal state if needed.

  return (
    <Card>
      <CardHeader>
        <CardTitle>Experiment Planning & Feasibility</CardTitle>
        <CardDescription>
          Design the experimental protocol and verify its feasibility with available resources.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="flex gap-2">
          {isExperimentNode && (
            <Button
              type="button"
              variant="outline"
              disabled={saving || running}
              onClick={() => void loadExperimentPlan()}
            >
              {experimentPlan ? "Regenerate Experiment Plan" : "Generate Experiment Plan"}
            </Button>
          )}
          
          {isFeasibilityNode && (
            <Button
              type="button"
              variant="outline"
              disabled={saving || running || !experimentPlan}
              onClick={() => void runFeasibilityCheck()}
            >
              {feasibilityReport ? "Re-check Feasibility" : "Check Feasibility"}
            </Button>
          )}
        </div>

        {error ? (
          <p role="alert" className="text-sm text-destructive">{error}</p>
        ) : null}

        {experimentPlan && (
          <div className="grid gap-4 mt-2">
            <div className="grid md:grid-cols-2 gap-4">
              <div className="bg-slate-50 border p-4 rounded-md">
                <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-2">
                  <Target className="w-4 h-4" /> Baselines
                </h4>
                <div className="flex flex-wrap gap-2">
                  {experimentPlan.baselines?.map((item: string, idx: number) => (
                    <span key={idx} className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-200 text-slate-800">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
              <div className="bg-slate-50 border p-4 rounded-md">
                <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-2">
                  <Activity className="w-4 h-4" /> Metrics
                </h4>
                <div className="flex flex-wrap gap-2">
                  {experimentPlan.metrics?.map((item: string, idx: number) => (
                    <span key={idx} className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="bg-muted/30 p-4 rounded-md border border-dashed">
              <h4 className="font-semibold text-navy mb-2">Evaluation Protocol</h4>
              <div className="text-sm text-muted-foreground leading-relaxed">
                <FormattedText text={experimentPlan.evaluation_protocol} />
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              <div className="bg-slate-50 border p-4 rounded-md">
                <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-2">
                  <FlaskConical className="w-4 h-4" /> Ablation Study
                </h4>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {experimentPlan.ablation_study?.map((item: string, idx: number) => (
                    <li key={idx} className="flex gap-2 items-start">
                      <ChevronRight className="w-4 h-4 shrink-0 mt-0.5 text-navy/50" />
                      <div><FormattedText text={item} /></div>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="bg-slate-50 border p-4 rounded-md">
                <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-2">
                  <Beaker className="w-4 h-4" /> Generalization
                </h4>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {experimentPlan.generalization?.map((item: string, idx: number) => (
                    <li key={idx} className="flex gap-2 items-start">
                      <ChevronRight className="w-4 h-4 shrink-0 mt-0.5 text-navy/50" />
                      <div><FormattedText text={item} /></div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {feasibilityReport && (
          <div className={`grid gap-4 rounded-md border p-5 text-sm ${feasibilityReport.is_feasible ? 'bg-green-50/50 border-green-200' : 'bg-red-50/50 border-red-200'}`}>
            <div className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${feasibilityReport.is_feasible ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className={`font-bold text-base ${feasibilityReport.is_feasible ? 'text-green-800' : 'text-red-800'}`}>
                {feasibilityReport.is_feasible ? "Thiết kế Khả thi (Feasible)" : "Có Rủi ro Vượt Tài nguyên"}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="block text-xs uppercase text-muted-foreground font-semibold mb-1">Ước lượng VRAM</span>
                <span className="font-medium text-foreground">{feasibilityReport.estimated_vram}</span>
              </div>
              <div>
                <span className="block text-xs uppercase text-muted-foreground font-semibold mb-1">Ước lượng Thời gian</span>
                <span className="font-medium text-foreground">{feasibilityReport.estimated_time}</span>
              </div>
            </div>
            {feasibilityReport.suggestions?.length > 0 && (
              <div className="mt-4 border-t pt-4">
                <span className="flex items-center gap-1.5 text-sm uppercase text-muted-foreground font-semibold mb-3">
                  <Lightbulb className="w-4 h-4 text-amber-500" /> Gợi ý điều chỉnh
                </span>
                <div className="grid gap-2">
                  {(feasibilityReport.suggestions as string[]).map((s, i) => (
                    <div key={i} className="flex items-start gap-2 bg-amber-50/50 border border-amber-100 p-2.5 rounded-md text-amber-900">
                      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-amber-600" />
                      <div className="leading-tight flex-1"><FormattedText text={s} /></div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {feasibilityReport?.is_feasible && (
          <p role="status" className="text-sm text-muted-foreground flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4 text-green-600" />
            Experiment plan verified. You can now confirm this stage.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
