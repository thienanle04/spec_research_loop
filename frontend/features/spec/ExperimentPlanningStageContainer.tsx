import React, { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { getApiErrorMessage } from "@/lib/api/config";
import { getGetSessionApiLoopSessionsSessionIdGetQueryKey } from "@/lib/api/generated/endpoints";
import { Target, Activity, FlaskConical, Beaker, Lightbulb, AlertTriangle, CheckCircle2, ChevronRight } from "lucide-react";
import {
  useGenerateExperimentApiSpecSpecSessionsSessionIdExperimentPlanGeneratePost,
  useCheckFeasibilityApiSpecSpecSessionsSessionIdFeasibilityCheckPost,
} from "@/lib/api/generated/endpoints";
import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";
import { useLoopSessionSave } from "../loop/loop-session-save";

const FormattedText = ({ text }: { text: string }) => {
  if (!text) return null;
  return (
    <>
      {text.split("\n").map((line, lineIndex) => {
        const strongRegex = /\*\*(.*?)\*\*/g;
        const parts = line.split(strongRegex);
        return (
          <span key={lineIndex} className="block mb-1">
            {parts.map((part, partIndex) =>
              partIndex % 2 === 1 ? <strong key={partIndex} className="font-semibold text-foreground">{part}</strong> : part
            )}
          </span>
        );
      })}
    </>
  );
};

// Assuming these types based on what the API would return
type ExperimentPlan = {
  baselines: string[];
  metrics: string[];
  evaluation_protocol: string;
};

type FeasibilityReport = {
  is_feasible: boolean;
  required_resources: string[];
  potential_bottlenecks: string[];
  mitigation_strategies: string[];
  conclusion: string;
};

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
  const generateExperiment = useGenerateExperimentApiSpecSpecSessionsSessionIdExperimentPlanGeneratePost();
  const checkFeasibility = useCheckFeasibilityApiSpecSpecSessionsSessionIdFeasibilityCheckPost();
  const { queue, status } = useLoopSessionSave();
  const sessionKey = getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId);
  const saving = status === "saving";

  const [error, setError] = useState<string | null>(null);
  
  const narrative = session.working_draft_narrative as any;
  const experimentPlan = narrative?.plan as ExperimentPlan | undefined;
  const feasibilityReport = narrative?.feasibility_report as FeasibilityReport | undefined;
  
  const running = generateExperiment.isPending || checkFeasibility.isPending || saving;

  const currentSession = () => {
    const cached = queryClient.getQueryData(sessionKey) as { status: number; data: LoopSessionResponse } | undefined;
    return cached?.status === 200 ? cached.data : session;
  };

  const updateSession = (updater: (prev: LoopSessionResponse) => LoopSessionResponse) => {
    queryClient.setQueryData(sessionKey, (old: any) => {
      if (old?.status === 200) {
        return { ...old, data: updater(old.data) };
      }
      return old;
    });
  };

  const isExperimentPlanNode = session.working_draft_node === WorkflowNode.experiment_plan;
  const isFeasibilityNode = session.working_draft_node === WorkflowNode.feasibility;

  useEffect(() => {
    onRunningChange?.(running);
  }, [running, onRunningChange]);

  useEffect(() => {
    if (isExperimentPlanNode) {
      onConfirmabilityChange?.(!!experimentPlan);
    } else if (isFeasibilityNode) {
      onConfirmabilityChange?.(!!feasibilityReport);
    } else {
      onConfirmabilityChange?.(false);
    }
    return () => onConfirmabilityChange?.(false);
  }, [isExperimentPlanNode, isFeasibilityNode, !!experimentPlan, !!feasibilityReport, onConfirmabilityChange]);

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

  async function runFeasibilityCheck() {
    setError(null);
    try {
      const response: any = await queue.enqueue(() =>
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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-serif text-navy">Experiment Planning & Feasibility</h3>
        <div className="flex gap-2">
          {isExperimentPlanNode && (
            <Button
              type="button"
              variant="outline"
              disabled={saving || running}
              onClick={() => void loadExperimentPlan()}
            >
              {experimentPlan ? "Regenerate Plan" : "Generate Plan"}
            </Button>
          )}
          
          {isFeasibilityNode && (
            <Button
              type="button"
              variant="outline"
              disabled={saving || running}
              onClick={() => void runFeasibilityCheck()}
            >
              {feasibilityReport ? "Re-check Feasibility" : "Check Feasibility"}
            </Button>
          )}
        </div>
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
                  <span key={idx} className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                    {item}
                  </span>
                ))}
              </div>
            </div>
          </div>
          
          <div className="bg-slate-50 border p-4 rounded-md">
            <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-2">
              <FlaskConical className="w-4 h-4" /> Evaluation Protocol
            </h4>
            <div className="text-sm text-slate-700 whitespace-pre-wrap">
              <FormattedText text={experimentPlan.evaluation_protocol} />
            </div>
          </div>
        </div>
      )}

      {feasibilityReport && (
        <div className="mt-6 border-t pt-6">
          <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-4">
            <Beaker className="w-4 h-4" /> Feasibility Assessment
          </h4>
          
          <div className={`p-4 rounded-md mb-4 flex items-start gap-3 ${feasibilityReport.is_feasible ? 'bg-green-50 border border-green-200' : 'bg-destructive/10 border border-destructive/20'}`}>
            {feasibilityReport.is_feasible ? (
              <CheckCircle2 className="w-5 h-5 text-green-600 mt-0.5" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-destructive mt-0.5" />
            )}
            <div>
              <p className={`font-semibold ${feasibilityReport.is_feasible ? 'text-green-800' : 'text-destructive'}`}>
                {feasibilityReport.is_feasible ? "Experiment Plan is Feasible" : "Significant Feasibility Concerns"}
              </p>
              <p className="text-sm mt-1 text-slate-700">{feasibilityReport.conclusion}</p>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-3">
              <h5 className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
                <ChevronRight className="w-4 h-4" /> Required Resources
              </h5>
              <ul className="text-sm text-slate-600 space-y-1.5 list-disc pl-5">
                {feasibilityReport.required_resources?.map((item: string, idx: number) => (
                  <li key={idx}><FormattedText text={item} /></li>
                ))}
              </ul>
            </div>
            
            <div className="space-y-3">
              <h5 className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-500" /> Potential Bottlenecks
              </h5>
              <ul className="text-sm text-slate-600 space-y-1.5 list-disc pl-5">
                {feasibilityReport.potential_bottlenecks?.map((item: string, idx: number) => (
                  <li key={idx}><FormattedText text={item} /></li>
                ))}
              </ul>
            </div>
          </div>

          {feasibilityReport.mitigation_strategies?.length > 0 && (
            <div className="mt-4 bg-slate-50 p-4 rounded-md border">
              <h5 className="text-sm font-semibold text-slate-700 flex items-center gap-1.5 mb-2">
                <Lightbulb className="w-4 h-4 text-amber-500" /> Mitigation Strategies
              </h5>
              <ul className="text-sm text-slate-600 space-y-2">
                {feasibilityReport.mitigation_strategies.map((item: string, idx: number) => (
                  <li key={idx} className="flex gap-2">
                    <span className="text-amber-500 font-bold">•</span>
                    <div className="leading-tight flex-1"><FormattedText text={item} /></div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
