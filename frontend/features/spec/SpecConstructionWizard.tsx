"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { Target, Activity, FlaskConical, Beaker, ChevronRight, Lightbulb, AlertTriangle } from "lucide-react";
import {
  useGenerateContributionApiSpecSpecContributionGeneratePost,
  useConfirmContributionApiSpecSpecContributionConfirmPost,
  useGenerateClaimsApiSpecSpecClaimsGeneratePost,
  useConfirmClaimsApiSpecSpecClaimsConfirmPost,
  useGenerateExperimentApiSpecSpecExperimentGeneratePost,
  useConfirmExperimentApiSpecSpecExperimentConfirmPost,
  useCheckFeasibilityApiSpecSpecFeasibilityCheckPost,
} from "@/lib/api/generated/endpoints";

const FormattedText = ({ text }: { text: string }) => {
  if (!text) return null;
  return (
    <>
      {text.split("\n").map((line, lineIndex) => {
        if (!line.trim()) return null;
        const parts = line.split(/(\*\*.*?\*\*)/g);
        return (
          <div key={lineIndex} className="mb-1 last:mb-0">
            {parts.map((part, i) => {
              if (part.startsWith("**") && part.endsWith("**")) {
                return (
                  <strong key={i} className="font-semibold text-foreground">
                    {part.slice(2, -2)}
                  </strong>
                );
              }
              return <span key={i}>{part}</span>;
            })}
          </div>
        );
      })}
    </>
  );
};

export function SpecConstructionWizard({ sessionId }: { sessionId: string }) {
  const [step, setStep] = useState<number>(1);
  const [selectedContribution, setSelectedContribution] = useState<string>("");
  const [claims, setClaims] = useState<any[]>([]);
  const [experimentPlan, setExperimentPlan] = useState<any | null>(null);
  const [feasibilityReport, setFeasibilityReport] = useState<any | null>(null);

  const genContrib = useGenerateContributionApiSpecSpecContributionGeneratePost();
  const confirmContrib = useConfirmContributionApiSpecSpecContributionConfirmPost();

  const genClaims = useGenerateClaimsApiSpecSpecClaimsGeneratePost();
  const confirmClaims = useConfirmClaimsApiSpecSpecClaimsConfirmPost();

  const genExp = useGenerateExperimentApiSpecSpecExperimentGeneratePost();
  const confirmExp = useConfirmExperimentApiSpecSpecExperimentConfirmPost();

  const checkFeas = useCheckFeasibilityApiSpecSpecFeasibilityCheckPost();

  async function handleGenerateContribution() {
    await genContrib.mutateAsync();
  }

  async function handleConfirmContribution() {
    if (!selectedContribution) return;
    await confirmContrib.mutateAsync({
      data: { session_id: sessionId, confirmed_data: { contribution: selectedContribution } },
    });
    setStep(2);
  }

  async function handleGenerateClaims() {
    const res = await genClaims.mutateAsync({ params: { contribution_desc: selectedContribution } });
    const data = res.data as any;
    if (data?.cards) {
      setClaims(data.cards);
    }
  }

  async function handleConfirmClaims() {
    await confirmClaims.mutateAsync({
      data: { session_id: sessionId, confirmed_data: { claims } },
    });
    setStep(3);
  }

  async function handleGenerateExperiment() {
    // claims map is any, we just pass the array
    const res = await genExp.mutateAsync({ data: claims as any });
    const data = res.data as any;
    if (data?.plan) {
      setExperimentPlan(data.plan);
    }
  }

  async function handleConfirmExperiment() {
    await confirmExp.mutateAsync({
      data: { session_id: sessionId, confirmed_data: { experiment: experimentPlan } },
    });
    setStep(4);
  }

  async function handleCheckFeasibility() {
    const planDesc = JSON.stringify(experimentPlan);
    const res = await checkFeas.mutateAsync({ params: { plan_desc: planDesc } });
    const data = res.data as any;
    if (data) {
      setFeasibilityReport(data);
    }
  }

  return (
    <div className="grid gap-6">
      {/* STEP 1: CONTRIBUTION */}
      {step >= 1 && (
        <Card className={step === 1 ? "border-navy shadow-md" : "opacity-70"}>
          <CardHeader>
            <CardTitle>Step 1: Choose Contribution</CardTitle>
            <CardDescription>Generate and pick a contribution direction based on the Research Gap.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {step === 1 && (
              <div className="flex gap-2">
                <Button onClick={handleGenerateContribution} disabled={genContrib.isPending}>
                  {genContrib.isPending ? "Generating..." : "Generate Options"}
                </Button>
              </div>
            )}

            {((genContrib.data?.data as any)?.options) && (
              <div className="grid gap-4">
                {((genContrib.data?.data as any).options as any[]).map((opt) => (
                  <div
                    key={opt.id}
                    className={`rounded-md border p-4 cursor-pointer ${selectedContribution === opt.description ? "bg-muted border-navy" : "hover:bg-muted/50"
                      }`}
                    onClick={() => step === 1 && setSelectedContribution(opt.description)}
                  >
                    <p className="font-medium">{opt.title} ({opt.id})</p>
                    <div className="text-sm text-muted-foreground"><FormattedText text={opt.description} /></div>
                  </div>
                ))}
              </div>
            )}

            {step === 1 && selectedContribution && (
              <Button onClick={handleConfirmContribution} disabled={confirmContrib.isPending}>
                Confirm Contribution
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* STEP 2: CLAIMS & EVIDENCE */}
      {step >= 2 && (
        <Card className={step === 2 ? "border-navy shadow-md" : "opacity-70"}>
          <CardHeader>
            <CardTitle>Step 2: Claims & Evidence</CardTitle>
            <CardDescription>Generate claims to support your contribution.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {step === 2 && (
              <div className="flex gap-2">
                <Button onClick={handleGenerateClaims} disabled={genClaims.isPending}>
                  {genClaims.isPending ? "Generating..." : "Generate Claims"}
                </Button>
              </div>
            )}

            {claims.length > 0 && (
              <div className="grid gap-4">
                {claims.map((c, i) => (
                  <div key={i} className="rounded-md border p-4 bg-card">
                    <div className="flex gap-2 mb-2"><strong className="shrink-0 text-navy">Claim:</strong> <div className="font-medium"><FormattedText text={c.claim} /></div></div>
                    <div className="text-sm flex gap-2 text-muted-foreground"><strong className="shrink-0">Baseline:</strong> <div><FormattedText text={c.baseline} /></div></div>
                    <div className="text-sm flex gap-2 text-muted-foreground"><strong className="shrink-0">Metric:</strong> <div><FormattedText text={c.metric} /></div></div>
                    <div className="text-sm flex gap-2 text-muted-foreground"><strong className="shrink-0">Evidence:</strong> <div><FormattedText text={c.evidence} /></div></div>
                    {c.rejection_condition && (
                      <div className="text-sm flex gap-2 mt-2 pt-2 border-t text-amber-700">
                        <strong className="shrink-0">Rejection condition:</strong>
                        <div><FormattedText text={c.rejection_condition} /></div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {step === 2 && claims.length > 0 && (
              <Button onClick={handleConfirmClaims} disabled={confirmClaims.isPending}>
                Confirm Claims
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* STEP 3: EXPERIMENT PLAN */}
      {step >= 3 && (
        <Card className={step === 3 ? "border-navy shadow-md" : "opacity-70"}>
          <CardHeader>
            <CardTitle>Step 3: Experiment Plan</CardTitle>
            <CardDescription>Design experiments to validate the claims.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {step === 3 && (
              <div className="flex gap-2">
                <Button onClick={handleGenerateExperiment} disabled={genExp.isPending}>
                  {genExp.isPending ? "Generating..." : "Generate Plan"}
                </Button>
              </div>
            )}

            {experimentPlan && (
              <div className="grid gap-6 rounded-md border p-5 text-sm bg-card">
                {/* Baselines & Metrics */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-1">
                      <Target className="w-4 h-4" /> Baselines
                    </h4>
                    <p className="text-xs text-muted-foreground mb-3 leading-tight">Các phương pháp cơ sở hiện có để đối chiếu và so sánh.</p>
                    <div className="flex flex-wrap gap-2">
                      {experimentPlan.baselines?.map((item: string, idx: number) => (
                        <span key={idx} className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 border border-slate-200 shadow-sm">
                          {item}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-1">
                      <Activity className="w-4 h-4" /> Metrics
                    </h4>
                    <p className="text-xs text-muted-foreground mb-3 leading-tight">Các thang đo độ tin cậy được dùng để đánh giá kết quả.</p>
                    <div className="flex flex-wrap gap-2">
                      {experimentPlan.metrics?.map((item: string, idx: number) => (
                        <span key={idx} className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200 shadow-sm">
                          {item}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Evaluation Protocol */}
                <div className="bg-muted/30 p-4 rounded-md border border-dashed">
                  <h4 className="font-semibold text-navy mb-1">Evaluation Protocol (Quy trình đánh giá)</h4>
                  <p className="text-xs text-muted-foreground mb-3">Mô tả cách thức dữ liệu được chuẩn bị và chạy thí nghiệm để đảm bảo công bằng.</p>
                  <div className="text-muted-foreground leading-relaxed"><FormattedText text={experimentPlan.evaluation_protocol} /></div>
                </div>

                {/* Ablation & Generalization */}
                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-1">
                      <FlaskConical className="w-4 h-4" /> Ablation Study
                    </h4>
                    <p className="text-xs text-muted-foreground mb-3 leading-tight">Thí nghiệm loại bỏ dần từng thành phần để chứng minh vai trò của chúng.</p>
                    <ul className="space-y-2">
                      {experimentPlan.ablation_study?.map((item: string, idx: number) => (
                        <li key={idx} className="flex gap-2 items-start text-muted-foreground bg-muted/10 p-2.5 rounded border border-muted shadow-sm">
                          <ChevronRight className="w-4 h-4 shrink-0 mt-0.5 text-navy/50" />
                          <div className="leading-snug flex-1"><FormattedText text={item} /></div>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4 className="flex items-center gap-1.5 font-semibold text-navy mb-1">
                      <Beaker className="w-4 h-4" /> Generalization
                    </h4>
                    <p className="text-xs text-muted-foreground mb-3 leading-tight">Kiểm tra khả năng mở rộng của phương pháp trên domain hay dataset khác.</p>
                    <ul className="space-y-2">
                      {experimentPlan.generalization?.map((item: string, idx: number) => (
                        <li key={idx} className="flex gap-2 items-start text-muted-foreground bg-muted/10 p-2.5 rounded border border-muted shadow-sm">
                          <ChevronRight className="w-4 h-4 shrink-0 mt-0.5 text-navy/50" />
                          <div className="leading-snug flex-1"><FormattedText text={item} /></div>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {step === 3 && experimentPlan && (
              <Button onClick={handleConfirmExperiment} disabled={confirmExp.isPending}>
                Confirm Plan
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* STEP 4: FEASIBILITY */}
      {step >= 4 && (
        <Card className={step === 4 ? "border-navy shadow-md" : ""}>
          <CardHeader>
            <CardTitle>Step 4: Feasibility Check</CardTitle>
            <CardDescription>Check if the plan fits hardware/budget constraints.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="flex gap-2">
              <Button onClick={handleCheckFeasibility} disabled={checkFeas.isPending}>
                {checkFeas.isPending ? "Checking..." : "Check Feasibility"}
              </Button>
            </div>

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

            {feasibilityReport && (
              <Button variant="outline" onClick={() => alert("Spec Construction Complete!")}>
                Finish Workflow
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
