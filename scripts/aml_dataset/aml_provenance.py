"""Conservative connected provenance components, independent of authored labels."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def neutral_observation(public, *, shape=False, history_only=False):
    """Remove neutral identifiers/text; shape additionally ignores amount/date mutations.

    Shape equality is intentionally conservative: it establishes dependence, never
    a label or a claim that two economic stories are substantively independent.
    """
    config, steps = public["config"], public["steps"]
    behavior = deepcopy(config["behavior"])
    parties = {}
    claims = {}

    def party(identity):
        if identity is None:
            return None
        return parties.setdefault(identity, f"party-{len(parties)}")

    def claim(identity):
        if identity is None:
            return None
        return claims.setdefault(identity, f"fact-{len(claims)}")

    history = behavior["history"].get("operations")
    if history_only:
        source = sorted(
            history or [],
            key=lambda e: (
                datetime.fromisoformat(e["occurred_at"]),
                e["operation_code"],
                Decimal(str(e["amount"])),
            ),
        )
    else:
        source = steps
    for item in source:
        for key in ("sender_id", "recipient_id", "counterparty_id"):
            if item.get(key):
                party(item[key])
        if item.get("claim_id"):
            claim(item["claim_id"])

    excluded = {
        "name",
        "title",
        "description",
        "label",
        "help",
        "step_id",
        "id",
        "code_version",
    }

    def clean(value, key=""):
        if key in {"sender_id", "recipient_id", "counterparty_id"}:
            return party(value)
        if key == "counterparty_ids":
            return sorted(party(v) for v in value)
        if key == "claim_id":
            return claim(value)
        if key == "opening_balance_facts":
            return sorted(claim(v) for v in value)
        if isinstance(value, dict):
            return {
                k: clean(v, k)
                for k, v in sorted(value.items())
                if k not in excluded
                and not (shape and k in {"verification_status", "provenance"})
            }
        if isinstance(value, list):
            return [clean(v, key) for v in value]
        if shape and (
            key
            in {
                "interval_minutes",
                "occurred_at",
                "starts_at",
                "available_at",
                "valid_from",
                "valid_to",
                "as_of",
                "period_start",
                "period_end",
                "history_start",
                "history_end",
            }
            or "amount" in key
            or key.startswith("expected_credit")
            or key.startswith("expected_debit")
        ):
            return None if value is None else "<numeric-or-time>"
        if key == "occurred_at" and isinstance(value, str):
            return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()
        if isinstance(value, str) and (
            "amount" in key
            or key.startswith("expected_credit")
            or key.startswith("expected_debit")
        ):
            try:
                return str(Decimal(value).normalize())
            except InvalidOperation:
                return value
        return value

    if history_only:
        # Current profile/party attributes are not part of the historical source.
        # First-use identity links retain the repeated historical roles themselves.
        return {"events": clean(source)}
    normalized_steps = clean(steps)
    # Stable first-use roles preserve identity links, while remaining isolated
    # parties are represented as an unordered multiset of observable attributes.
    known_parties = {
        party(p["id"]): clean(p)
        for p in behavior["counterparties"]
        if p["id"] in parties
    }
    unused_parties = sorted(
        (clean(p) for p in behavior["counterparties"] if p["id"] not in parties),
        key=digest,
    )
    facts = behavior["aml_context"]["facts"]
    normalized_facts = {
        claim(f["id"]): clean(f)
        for f in sorted(
            facts,
            key=lambda f: (
                f["id"] not in claims,
                claims.get(f["id"], digest(clean(f))),
            ),
        )
    }
    behavior["aml_context"]["facts"] = normalized_facts
    behavior["counterparties"] = {"used": known_parties, "unused": unused_parties}

    # Country is explicitly neutral in this educational feature contract.
    def strip_country(value):
        if isinstance(value, dict):
            return {
                k: strip_country(v) for k, v in value.items() if k != "bank_country"
            }
        if isinstance(value, list):
            return [strip_country(v) for v in value]
        return value

    return strip_country({"steps": normalized_steps, "behavior": clean(behavior)})


def connected_groups(rows, features):
    ids = [r["scenario_id"] for r in rows]
    parent = {sid: sid for sid in ids}
    tokens = {}
    links = []

    def root(sid):
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid

    def link(sid, token):
        other = tokens.setdefault(token, sid)
        left, right = root(sid), root(other)
        if left != right:
            parent[max(left, right)] = min(left, right)
            links.append(
                {
                    "left": other,
                    "right": sid,
                    "reason": token[0],
                    "token_sha256": digest(token),
                }
            )

    for row in sorted(rows, key=lambda r: r["scenario_id"]):
        sid = row["scenario_id"]
        provenance = {**row, **row.get("provenance", {})}
        link(sid, ("root", sid))
        link(sid, ("declared_group", row["provenance_group_id"]))
        for key, category in (
            ("root_id", "root"),
            ("authored_root_id", "root"),
            ("counterfactual_pair_id", "pair"),
            ("near_duplicate_id", "near_duplicate"),
            ("history_origin_id", "history"),
        ):
            if provenance.get(key):
                link(sid, (category, str(provenance[key])))
        for key, category in (
            ("parent_ids", "root"),
            ("history_origin_ids", "history"),
            ("near_duplicate_ids", "near_duplicate"),
        ):
            values = provenance.get(key, [])
            if not isinstance(values, list) or any(
                not isinstance(v, str) or not v for v in values
            ):
                raise ValueError(f"provenance {key} requires string list")
            for identity in values:
                link(sid, (category, identity))
        public = row["public_snapshot"]
        link(sid, ("neutral_observation", digest(neutral_observation(public))))
        link(
            sid,
            ("near_duplicate_shape", digest(neutral_observation(public, shape=True))),
        )
        link(sid, ("feature_collision", digest(features[sid])))
        if public["config"]["behavior"]["history"].get("operations"):
            link(
                sid,
                (
                    "shared_nonempty_history",
                    digest(neutral_observation(public, history_only=True)),
                ),
            )
    components = {}
    for sid in sorted(ids):
        components.setdefault(root(sid), []).append(sid)
    members = {"group-" + digest(sids)[:24]: sids for sids in components.values()}
    mapping = {sid: gid for gid, sids in members.items() for sid in sids}
    return {
        "groups": members,
        "links": links,
        "scenario_groups": mapping,
        "method": "connected-root-parent-history-pair-neutral-shape-feature-v1",
    }
