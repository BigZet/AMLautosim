# Supported model packages

`resources/catboost_models/registry.json` is the server-owned inventory built
from the T00 package inventory. It records paths, release/manifest identities,
support categories and runtime consumers. `current_runtime` is the default v10
organizer-settings classifier. Four historical v10 packages remain available
for exact saved pins. `integration-v2-final` services saved v8 rounds.

The resolver checks the current package and its explicitly compatible identities,
then only registered current/legacy classifier locations. An unknown client pin
cannot construct a path or silently select a different model. Every selected
package still verifies source and artifact hashes; registry identity metadata is
not a substitute for integrity verification. Source republication refreshes the
registry's current identity after the 25-chain numerical replay gate.

`CURRENT.json` has no source/script runtime reader (`rg CURRENT.json src scripts`).
It is retained as the historical integration-v2-final release note/pointer, not
repurposed to v10. Runtime v8 and v10 pointers are explicit in the registry;
`AML_PROBABILITY_MODEL_PATH` remains an administrator-controlled override.

The broken `aml-game-attribute-context-unlimited-v1` remains in source history
and the research inventory. It is omitted from the runtime image/archive after
replaying all of its identities (own release plus compatible old identity) through
the current package: 25 chains per pin, exact features and probabilities. The
other historical packages remain in the image. Research packages and datasets
are not deleted. Corruption and unknown-pin tests fail closed.

PERF-07 remains a P3 baseline: getters continue rechecking hashes. No mtime/size
shortcut is used. A future validation-once cache requires an immutable versioned
directory contract and separate corruption/load measurements.

# Research replay

Verified historical engine: `13e01a9e95b8eff711dd04f920ac602e0815d2b6`.
This is an actual commit before organizer financial changes, not an invented tag.
Use Python 3.13.15 and this remediation branch's `requirements-ml.txt` in an
isolated environment, with `PYTHONUTF8=1` and `PYTHONHASHSEED=0`. Check out the
historical source with `core.autocrlf=false` and restore required LFS fixtures.
Run from that checkout, placing output in new directories:

```text
python -m scripts.build_aml_game_dataset_v9 --output .research-replay/game-v9-seed0 --count 600
python -m scripts.audit_aml_game_dataset_v9 .research-replay/game-v9-seed0
python -m scripts.train_aml_game_window_model_v2 .research-replay/game-v9-seed0 --output .research-replay/window-v2-seed0
```

Repeat the build to a second directory and compare `audit.json` artifact hashes.
Both verified builds produced identical hashes, 600 rows and 600 isolated groups;
readback passed all rows. Generator seed is 2051900000 (band offsets in source),
model/calibration seed 2026100400. Training/evaluation completed with 60 test rows;
MAE 0.024265268089697742 and no small-run quality-policy failures. All source,
dataset, model and lock hashes are in
[T14-research-replay.json](../verification/remediation-2026-09-25/T14-research-replay.json).
This establishes a small reproducible historical workflow. It does not reproduce
the released current model's weights, establish representative quality, or
authorize replacing that model. CatBoost binary metadata may differ on retraining;
compare held-out predictions as well as preserving each artifact's byte checksum.

The first attempted `build_aml_attribute_dataset_r1 --count 600` was stopped:
its salary supplement starts from a hard-coded external 60,000-row directory
and cannot terminate at a smaller count. No successful claim is made for it.
Current-HEAD research failures remain separately recorded in
`tests/research-baseline.json`; the known failures are neither skipped nor mixed
with the required runtime gate. Updating generators to the current financial
contract requires a separately versioned dataset and ML acceptance review.

# Static and transaction contracts

The general Ruff gate covers all Python sources. `ruff-runtime.toml` adds
B/ASYNC/UP for selected scoring/registry/worker modules; no blanket B008 exception
is introduced. `zip(batch, results, strict=True)` records the one-result-per-task
invariant. `mypy.ini` checks four selected pure modules, including scoring, with
typed definitions and checked bodies. Imported unselected modules are followed
silently; no `ignore_errors` mask is used. Widen this list as boundaries are typed.

`get_db` does not auto-commit. Services own commits; exceptions and session close
roll back pending changes. Migration heads are cached per process because images
are immutable; changing migration files requires restarting the process. Local
imports preserving lazy model loading/cycle avoidance remain intentional.
