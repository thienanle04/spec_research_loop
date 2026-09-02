# Export Scratch first paint pairs Claim and Evidence Cards

New Export Scratch first paint uses twelve `## N. Title` headings. Claim and Evidence Cards share `Claims and Evidence` as generate pairs (labeled baseline, metric, expected evidence, rejection condition; unpaired evidence last). Each experiment is the claim as `###` plus labeled Action, Objective, and Significance. Existing `{ markdown }` buffers are not rewritten. Legacy `{ sections }` concatenate the old claims and evidence bodies under the new heading, without re-pairing. Spec Draft and Clarification Review stay unchanged. Card kinds and Confirm `claims` stay ADR 0044.

**Status:** accepted

**Considered options:** keep two paper H2s after Confirm already merged (rejected — paper still split what the Account authored as pairs); reproject edited buffers (rejected — overlay is the downloaded file); parse Claim Card `text` blobs for field labels (rejected — unstable, duplicates metadata already on save).

**Why:** ADR 0042 made storage opaque markdown but left first paint as thirteen concatenated dumps, so Action/Objective/Significance were present without roles and Evidence was a second dump. Pairing uses generate `metadata.id` / `source_claim_id`, not Card uuids. Old buffers diverge on purpose.
