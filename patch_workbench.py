import re

with open("frontend/features/loop/LoopSessionWorkbench.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# Add imports
imports = """import {
  ContributionStageContainer,
  ResearchStageContainer,
} from "@/features/research";
import { ClaimsEvidenceStageContainer } from "@/features/spec/ClaimsEvidenceStageContainer";
import { ExperimentPlanningStageContainer } from "@/features/spec/ExperimentPlanningStageContainer";"""

content = content.replace('import {\n  ContributionStageContainer,\n  ResearchStageContainer,\n} from "@/features/research";', imports)

# Add logic
logic_before = """const editingContributionDraft =
    editingWorkingDraft && workingDraftNode === WorkflowNode.contribution;
  const editingStructuredDraft = editingResearchDraft || editingContributionDraft;"""
logic_after = """const editingContributionDraft =
    editingWorkingDraft && workingDraftNode === WorkflowNode.contribution;
  const editingClaimsDraft =
    editingWorkingDraft && workingDraftNode === WorkflowNode.claims;
  const editingExperimentDraft =
    editingWorkingDraft && (workingDraftNode === WorkflowNode.experiment_plan || workingDraftNode === WorkflowNode.feasibility);
  const editingStructuredDraft = editingResearchDraft || editingContributionDraft || editingClaimsDraft || editingExperimentDraft;"""

content = content.replace(logic_before, logic_after)

# Add JSX
jsx_before = """) : editingContributionDraft ? (
              <ContributionStageContainer
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : ("""
jsx_after = """) : editingContributionDraft ? (
              <ContributionStageContainer
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingClaimsDraft ? (
              <ClaimsEvidenceStageContainer
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : editingExperimentDraft ? (
              <ExperimentPlanningStageContainer
                sessionId={sessionId}
                session={session}
                onRunningChange={setResearchRunning}
                onConfirmabilityChange={setResearchConfirmable}
              />
            ) : ("""

content = content.replace(jsx_before, jsx_after)

with open("frontend/features/loop/LoopSessionWorkbench.tsx", "w", encoding="utf-8") as f:
    f.write(content)
print("Patch applied successfully.")
