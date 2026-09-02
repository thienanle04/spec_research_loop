# Export Scratch is an opaque markdown document

Export Scratch is stored and downloaded as one markdown string (JSONB `{ markdown }`), not thirteen section records. First paint is still a paper-shaped projection (`Source Spec Version`, optional validity banner, `## N. Title` plus Card bodies; heading catalog and Claim/Evidence pairing are ADR 0045); later edits may delete those headings. The stored markdown is the `.md` file. PDF renders that markdown as GFM plus `$`/`$$` math (same features as the Readiness preview, not pixel-identical). Diffs are whole-document text. Legacy `{ sections }` rows migrate to markdown with the Spec Version header and headings, without stamping today’s Readiness banner.

**Status:** accepted

**Considered options:** keep section JSON and only add a preview (rejected — Account asked for markdown text, not twelve boxes); parse the editor back into thirteen sections on save (rejected — deleting a heading has nowhere to live); inject the validity banner at every download (rejected — buffer would not be the file); print the preview HTML with Chromium so PDF matches pixels (rejected — too heavy for the download endpoint).

**Why:** Overlay editing is paper authoring. Structured section ids were an implementation leftover from projection, not a domain invariant. Baking the banner at projection (Q9 identity) means a later Readiness fail does not rewrite an already-edited file.
