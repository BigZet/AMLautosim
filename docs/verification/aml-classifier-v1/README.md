# Current classifier release ? 2026-09-18

Training is complete. The accepted model is enabled by default for new games.
Existing rounds retain their exact pinned packages and results.

- Runtime package: `resources/catboost_models/aml-game-attribute-context-v1`.
- Accepted dataset: `E:/AMLautosim-artifacts/aml-probability-v1/game-attribute-context-v1r2-62000`.
- Training output: `E:/AMLautosim-artifacts/aml-probability-v1/aml-game-attribute-context-v1r2-model`.
- 62,000 chains; 28 features; one immutable shared history.
- Test grey share: 15.7963%; server/offline parity: exact on all 6,166 test chains.
- Four errors above 0.25 across 5,590 stress chains; user-approved maximum: 20.

## Authoritative reports

- [Release and metrics](attribute-context-release-2026-09-18.md)
- [Features and labeling policy](attribute-context-policy-2026-09-17.md)
- [Runtime parity](attribute-context-runtime-parity.json)
- [Attribute coverage](attribute-context-coverage.json)
- [Controlled model input/prediction changes](attribute-context-model-usage.json)
- [Contextual and neutral pairs](attribute-context-pairs.json)
- [Live readiness](attribute-context-live-readiness.json)
- [Preserved round data](attribute-context-rollout-state.json)
- [Final verification and cleanup](final-verification-2026-09-18.md)
- [Reversible cleanup manifest](final-cleanup-2026-09-18.json)

## Retained dependencies

The source datasets `game-attributes-v1r1-62000` and `game-attributes-v1-60000`
remain on E: for reproducibility. Runtime does not depend on them.
Old packaged models remain because saved rounds and regression tests use them.
Credentials, current process configuration and database backups remain in
Git-ignored `.local-run/classifier-release/`.

Superseded bulk experiments are outside the working directories, under
`E:/AMLautosim-artifacts/archive/final-cleanup-2026-09-18`.
The cleanup manifest records original and archive locations for restoration.
Permanent deletion was blocked by automatic policy review; files were archived.

Earlier dated reports are historical evidence, not the current release status.
The previous index is preserved as [infrastructure audit](infrastructure-audit-2026-09-17.md).
