"""Independent structural/numerical validation of stored release evidence."""

import math

RELEASE_ARTIFACTS = {
    "dataset-manifest.json",
    "dataset-audit.json",
    "training-manifest.json",
    "training-stability.json",
    "training-baselines.json",
    "calibration-manifest.json",
    "calibration-selection.json",
    "test-ids.json",
}


def require(condition, message):
    if not condition:
        raise ValueError("Release evidence: " + message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_main_test(report):
    """Recompute acceptance predicates instead of trusting saved true booleans."""
    from scipy.stats import beta

    require(isinstance(report, dict), "missing main-test report")
    prior = report.get("reference_prior")
    require(number(prior) and 0 < prior < 1, "missing frozen training prior")
    require(
        report.get("scope") == "main-test-quantitative-gates-only",
        "invalid main-test scope",
    )
    bootstrap = report.get("bootstrap", {})
    require(
        bootstrap.get("repeats") == 2000
        and bootstrap.get("seed") == 2026091601
        and bootstrap.get("unit") == "provenance-group"
        and bootstrap.get("interval") == "95%-percentile",
        "invalid group-bootstrap protocol",
    )
    support = report.get("support", {})
    rows, groups = report.get("rows"), report.get("groups")
    require(
        type(rows) is int and type(groups) is int and 0 < groups <= rows,
        "invalid main-test population counts",
    )
    require(
        all(
            type(support.get(key)) is int and support[key] >= minimum
            for key, minimum in {
                "class_0": 60,
                "class_1": 60,
                "low": 30,
                "high": 30,
            }.items()
        ),
        "insufficient independent support",
    )
    require(
        all(value <= groups for value in support.values()),
        "support exceeds main-test groups",
    )
    expected_gates = {
        "bootstrap_protocol",
        "test_class_group_support",
        "test_tail_group_support",
    }
    metrics_names = {
        "roc_auc",
        "average_precision",
        "class_prior",
        "log_loss",
        "brier",
        "ece",
        "grey",
        "false_high",
        "false_low",
        "precision_high",
        "npv_low",
    }
    point_rules = {
        "roc_auc": (0.9, 1),
        "ece": (0, 0.05),
        "grey": (0, 0.2),
        "false_high": (0, 0.05),
        "false_low": (0, 0.05),
        "precision_high": (0.9, 1),
        "npv_low": (0.9, 1),
    }
    require(
        set(report.get("aggregations", {})) == {"row", "group"},
        "missing row/group aggregations",
    )
    for axis, aggregation in report["aggregations"].items():
        metrics, constant, ci = (
            aggregation.get(name, {})
            for name in ("metrics", "constant_prior", "confidence_intervals")
        )
        require(
            set(metrics) == metrics_names and all(number(v) for v in metrics.values()),
            "missing/nonfinite metrics",
        )
        require(
            all(0 <= value <= 1 for key, value in metrics.items() if key != "log_loss")
            and metrics["log_loss"] >= 0,
            "metric outside valid range",
        )
        require(
            all(
                lo - 1e-12 <= metrics[name] <= hi + 1e-12
                for name, (lo, hi) in point_rules.items()
            ),
            "point metric gate failed",
        )
        require(
            0 <= metrics["class_prior"] <= 1
            and metrics["average_precision"] > metrics["class_prior"],
            "AP does not beat prior",
        )
        require(
            all(
                number(constant.get(name)) and 0 <= metrics[name] < constant[name]
                for name in ("log_loss", "brier")
            ),
            "model does not beat constant prior",
        )
        q = metrics["class_prior"]
        expected_constant = {
            "brier": q * (1 - prior) ** 2 + (1 - q) * prior**2,
            "log_loss": -q * math.log(prior) - (1 - q) * math.log1p(-prior),
        }
        require(
            all(
                abs(constant[key] - value) <= 1e-12
                for key, value in expected_constant.items()
            ),
            "constant baseline differs from frozen prior",
        )
        require(set(ci) == metrics_names, "missing confidence intervals")
        require(
            all(
                number(v.get("lower"))
                and number(v.get("upper"))
                and 0 <= v["lower"] <= v["upper"]
                and (key == "log_loss" or v["upper"] <= 1)
                and number(v.get("valid_fraction"))
                and 0.95 <= v["valid_fraction"] <= 1
                and v.get("sufficient") is True
                for key, v in ci.items()
            ),
            "invalid bootstrap intervals",
        )
        require(
            ci["false_high"]["upper"] <= 0.1 + 1e-12
            and ci["false_low"]["upper"] <= 0.1 + 1e-12
            and ci["precision_high"]["lower"] >= 0.85 - 1e-12
            and ci["npv_low"]["lower"] >= 0.85 - 1e-12,
            "confidence interval gate failed",
        )
        expected_gates.update(
            axis + ":" + name
            for name in (
                "roc_auc",
                "average_precision",
                "log_loss",
                "brier",
                "ece",
                "grey",
                "false_high",
                "false_low",
                "precision_high",
                "npv_low",
                "ci_defined",
                "false_high_ci",
                "false_low_ci",
                "precision_high_ci",
                "npv_low_ci",
            )
        )
    events = report.get("group_events", {})
    event_support = {
        "false_high": "class_0",
        "false_low": "class_1",
        "high_error_event": "high",
        "low_error_event": "low",
    }
    require(set(events) == set(event_support), "missing group-event bounds")
    for name, event in events.items():
        n, k = event.get("groups"), event.get("groups_with_error")
        require(
            type(n) is int
            and type(k) is int
            and n == support[event_support[name]]
            and 0 <= k <= n,
            "invalid group-event counts",
        )
        upper = 1.0 if k == n else float(beta.ppf(0.95, k + 1, n - k))
        require(
            number(event.get("upper_95")) and abs(event["upper_95"] - upper) <= 1e-12,
            "incorrect group-event confidence bound",
        )
        require(
            upper <= (0.15 if name.endswith("error_event") else 0.1) + 1e-12,
            "group-event gate failed",
        )
        expected_gates.add("group_event:" + name)
    gates = report.get("gates", {})
    require(
        set(gates) == expected_gates
        and all(v is True for v in gates.values())
        and report.get("release_ready") is True,
        "main-test gate summary inconsistent",
    )


def validate_release_artifacts(manifest, read):
    hashes = manifest["artifact_hashes"]
    require(RELEASE_ARTIFACTS <= set(hashes), "missing release provenance artifacts")
    dataset, audit, training, stability, calibration, selection, ids = (
        read(name)
        for name in (
            "dataset-manifest.json",
            "dataset-audit.json",
            "training-manifest.json",
            "training-stability.json",
            "calibration-manifest.json",
            "calibration-selection.json",
            "test-ids.json",
        )
    )
    require(
        dataset.get("release_ready") is True
        and audit.get("release_ready") is True
        and audit.get("confirmed_rows", 0) >= 30000
        and audit.get("groups", 0) >= 1200
        and audit.get("unmet_gates") == [],
        "dataset provenance gate failed",
    )
    require(
        hashes["dataset-manifest.json"] == manifest.get("dataset_manifest_sha256"),
        "dataset manifest hash mismatch",
    )
    require(
        training.get("status") == "awaiting-calibration-and-evaluation"
        and training.get("accessed_model_splits") == ["train", "validation"],
        "invalid training protocol",
    )
    require(
        stability.get("passed") is True and len(stability.get("runs", [])) == 3,
        "training stability evidence missing",
    )
    for metric in ("roc_auc", "false_high", "false_low"):
        values = [r.get(metric) for r in stability["runs"]]
        require(
            all(number(v) and 0 <= v <= 1 for v in values)
            and max(values) - min(values) <= 0.03 + 1e-12,
            "training stability failed",
        )
    require(
        [r.get("seed") for r in stability["runs"]]
        == [2026091601, 2026091602, 2026091603],
        "incorrect stability seeds",
    )
    require(
        calibration.get("status") == "awaiting-independent-test"
        and calibration.get("accessed_model_splits")
        == ["calibration-fit", "calibration-check"],
        "invalid calibration protocol",
    )
    require(
        selection.get("support_gate_passed") is True
        and all(
            type(selection.get(k)) is int and selection[k] >= 20
            for k in ("low_groups", "high_groups")
        ),
        "calibration tail support missing",
    )
    for source, names in (
        (
            training,
            (
                "model.cbm",
                "dataset-manifest.json",
                "protocol.json",
                "feature-schema.json",
            ),
        ),
        (
            calibration,
            (
                "calibration.json",
                "dataset-manifest.json",
                "protocol.json",
                "feature-schema.json",
            ),
        ),
    ):
        require(
            all(
                source.get("artifact_hashes", {}).get(name) == hashes[name]
                for name in names
            ),
            "upstream artifact binding mismatch",
        )
    require(
        training["artifact_hashes"].get("stability.json")
        == hashes["training-stability.json"]
        and calibration["artifact_hashes"].get("selection.json")
        == hashes["calibration-selection.json"],
        "support/stability checksum mismatch",
    )
    report = read("evaluation.json")
    require(
        isinstance(ids, list)
        and bool(ids)
        and all(isinstance(v, str) and v for v in ids)
        and len(ids) == len(set(ids))
        and report.get("test_ids") == ids,
        "missing/invalid full test ID roster",
    )
    main = report.get("main_test", {})
    baselines = read("training-baselines.json")
    require(
        training["artifact_hashes"].get("baselines.json")
        == hashes["training-baselines.json"]
        and main.get("reference_prior")
        == baselines.get("constant_prior", {}).get("prior"),
        "evaluation training-prior binding mismatch",
    )
    validate_main_test(main)
    test_counts = audit.get("split_counts", {}).get("test", {})
    require(
        main.get("rows") == len(ids) == test_counts.get("rows")
        and main.get("groups") == test_counts.get("groups"),
        "test population mismatch",
    )
    subgroups = report.get("subgroups", {})
    require(
        subgroups.get("passed") is True and bool(subgroups.get("slices")),
        "missing subgroup evidence",
    )
    supported = {"profile": set(), "channel": set()}
    for row in subgroups["slices"]:
        axis, status = row.get("axis"), row.get("status")
        require(
            axis in supported and status in {"passed", "insufficient-support"},
            "invalid/failed subgroup slice",
        )
        counts = [
            row.get(k) for k in ("rows", "groups_with_class_0", "groups_with_class_1")
        ]
        require(
            all(type(n) is int and n >= 0 for n in counts), "invalid subgroup counts"
        )
        sufficient = counts[0] >= 100 and min(counts[1:]) >= 20
        require(
            sufficient == (status == "passed"), "subgroup support summary inconsistent"
        )
        if sufficient:
            require(
                all(
                    number(row.get("metrics", {}).get(a, {}).get(e))
                    and 0 <= row["metrics"][a][e] <= 0.1 + 1e-12
                    for a in ("row", "group")
                    for e in ("false_high", "false_low")
                ),
                "subgroup confident-error gate failed",
            )
            supported[axis].add(row.get("value"))
    require(
        all(
            set(subgroups.get("allowlist", {}).get(axis, [])) == values and bool(values)
            for axis, values in supported.items()
        ),
        "subgroup allowlist inconsistent",
    )
    require(
        set(manifest["allowed_profiles"])
        <= set(subgroups.get("allowlist", {}).get("profile", []))
        and set(manifest["allowed_channels"])
        <= set(subgroups.get("allowlist", {}).get("channel", [])),
        "unsupported release profile/channel",
    )
    for name, keys in (
        (
            "challenge_reports",
            {"masked-context", "unresolved", "new-combinations", "family-held-out"},
        ),
        ("ablation_reports", {"without_scoped_evidence", "scoped_context_only"}),
    ):
        reports = report.get(name, {})
        require(
            set(reports) == keys
            and all(
                isinstance(v, dict)
                and v.get("status") == "complete"
                and type(v.get("rows")) is int
                and v["rows"] > 0
                and bool(v.get("predictions_sha256"))
                for v in reports.values()
            ),
            "missing detailed " + name,
        )
