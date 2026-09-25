# Machine evidence and historical archives

Narrative acceptance reports live in `docs/verification`. New raw logs, JUnit and
notebooks belong here or in versioned CI artifacts, with the report linking to
an immutable run and checksum. Private run state, credentials and DB dumps never
belong in either tree.

`historical-evidence-manifest.json` indexes existing tracked logs/JUnit/notebooks
separately from reports. Their original paths are retained: old report links and
notebook working directories remain valid, and historical logs are not edited.
Restore a missing indexed file from the source commit with `git restore
--source=<commit> -- <path>`, then compare SHA-256. For LFS-backed artifacts,
`git lfs pull --include=<exact-path>` restores the bytes before checksum checking.
No Git history or archived research artifact was removed or rewritten.

Current load/browser/scoring JSON summaries are acceptance evidence linked by
reports; long private execution logs remain in the ignored plan workspace.
