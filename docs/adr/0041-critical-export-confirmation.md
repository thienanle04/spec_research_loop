# Critical Export Confirmation instead of blocking export on CRITICAL

CRITICAL Judge Issues still fail Readiness and still never un-mint a Spec Version (ADR 0039). They no longer 409-block Spec Artifact export or Export Scratch download. Each such export or download while the current Aggregator Report has any CRITICAL Issue is a recorded Critical Export Confirmation Decision; there is no session- or Spec-Version-scoped skip. Spec Artifact remains the unedited Valid Spec Version; Export Scratch is a separate last-write-wins projection the Account may edit and download as markdown or PDF without minting or touching Cards.

**Status:** accepted; supersedes ADR 0039’s “block Spec Artifact export while CRITICAL remains” and its rejection of override-and-export.

**Considered options:** keep the 409 gate (rejected — Account must be able to take a file out of the loop while still seeing Readiness fail); one ack per Spec Version (rejected — later downloads would be unaudited); UI dialog with no Decision (rejected — history would not show export-while-blocked); treat Export Scratch as Spec Artifact (rejected — Judges evaluated the Valid Spec Version, not the edited projection).

**Why:** TOPIC Bước 10 is still how to *fix* the Research Spec (path A: reopen a Workflow Node). Export is allowed to leave the loop as a distinct, audited act so a blocked session can still produce a submission file without pretending Readiness passed.
