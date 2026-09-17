# Released educational pattern classifier

Accepted source: `aml-game-limits360-v3`. Weights and calibration are copied unchanged;
no dataset regeneration or retraining was performed for this release.

Runtime contract: v10, fixed shared history, target 360000, balance 180000,
energy/time 30/30, maximum 14 actions. Three window probabilities (2/10/60 minutes)
are averaged, then the saved sigmoid calibration is applied to the logit of that mean.
`score_kind=educational_pattern_probability`; score is `100 * p`.

`release.json` binds the model, calibration manifest, ordered feature dictionary,
fixed context, accepted offline audits and the three feature-extraction source files.
`manifest.json` is the unchanged research manifest: its historical `release_ready`
flag describes the offline stage, not the application's deployment readiness.
Server readiness loads and verifies this package; missing or changed artifacts fail closed.

Runtime verification and browser results are recorded in
`docs/verification/aml-classifier-v1/classifier-release-2026-09-17.md`.
The runtime adapter imports no research scripts and requires no external artifact disk.

SHAP is stored separately for each window in logit space. It must not be interpreted
as additive percentage-point contributions to the final calibrated score.
