"""Versioned v9 observable features; no rubric or model predictions."""

from src.aml_workshop_simulator.services.aml_dataset_features_v3 import (
    extract_features as extract_v3,
)
from src.aml_workshop_simulator.services.semantic_contract import (
    INCOMING_KINDS,
    canonical_steps,
    resource_steps,
    resource_config,
)

FEATURE_VERSION = "aml-observable-v4.0"
CATEGORICAL_FEATURES = ["income_basis"]


def extract_features(steps, config):
    canonical = canonical_steps(steps, config)
    f = extract_v3(resource_steps(canonical, config), resource_config(config))
    parties = {p["id"]: p for p in config["behavior"]["counterparties"]}
    transfers = [s for s in canonical if s["card"]["code"] == "card_transfer"]
    amounts = {}
    for step in transfers:
        identity = step["recipient_id"]
        amounts[identity] = amounts.get(identity, 0) + float(step["amount"])
    total = sum(amounts.values())
    f["recipient_hhi"] = sum((a / total) ** 2 for a in amounts.values()) if total else 0
    f["has_recipient_transfers"] = int(bool(transfers))
    linked = [
        parties[s.get("sender_id") or s.get("recipient_id")]
        for s in canonical
        if s["card"]["code"] in ("incoming_transfer", "card_transfer")
    ]
    people = [p for p in linked if p["kind"] == "person"]
    f["known_relationship_share"] = sum(
        p["personal_relationship"] == "known" for p in people
    ) / max(len(people), 1)
    f["relationship_applicable_share"] = len(people) / max(len(linked), 1)
    incoming = [s for s in canonical if s["card"]["code"] == "incoming_transfer"]
    for kind in INCOMING_KINDS:
        f[f"incoming_{kind}_count"] = sum(
            s["action_details"]["incoming_kind"] == kind for s in incoming
        )
        f[f"incoming_{kind}_amount"] = sum(
            float(s["amount"])
            for s in incoming
            if s["action_details"]["incoming_kind"] == kind
        )
    history = config["behavior"]["history"]["operations"]
    for field, codes in (
        ("incoming_kind", {"incoming_transfer"}),
        ("bank_country", {"incoming_transfer"}),
        ("income_basis", {"salary"}),
        (
            "channel",
            {"incoming_transfer", "salary", "card_transfer", "cash_withdrawal"},
        ),
    ):
        events = [
            e
            for e in history or []
            if e["operation_code"] in codes
            and (field != "bank_country" or e.get("incoming_kind") == "bank_transfer")
        ]
        f[f"history_{field}_known_count"] = sum(
            e.get(field) is not None for e in events
        )
        f[f"history_{field}_unknown_count"] = sum(e.get(field) is None for e in events)
    for kind in INCOMING_KINDS:
        events = [e for e in history or [] if e.get("incoming_kind") == kind]
        f[f"history_incoming_{kind}_count"] = len(events)
        f[f"history_incoming_{kind}_amount"] = sum(float(e["amount"]) for e in events)
    return f
