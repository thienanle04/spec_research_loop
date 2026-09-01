# Opening an empty or Stale Workflow Node runs recompute-prepare

The SPA does not show Start/Recompute. Selecting an available empty or Stale Workflow Node (rail, URL, or stage path) calls `recompute-prepare` for that Loop Stage. Generate stays an explicit Account action. Confirm still auto-prepares the next stage. Spec Draft keeps Continue. Skip when the Working Draft is already that node, is a current node in the same Loop Stage, or is not current — so in-progress work and Edit-interpretation are not reset. Supersedes ADR 0010’s “user confirms recompute of affected Loop Stages”; LLM and Judge work still do not auto-run.

**Considered options:** auto-generate as well (rejected — human-in-the-loop); auto-prepare only after Confirm (rail-jump could not open empty work); keep an explicit Recompute for Stale (rejected); stage-level prepare on mixed current+Stale (would block reading a current Node Head).

**Why:** Sequential Confirm already ran the same command. Opening the node that needs work is the Account’s choice to recompute that Loop Stage; generating remains costly and explicit.
