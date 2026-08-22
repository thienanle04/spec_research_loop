export const RESEARCH_DEMO_FIXTURE = {
  title: "Research demo — claim checklist for paper summaries",
  idea: "Test whether a simple claim–evidence checklist reduces unsupported claims in LLM-generated paper summaries.",
  interpretation: {
    text: "Compare ordinary paper summarization with a workflow that splits a summary into claims and checks each claim against the source.",
    objective: "Measure whether claim-level checking reduces unsupported statements under the same inference budget.",
    target_context: "English computer-science papers with public full text.",
  },
  problem: {
    text: "LLM-generated paper summaries can contain plausible statements that are not supported by the source paper.",
  },
  researchQuestion: {
    text: "Does checking each generated claim against source evidence reduce unsupported claims compared with ordinary prompting under the same inference budget?",
  },
  gapCandidate: {
    text: "Existing refinement methods often use an overall score or free-form feedback; it remains unclear whether claim-level evidence errors provide more effective feedback within the same inference budget.",
  },
  contribution: {
    text: "A lightweight multi-round summarization method that decomposes output into claims, verifies evidence for each claim, and revises only unsupported claims.",
  },
  claim: {
    text: "Claim-level evidence feedback reduces the unsupported-claim rate without increasing the inference budget.",
  },
  evidence: {
    text: "A controlled comparison on public paper-summary datasets using unsupported-claim rate, evidence precision, and inference cost.",
  },
  constraint: {
    text: "Use public papers and models, keep the inference budget equal across conditions, and report uncertainty.",
  },
  openQuestion: {
    text: "Should evidence verification be fully automatic or include a small human-confirmation step?",
  },
} as const;
