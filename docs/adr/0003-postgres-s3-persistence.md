# Postgres plus S3-compatible object storage

Relational state (Accounts, Loop Sessions, cards, decision history, metadata) lives in PostgreSQL. Spec Artifacts and other binary/export payloads live in an S3-compatible object store (MinIO locally; R2/S3 in deploy), accessed through a storage port/adapter.

Normalized scholarly source text, including Counter Evidence used by a Gap Candidate, is also stored in object storage. PostgreSQL keeps its object key beside the grounded passage metadata. Deleting a Working Draft's Related Work or Gap Candidate deletes source-text objects that are no longer referenced; objects shared with immutable Stage Revisions are retained for history.

**Considered options:** SQLite-only; Postgres BYTEA for artifacts; filesystem-only blobs.

**Why:** Separates queryable workflow state from large artifacts early, matches a production-shaped student architecture, and keeps local/dev interchangeable via the S3 API.
