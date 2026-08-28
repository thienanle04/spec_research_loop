import {
  BadgeCheck,
  FileText,
  FlaskConical,
  Library,
  Lightbulb,
  ListChecks,
  MessageSquare,
  Scale,
  ScanSearch,
} from "lucide-react";

import { LoopStage } from "@/lib/api/generated/model";

export const LOOP_STAGE_ICONS = {
  [LoopStage.grilling]: MessageSquare,
  [LoopStage.related_work]: Library,
  [LoopStage.gap]: ScanSearch,
  [LoopStage.contribution]: Lightbulb,
  [LoopStage.claims_evidence]: BadgeCheck,
  [LoopStage.experiment_planning]: FlaskConical,
  [LoopStage.spec_draft]: FileText,
  [LoopStage.independent_judges]: Scale,
  [LoopStage.readiness]: ListChecks,
} as const;
