# Loop Session — page overrides

> Overrides `MASTER.md` for the in-app Loop Session workbench (grilling, related work, claims/evidence, experiment planning, judges, readiness).
> Marketing pages use `landing.md`. Unlisted rules inherit Master.

**Project:** SpecResearch Loop
**Page:** Loop Session
**Stack:** Next.js SPA + Tailwind + shadcn/ui (New York, Lucide) over FastAPI — not Server Actions

---

## Pattern (overrides Master Portfolio Grid)

Do **not** use a portfolio/masonry layout. Verified product matches:

| Source | Use for Loop Session |
|--------|----------------------|
| Productivity Tool → Drill-Down Analytics | Stage rail + detail pane |
| E-signature / Document Workflow → Document Pipeline Dashboard | Ordered stages with status (pending / in review / confirmed) |
| UX: Progress Indicators | Persistent “Stage N of 5” plus named stages |

**Stages (in order):** Grilling → Related work → Claims/evidence → Experiment planning → Independent judges → Readiness

**CTA:** Confirm / continue the current stage (accent gold). Never a “submit to conference” primary action. Copy must say the system evaluates **readiness criteria**; it does not guarantee conference acceptance.

**Layout:** 12-column Swiss grid. Left rail (2–3 cols) = stage list + readiness summary. Main (7–8 cols) = current stage. Right (optional, ≥1280px) = Spec draft / open questions.

---

## Typography (overrides Master serif-on-serif)

Master’s archive serif pairing is not a dense app. Atkinson Hyperlegible has no Vietnamese subset, so UI copy fell back to mixed system glyphs. For UI chrome and body:

| Role | Font | Why |
|------|------|-----|
| UI / body | Be Vietnam Pro (Noto Sans fallback) | Designed for Vietnamese diacritics; latin-ext + vietnamese subsets |
| Spec headings / quotes | Crimson Pro | Scholarly without slowing the workbench; load vietnamese subset |
| Spec Artifact export | EB Garamond | Keep Master serif only on exported Research Spec; load vietnamese subset |

Swiss Modernism still applies: 12-column grid, 8px base, one accent, no decoration.

---

## Color usage in the workbench

Keep Master tokens. Map them functionally:

| Token | Loop Session use |
|-------|------------------|
| `--color-primary` `#1E3A5F` | Chrome, stage rail, confirmed state |
| `--color-secondary` `#2563EB` | Links, focusable evidence, in-progress |
| `--color-accent` `#A16207` | Human confirm / “ready to continue” only |
| `--color-muted-foreground` `#475569` | Secondary labels (must stay ≥4.5:1) |

Status (never color-only): pending amber, confirmed navy, blocked destructive + label.

Primary **button** fill is accent gold (`#A16207` on `#FFFFFF`). Outline / secondary actions stay navy. Do not lift buttons or cards with `translateY` (Master anti-pattern: layout-shifting hovers).

---

## Charts (readiness)

| Question | Chart | Notes |
|----------|-------|-------|
| What fraction of readiness criteria is met? | Waffle (10×10) | Label % + pattern/symbol; color alone is insufficient |
| How close is this session to the readiness threshold? | Bullet / gauge | Number + target text beside the chart |
| How did readiness change over Loop Session versions? | Line | Only if ≥4 versions; distinct line styles per series |

---

## UX rules for this page

- Show **Stage N of 5** (or 6 including readiness) at all times.
- Failed confirms: inline field errors **and** a focusable error summary (`role="alert"`, `tabindex="-1"`) with links to invalid fields. No toast-only errors.
- Sticky stage rail / Spec pane: `scroll-padding` so keyboard focus is never fully covered (WCAG 2.2 AA).
- Grilling SSE lists: stable IDs as React keys, never array index.
- `prefers-reduced-motion`: skip scroll-reveal; render final state.
- Domain language: Research Spec, Loop Session, Account, Spec Artifact — never “paper,” “pipeline” alone, or “chat.”

---

## Icons

No verified match in the ui-ux-pro-max icon catalog for this workflow. **Keep Lucide** (already the shadcn `iconLibrary`). Outline style only at one stroke weight. No emoji as structure.

Suggested Lucide names (unverified catalog fallback): `MessageSquare` grilling, `Library` related work, `BadgeCheck` claims, `FlaskConical` experiments, `Scale` judges, `ListChecks` readiness.

---

## Stack notes (do not follow off-topic Next.js hits)

This app is a **client SPA** with Orval + TanStack Query and hand-written SSE. Do not introduce Server Actions for Loop Session mutations. Keep React Hook Form + shadcn Field (project already uses RHF). Dialog for confirmations; not Alert styled as a modal.

---

## Anti-patterns (page-specific)

- ❌ Autopilot / “agent swarm” chrome, neon SaaS glassmorphism, orange startup CTAs
- ❌ Conference-acceptance guarantees in UI copy
- ❌ Portfolio masonry, publication-gallery filtering as the main IA
- ❌ Glassmorphism on dense panels (contrast and density fail)
- ❌ Serif body text in tables, chips, or stage labels
