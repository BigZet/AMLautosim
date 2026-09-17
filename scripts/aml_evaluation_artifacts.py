"""Inspectable, deterministic diagnostics for frozen AML predictions."""

import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import confusion_matrix, precision_recall_curve, roc_curve


def prediction_report(predictions):
    from scripts.evaluate_aml_classifier import probability_metrics

    if not predictions:
        return {
            "status": "missing",
            "rows": 0,
            "predictions_sha256": None,
            "reason": "No frozen observations; no completion or quality claim",
        }
    p = np.asarray([r["probability"] for r in predictions], dtype=float)
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Invalid prediction probabilities")
    if any(r["aml_label"] not in (0, 1, None) for r in predictions):
        raise ValueError("Predictions require binary or unresolved labels")
    confirmed = [r for r in predictions if r["aml_label"] is not None]
    metrics = diagnostics = None
    if confirmed:
        y = np.asarray([r["aml_label"] for r in confirmed])
        q = np.asarray([r["probability"] for r in confirmed])
        groups = [r["group_id"] for r in confirmed]
        _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
        metrics = {
            "row": probability_metrics(y, q, np.ones(len(y))),
            "group": probability_metrics(y, q, 1 / counts[inverse]),
        }
        bins = np.minimum((q * 10).astype(int), 9)
        bin_groups = [
            len({g for g, bucket in zip(groups, bins, strict=True) if bucket == i})
            for i in range(10)
        ]
        reliability = [
            {
                "lower": i / 10,
                "upper": (i + 1) / 10,
                "rows": int(np.sum(bins == i)),
                "groups": bin_groups[i],
                "support": "supported"
                if bin_groups[i] >= 30
                else "insufficient-support",
                "predicted": float(q[bins == i].mean()) if np.any(bins == i) else None,
                "observed": float(y[bins == i].mean()) if np.any(bins == i) else None,
            }
            for i in range(10)
        ]
        roc = pr = None
        if set(y) == {0, 1}:
            fpr, tpr, _ = roc_curve(y, q)
            precision, recall, _ = precision_recall_curve(y, q)
            roc, pr = (
                {"fpr": fpr.tolist(), "tpr": tpr.tolist()},
                {"recall": recall.tolist(), "precision": precision.tolist()},
            )
        diagnostics = {
            "confusion_matrix": confusion_matrix(y, q >= 0.5, labels=[0, 1]).tolist(),
            "confusion_threshold": 0.5,
            "confusion_scope": "Descriptive binary decision; confidence thresholds remain 0.1/0.9",
            "roc": roc,
            "pr": pr,
            "reliability": reliability,
            "class_histogram": {
                str(c): np.histogram(q[y == c], bins=np.linspace(0, 1, 11))[0].tolist()
                for c in (0, 1)
            },
        }
    content = json.dumps(
        predictions,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "status": "complete",
        "rows": len(predictions),
        "confirmed_rows": len(confirmed),
        "unresolved_rows": len(predictions) - len(confirmed),
        "predictions_sha256": hashlib.sha256(content).hexdigest(),
        "predictions": predictions,
        "metrics": metrics,
        "diagnostics": diagnostics,
        "probability_distribution": {
            "low": int(np.sum(p < 0.1)),
            "grey": int(np.sum((p >= 0.1) & (p < 0.9))),
            "high": int(np.sum(p >= 0.9)),
        },
    }


def prior_sensitivity(predictions, prior):
    """Label-shift assumptions only; never changes candidate probabilities or gates."""
    from scripts.evaluate_aml_classifier import probability_metrics

    y = np.asarray([r["aml_label"] for r in predictions])
    p = np.asarray([r["probability"] for r in predictions])
    scenarios = []
    observed_prior = float(y.mean())
    for assumed in (0.01, 0.05, 0.1, 0.25, 0.5):
        odds_factor = (assumed / (1 - assumed)) / (prior / (1 - prior))
        adjusted = odds_factor * p / (1 - p + odds_factor * p)
        weights = np.where(
            y == 1, assumed / observed_prior, (1 - assumed) / (1 - observed_prior)
        )
        scenarios.append(
            {
                "assumed_prior": assumed,
                "metrics": probability_metrics(y, adjusted, weights),
            }
        )
    return {
        "scope": "Assumption-only label-shift sensitivity; stable class-conditional distributions and calibrated source probabilities assumed; no runtime prior correction",
        "source_training_prior": prior,
        "scenarios": scenarios,
    }


def write_evaluation_artifacts(report, output):
    """Refuse overwrites; JSON is written last, after all plot files succeed."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(output)
    directory = output.with_suffix(".artifacts")
    if output.exists() or directory.exists():
        raise FileExistsError(f"Refusing existing evaluation output: {output}")
    directory.mkdir(parents=True, exist_ok=False)
    diagnostics = prediction_report(report["predictions"])["diagnostics"]
    if diagnostics is None:
        raise ValueError("Main evaluation requires confirmed predictions")
    paths = {}
    for kind in ("confusion", "roc", "pr", "reliability", "class-histogram"):
        fig, axis = plt.subplots(figsize=(6, 4))
        axis.set_title(kind.replace("-", " ").title())
        if kind == "confusion":
            matrix = diagnostics["confusion_matrix"]
            axis.imshow(matrix, cmap="Blues")
            for i in range(2):
                for j in range(2):
                    axis.text(j, i, str(matrix[i][j]), ha="center", va="center")
            axis.set(
                xticks=[0, 1],
                yticks=[0, 1],
                xlabel="Predicted class at p >= 0.5",
                ylabel="True class",
            )
        elif kind == "class-histogram":
            for c in ("0", "1"):
                axis.step(
                    np.arange(10) / 10 + 0.05,
                    diagnostics["class_histogram"][c],
                    where="mid",
                    label=f"True class {c}",
                )
            axis.set(xlabel="Probability", ylabel="Rows", xlim=(0, 1))
            axis.legend()
        elif kind == "reliability":
            bins = [b for b in diagnostics["reliability"] if b["rows"]]
            for status, marker, label in [
                ("supported", "o", "Supported: at least 30 groups"),
                (
                    "insufficient-support",
                    "x",
                    "Insufficient support: fewer than 30 groups",
                ),
            ]:
                selected = [b for b in bins if b["support"] == status]
                if selected:
                    axis.scatter(
                        [b["predicted"] for b in selected],
                        [b["observed"] for b in selected],
                        marker=marker,
                        label=label,
                    )
            for bucket in bins:
                axis.annotate(
                    f"{bucket['groups']} groups",
                    (bucket["predicted"], bucket["observed"]),
                    xytext=(3, 5),
                    textcoords="offset points",
                    fontsize=7,
                )
            axis.legend(fontsize=7)
            axis.plot([0, 1], [0, 1], "--", color="grey")
            axis.set(
                xlabel="Mean predicted probability",
                ylabel="Observed class 1 frequency",
                xlim=(0, 1),
                ylim=(0, 1),
            )
        else:
            data = diagnostics[kind]
            if data:
                x, y = ("fpr", "tpr") if kind == "roc" else ("recall", "precision")
                axis.plot(data[x], data[y])
                axis.set(xlabel=x, ylabel=y, xlim=(0, 1), ylim=(0, 1))
            else:
                axis.text(0.5, 0.5, "Undefined: only one class", ha="center")
        path = directory / (kind + ".svg")
        fig.tight_layout()
        fig.savefig(path, metadata={"Date": None})
        plt.close(fig)
        paths[kind] = {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    published = {**report, "plots": {"directory": directory.name, "artifacts": paths}}
    with output.open("x", encoding="utf-8") as handle:
        json.dump(
            published,
            handle,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        handle.write("\n")
