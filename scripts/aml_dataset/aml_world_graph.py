"""Typed, finite economic-world grammar; all emitted cases remain unreviewed.

Partition choices change legal entitlements and obligated parties. Channel choices
change delivered services and their settlement rights, never merely root names.
Closure remains authoritative even when these real economic differences collapse.
"""

from dataclasses import dataclass, asdict, field
from collections import defaultdict, Counter
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
import json

from scripts.aml_dataset.aml_origins import _configuration
from scripts.aml_dataset.aml_casebook import protocol
from scripts.aml_dataset.aml_provenance import digest, connected_groups
from scripts.aml_dataset.aml_training import (
    validate_sources,
    source_hashes,
    json_bytes,
    jsonl_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
START = "2026-09-13T09:00:00+03:00"
END = "2026-09-14T09:00:00+03:00"
PURPOSE = dict(
    service="service_payment",
    asset="asset_sale",
    refund="refund",
    debt="loan",
    cost="shared_expense",
)
FAMILY = dict(service="P03", asset="P04", refund="P02", debt="P06", cost="P01")


@dataclass(frozen=True)
class Party:
    id: str
    role: str
    kind: str = "person"


@dataclass(frozen=True)
class Event:
    id: str
    kind: str
    actor: str
    beneficiary: str
    amount: int
    parents: tuple[str, ...]
    at: str


@dataclass(frozen=True)
class Obligation:
    id: str
    debtor: str
    creditor: str
    principal: int
    basis: str
    purpose: str
    due: str = START


@dataclass(frozen=True)
class Payment:
    id: str
    obligation: str
    payer: str
    beneficiary: str
    amount: int
    operation: str


@dataclass(frozen=True)
class Observation:
    payment: str
    issuer: str
    event: str
    checked_at: str = START
    confirms: str = "authority"


@dataclass
class World:
    id: str
    source: str
    participants: list[Party]
    events: list[Event]
    obligations: list[Obligation]
    payments: list[Payment]
    history: list[dict]
    rights: list[dict]
    observations: list[Observation]
    crime: dict
    profile: dict
    evidence_worlds: dict = field(default_factory=dict)


def money(n):
    return f"{n:.2f}"


def author_roots():
    roots = []
    for source in PURPOSE:
        for partition in ((3,), (2, 1), (1, 1, 1)):
            for cards, card_amount, cash_amount in (
                (5, 80000, 0),
                (4, 80000, 80000),
                (4, 70000, 120000),
                (5, 60000, 100000),
            ):
                w = World(
                    f"world-{source}-{len(partition)}-{cards}-{cash_amount}",
                    source,
                    [Party("player", "account holder")],
                    [],
                    [],
                    [],
                    [],
                    [],
                    [],
                    {},
                    {},
                )

                def event(kind, actor, beneficiary, amount, parents=()):
                    eid = f"event-{len(w.events)}"
                    at = (
                        datetime.fromisoformat("2026-09-01T09:00:00+03:00")
                        + timedelta(hours=len(w.events))
                    ).isoformat()
                    w.events.append(
                        Event(eid, kind, actor, beneficiary, amount, tuple(parents), at)
                    )
                    return eid

                def history(basis, amount, party, code="card_transfer"):
                    e = next(e for e in w.events if e.id == basis)
                    w.history.append(
                        dict(
                            id=f"history-{len(w.history)}",
                            occurred_at=e.at,
                            operation_code=code,
                            amount=money(amount),
                            counterparty_id=party,
                            category=None,
                            origin_event_id=basis,
                        )
                    )

                def obligation(debtor, creditor, amount, basis, purpose):
                    oid = f"obligation-{len(w.obligations)}"
                    w.obligations.append(
                        Obligation(oid, debtor, creditor, amount, basis, purpose)
                    )
                    return oid

                for group, count in enumerate(partition):
                    party = f"source-{group}"
                    w.participants.append(
                        Party(
                            party,
                            dict(
                                service="customer",
                                asset="asset buyer",
                                refund="advance recipient",
                                debt="actual borrower",
                                cost="shared cost principal",
                            )[source],
                        )
                    )
                    amount = count * 80000
                    if source == "service":
                        contract = event("service_contract", party, "player", amount)
                        stages = [
                            event(
                                "accepted_service_stage",
                                "player",
                                party,
                                80000,
                                [contract],
                            )
                            for _ in range(count)
                        ]
                        basis = event(
                            "accepted_work_receivable", party, "player", amount, stages
                        )
                    elif source == "asset":
                        seller = f"seller-{group}"
                        w.participants.append(Party(seller, "original asset owner"))
                        purchase = event(
                            "asset_purchase_paid", "player", seller, amount
                        )
                        history(purchase, amount, seller)
                        acquisition = event(
                            "title_acquired", seller, "player", amount, [purchase]
                        )
                        w.rights.append(
                            dict(
                                asset=f"asset-{group}",
                                owner="player",
                                controller="player",
                                basis=acquisition,
                                disposed_to=party,
                            )
                        )
                        basis = event(
                            "owned_asset_transferred",
                            "player",
                            party,
                            amount,
                            [acquisition],
                        )
                    elif source in {"refund", "debt"}:
                        original = count * 100000
                        paid = event(
                            "paid_advance"
                            if source == "refund"
                            else "loan_disbursement",
                            "player",
                            party,
                            original,
                        )
                        history(paid, original, party)
                        if source == "refund":
                            retained = event(
                                "accepted_nonrefundable_service",
                                party,
                                "player",
                                count * 20000,
                                [paid],
                            )
                            basis = event(
                                "partial_cancellation_refund_due",
                                party,
                                "player",
                                amount,
                                [paid, retained],
                            )
                        else:
                            repaid = event(
                                "prior_principal_repaid",
                                party,
                                "player",
                                count * 20000,
                                [paid],
                            )
                            history(repaid, count * 20000, party, "incoming_transfer")
                            basis = event(
                                "remaining_principal_due",
                                party,
                                "player",
                                amount,
                                [paid, repaid],
                            )
                    else:
                        provider = f"prior-provider-{group}"
                        w.participants.append(
                            Party(provider, "provider paid by disclosed agent")
                        )
                        authority = event(
                            "cost_agency_authority", party, "player", amount
                        )
                        paid = event(
                            "allocated_cost_paid",
                            "player",
                            provider,
                            amount,
                            [authority],
                        )
                        history(paid, amount, provider)
                        basis = event(
                            "principal_reimbursement_due",
                            party,
                            "player",
                            amount,
                            [authority, paid],
                        )
                        w.rights.append(
                            dict(
                                principal=party,
                                agent="player",
                                authority=authority,
                                allocated_cost=paid,
                            )
                        )
                    oid = obligation(party, "player", amount, basis, PURPOSE[source])
                    for _ in range(count):
                        w.payments.append(
                            Payment(
                                f"in-{len(w.payments)}",
                                oid,
                                party,
                                "player",
                                80000,
                                "incoming_transfer",
                            )
                        )
                cash_parts = (
                    [cash_amount]
                    if 0 < cash_amount <= 80000
                    else [cash_amount // 2] * 2
                    if cash_amount
                    else []
                )
                for i in range(cards + len(cash_parts)):
                    cash = i >= cards
                    party = "cash-vendor" if cash else f"provider-{i}"
                    if not any(p.id == party for p in w.participants):
                        w.participants.append(
                            Party(
                                party,
                                "cash delivery provider"
                                if cash
                                else "independent completed-service creditor",
                            )
                        )
                    amount = cash_parts[i - cards] if cash else card_amount
                    basis = event(
                        "cash_service_delivered"
                        if cash
                        else "service_delivered_on_credit",
                        party,
                        "player",
                        amount,
                    )
                    oid = obligation(
                        "player", party, amount, basis, "personal_spending"
                    )
                    w.payments.append(
                        Payment(
                            f"out-{i}",
                            oid,
                            "player",
                            party,
                            amount,
                            "cash_withdrawal" if cash else "card_transfer",
                        )
                    )
                for p in w.payments:
                    o = next(o for o in w.obligations if o.id == p.obligation)
                    w.observations.append(
                        Observation(
                            p.id,
                            p.payer
                            if p.operation == "incoming_transfer"
                            else p.beneficiary,
                            o.basis,
                        )
                    )
                # Actual alternative offence: unrelated entrusted funds diverted by
                # the final payer, knowingly received and sent to a collector.
                payer = w.payments[2].payer
                w.participants.extend(
                    [
                        Party("victim", "owner of entrusted funds"),
                        Party(
                            "collector", "beneficial controller of diverted proceeds"
                        ),
                    ]
                )
                entrusted = event("unrelated_funds_entrusted", "victim", payer, 80000)
                offence = event(
                    "escrow_embezzlement", payer, "collector", 80000, [entrusted]
                )
                custody = event(
                    "diverted_funds_in_sender_custody",
                    payer,
                    "collector",
                    80000,
                    [offence],
                )
                w.crime = dict(
                    source_payment=w.payments[2].id,
                    source_amount=80000,
                    source_owner="victim",
                    source_controller=payer,
                    source_custodian=payer,
                    offence_event=offence,
                    custody_event=custody,
                    collector="collector",
                    routing=[],
                )
                remaining = 80000
                for p in reversed(w.payments[3:]):
                    routed = min(remaining, p.amount)
                    if routed:
                        w.crime["routing"].insert(
                            0,
                            dict(
                                payment=p.id,
                                amount=routed,
                                actual_beneficiary="collector",
                                custodian="player",
                                channel="cash_handover"
                                if p.operation == "cash_withdrawal"
                                else "controlled_account",
                            ),
                        )
                        remaining -= routed
                w.profile = dict(
                    id="account-holder",
                    title=dict(
                        service="Independent service worker",
                        asset="Owner disposing of acquired assets",
                        refund="Customer cancelling prepaid services",
                        debt="Private lender collecting principal",
                        cost="Disclosed shared-cost agent",
                    )[source],
                    description="Expected receipts settle existing rights; current debits settle separately delivered services.",
                )
                incoming = w.payments[:3]
                outgoing = w.payments[3:]
                ordered = [
                    incoming[0],
                    outgoing[0],
                    outgoing[1],
                    incoming[1],
                    outgoing[2],
                    incoming[2],
                    outgoing[3],
                ]
                card_tail = [p for p in outgoing[4:] if p.operation == "card_transfer"]
                cash_tail = [
                    p for p in outgoing[4:] if p.operation == "cash_withdrawal"
                ]
                if cash_tail:
                    ordered.append(cash_tail.pop(0))
                ordered.extend(card_tail)
                ordered.extend(cash_tail)
                w.payments = ordered
                checks = {c.payment: c for c in w.observations}
                w.observations = [checks[p.id] for p in ordered]
                w.evidence_worlds = author_evidence_worlds(w)
                roots.append(w)
    return roots


def author_evidence_worlds(w):
    """Author explicit alternative case files before selecting a public variant.

    These are synthetic original authority statements, account-control records
    and signed denials; none is manufactured by the feature projection. The
    three worlds have different actual allocations and documentary findings.
    """
    obligations = {o.id: o for o in w.obligations}
    checks = {c.payment: c for c in w.observations}
    routing = {r["payment"]: r for r in w.crime["routing"]}
    worlds = {}
    for kind in ("lawful", "criminal", "unresolved"):
        documents, movements, controls = {}, {}, []
        for p in w.payments:
            o, c = obligations[p.obligation], checks[p.id]
            diverted = kind == "criminal" and (
                p.id in routing or p.id == w.crime["source_payment"]
            )
            movement = dict(
                asdict(p),
                settles_obligation=None if kind == "unresolved" else not diverted,
                origin_established=kind != "unresolved",
            )
            if diverted and p.id == w.crime["source_payment"]:
                movement.update(
                    criminal_proceeds=True,
                    source_owner=w.crime["source_owner"],
                    source_controller=w.crime["source_controller"],
                    source_custodian=w.crime["source_custodian"],
                    origin_event=w.crime["custody_event"],
                )
            if diverted and p.id in routing:
                movement.update(
                    beneficiary=w.crime["collector"],
                    criminal_amount=routing[p.id]["amount"],
                    custodian="player",
                    channel=routing[p.id]["channel"],
                )
                if p.operation == "card_transfer":
                    controls.append(
                        dict(
                            payment=p.id,
                            observed_account_holder=p.beneficiary,
                            controller=w.crime["collector"],
                            claimant=o.creditor,
                            obligation=o.id,
                            settlement_authorized=False,
                            available_at=START,
                            source="bank_control_record_and_creditor_denial",
                        )
                    )
            movements[p.id] = movement
            documents[p.id] = {}
            for claim_kind in ("actual_purpose", "wrong_cover"):
                purpose = (
                    o.purpose
                    if claim_kind == "actual_purpose"
                    else "loan"
                    if o.purpose != "loan"
                    else "refund"
                )
                outcome = (
                    "unknown"
                    if kind == "unresolved"
                    else "refutes"
                    if diverted or claim_kind == "wrong_cover"
                    else "corroborates"
                )
                documents[p.id][claim_kind] = dict(
                    issuer=c.issuer,
                    event=c.event,
                    confirms=c.confirms,
                    checked_at=c.checked_at,
                    amount=money(p.amount),
                    obligation=o.id,
                    payment=p.id,
                    actual_purpose=o.purpose,
                    claimed_purpose=purpose,
                    outcome=outcome,
                    signed_by_issuer=kind != "unresolved",
                    complete_purpose_authority=kind != "unresolved",
                    authorized_purpose=o.purpose,
                    allocation_authorized=None
                    if kind == "unresolved"
                    else not diverted,
                    kind="unresolved_statement"
                    if kind == "unresolved"
                    else "signed_issuer_denial_of_claimed_purpose_with_actual_basis"
                    if claim_kind == "wrong_cover"
                    else "signed_issuer_denial_of_allocation"
                    if diverted
                    else "signed_original_event_and_payment_authority",
                )
        worlds[kind] = dict(
            documents=documents, actual_payments=movements, account_controls=controls
        )
    return worlds


def validate_evidence_worlds(w, instant):
    obligations = {o.id: o for o in w.obligations}
    checks = {c.payment: c for c in w.observations}
    payments = {p.id: p for p in w.payments}
    routing = {r["payment"]: r for r in w.crime["routing"]}
    if set(w.evidence_worlds) != {"lawful", "criminal", "unresolved"}:
        raise ValueError("missing authored evidence worlds")
    for kind, world in w.evidence_worlds.items():
        if set(world.get("documents", {})) != set(payments) or set(
            world.get("actual_payments", {})
        ) != set(payments):
            raise ValueError("signed-document/actual-payment roster mismatch")
        controls = world.get("account_controls", [])
        required_controls = (
            {pid for pid in routing if payments[pid].operation == "card_transfer"}
            if kind == "criminal"
            else set()
        )
        if (
            len(controls) != len(required_controls)
            or {r.get("payment") for r in controls} != required_controls
        ):
            raise ValueError("missing or duplicate nominee-account control relation")
        for r in controls:
            p = payments[r["payment"]]
            if (
                r.get("observed_account_holder") != p.beneficiary
                or r.get("controller") != w.crime["collector"]
                or r.get("claimant") != p.beneficiary
                or r.get("obligation") != p.obligation
                or r.get("settlement_authorized") is not False
                or r.get("source") != "bank_control_record_and_creditor_denial"
                or instant(r["available_at"]) > instant(START)
            ):
                raise ValueError("unbound nominee-account control/settlement denial")
        for pid, p in payments.items():
            o, c = obligations[p.obligation], checks[pid]
            diverted = kind == "criminal" and (
                pid in routing or pid == w.crime["source_payment"]
            )
            actual = world["actual_payments"][pid]
            actual_keys = set(asdict(p)) | {"settles_obligation", "origin_established"}
            if diverted and pid == w.crime["source_payment"]:
                actual_keys |= {
                    "criminal_proceeds",
                    "source_owner",
                    "source_controller",
                    "source_custodian",
                    "origin_event",
                }
            if diverted and pid in routing:
                actual_keys |= {"criminal_amount", "custodian", "channel"}
            if set(actual) != actual_keys:
                raise ValueError(
                    "actual movement contains unsupported or contradictory fields"
                )
            expected_settles = None if kind == "unresolved" else not diverted
            expected_beneficiary = (
                w.crime["collector"] if diverted and pid in routing else p.beneficiary
            )
            if (
                any(
                    actual.get(k) != v
                    for k, v in asdict(p).items()
                    if k != "beneficiary"
                )
                or actual.get("beneficiary") != expected_beneficiary
                or actual.get("settles_obligation") is not expected_settles
                or actual.get("origin_established") is not (kind != "unresolved")
            ):
                raise ValueError("actual payment differs from authored allocation")
            if (
                diverted
                and pid in routing
                and (
                    actual.get("criminal_amount") != routing[pid]["amount"]
                    or actual.get("channel") != routing[pid]["channel"]
                    or actual.get("custodian") != "player"
                )
            ):
                raise ValueError("actual payment loses criminal routing")
            if (
                diverted
                and pid == w.crime["source_payment"]
                and (
                    actual.get("criminal_proceeds") is not True
                    or any(
                        actual.get(k) != w.crime[k]
                        for k in (
                            "source_owner",
                            "source_controller",
                            "source_custodian",
                        )
                    )
                    or actual.get("origin_event") != w.crime["custody_event"]
                )
            ):
                raise ValueError("actual receipt loses criminal source")
            docs = world["documents"][pid]
            if set(docs) != {"actual_purpose", "wrong_cover"}:
                raise ValueError("missing specific purpose statement")
            for claim_kind, doc in docs.items():
                expected_purpose = (
                    o.purpose
                    if claim_kind == "actual_purpose"
                    else "loan"
                    if o.purpose != "loan"
                    else "refund"
                )
                expected_outcome = (
                    "unknown"
                    if kind == "unresolved"
                    else "refutes"
                    if diverted or claim_kind == "wrong_cover"
                    else "corroborates"
                )
                expected_kind = (
                    "unresolved_statement"
                    if kind == "unresolved"
                    else "signed_issuer_denial_of_claimed_purpose_with_actual_basis"
                    if claim_kind == "wrong_cover"
                    else "signed_issuer_denial_of_allocation"
                    if diverted
                    else "signed_original_event_and_payment_authority"
                )
                if (
                    doc.get("issuer") != c.issuer
                    or doc.get("kind") != expected_kind
                    or doc.get("event") != o.basis
                    or doc.get("confirms") != "authority"
                    or doc.get("payment") != pid
                    or doc.get("obligation") != o.id
                    or doc.get("amount") != money(p.amount)
                    or doc.get("actual_purpose") != o.purpose
                    or doc.get("claimed_purpose") != expected_purpose
                    or doc.get("authorized_purpose") != o.purpose
                    or doc.get("outcome") != expected_outcome
                    or doc.get("signed_by_issuer") is not (kind != "unresolved")
                    or doc.get("complete_purpose_authority")
                    is not (kind != "unresolved")
                    or doc.get("allocation_authorized") is not expected_settles
                    or instant(doc["checked_at"]) != instant(c.checked_at)
                ):
                    raise ValueError(
                        "signed statement contradicts actual authority or scope"
                    )


def validate_world(w):
    def instant(value):
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("economic timestamps require an explicit timezone")
        return result

    def unique(items):
        mapped = {x.id: x for x in items}
        if len(mapped) != len(items):
            raise ValueError("duplicate identity")
        return mapped

    parties = unique(w.participants)
    events = unique(w.events)
    obligations = unique(w.obligations)
    payments = unique(w.payments)
    if w.source not in PURPOSE or any(p.kind != "person" for p in parties.values()):
        raise ValueError("unsupported source or party kind")
    seen = set()
    for e in w.events:
        if (
            type(e.amount) is not int
            or e.amount <= 0
            or not {e.actor, e.beneficiary} <= parties.keys()
            or not set(e.parents) <= seen
            or len(e.parents) != len(set(e.parents))
        ):
            raise ValueError("noncausal event, unknown party or invalid amount")
        if any(instant(events[p].at) >= instant(e.at) for p in e.parents):
            raise ValueError("dependency must precede effect")
        if instant(e.at) >= instant(START):
            raise ValueError("original event occurs after authority observation")
        seen.add(e.id)
    paid = defaultdict(int)
    for p in w.payments:
        if (
            p.amount <= 0
            or p.obligation not in obligations
            or not {p.payer, p.beneficiary} <= parties.keys()
        ):
            raise ValueError("payment requires actual obligation and supported parties")
        o = obligations[p.obligation]
        if (p.payer, p.beneficiary) != (o.debtor, o.creditor):
            raise ValueError("payment reverses entitlement")
        if p.operation not in {
            "incoming_transfer",
            "card_transfer",
            "cash_withdrawal",
        } or (p.operation == "incoming_transfer") != (p.beneficiary == "player"):
            raise ValueError("operation/party incompatibility")
        paid[o.id] += p.amount
    for o in w.obligations:
        if (
            o.basis not in events
            or events[o.basis].amount != o.principal
            or paid[o.id] != o.principal
            or instant(o.due) > instant(START)
        ):
            raise ValueError("double use or invalid due entitlement")
    history_events = set()
    historical_codes = {
        "asset_purchase_paid": "card_transfer",
        "paid_advance": "card_transfer",
        "loan_disbursement": "card_transfer",
        "allocated_cost_paid": "card_transfer",
        "prior_principal_repaid": "incoming_transfer",
        "service_deposit_paid": "card_transfer",
        "cash_withdrawn_for_service_deposit": "cash_withdrawal",
    }
    for h in w.history:
        e = events.get(h["origin_event_id"])
        if (
            e is None
            or historical_codes.get(e.kind) != h["operation_code"]
            or h["occurred_at"] != e.at
            or h["amount"] != money(e.amount)
            or (
                h["counterparty_id"] not in parties
                and not (
                    e.kind == "cash_withdrawn_for_service_deposit"
                    and h["counterparty_id"] is None
                )
            )
        ):
            raise ValueError("fabricated historical settlement")
        if e.id in history_events:
            raise ValueError("historical settlement used twice")
        if e.kind == "cash_withdrawn_for_service_deposit":
            if h["counterparty_id"] is not None or (e.actor, e.beneficiary) != (
                "player",
                "player",
            ):
                raise ValueError(
                    "cash deposit withdrawal must enter the player's own custody"
                )
        elif h["counterparty_id"] != (
            e.beneficiary if e.actor == "player" else e.actor
        ):
            raise ValueError("historical party differs from original settlement")
        history_events.add(e.id)
    if history_events != {e.id for e in w.events if e.kind in historical_codes}:
        raise ValueError("complete history omits an actual monetary settlement")
    used_bases, used_originals = set(), set()
    for o in w.obligations:
        e = events[o.basis]
        if e.id in used_bases:
            raise ValueError("one basis cannot create multiple entitlements")
        used_bases.add(e.id)
        if o.creditor != "player":
            if e.kind == "service_balance_due":
                parents = [events[p] for p in e.parents]
                deliveries = [
                    p for p in parents if p.kind == "service_contract_completed"
                ]
                deposits = [
                    p
                    for p in parents
                    if p.kind in {"service_deposit_paid", "service_cash_deposit_paid"}
                ]
                if len(parents) != 2 or len(deliveries) != 1 or len(deposits) != 1:
                    raise ValueError(
                        "service balance requires delivered contract and actual deposit"
                    )
                delivery, deposit = deliveries[0], deposits[0]
                consumed = {deposit.id}
                if deposit.kind == "service_cash_deposit_paid":
                    if len(deposit.parents) != 2:
                        raise ValueError(
                            "cash deposit requires actual withdrawal and signed receipt"
                        )
                    withdrawal, receipt = [events[p] for p in deposit.parents]
                    if (
                        withdrawal.kind != "cash_withdrawn_for_service_deposit"
                        or receipt.kind != "signed_service_deposit_cash_receipt"
                        or len(withdrawal.parents) != 1
                        or len(receipt.parents) != 1
                    ):
                        raise ValueError(
                            "cash deposit monetary source or receipt missing"
                        )
                    terms = events[withdrawal.parents[0]]
                    handover = events[receipt.parents[0]]
                    if (
                        terms.kind != "service_cash_deposit_required"
                        or len(terms.parents) != 1
                        or handover.kind != "cash_service_deposit_handed_over"
                        or handover.parents != (withdrawal.id,)
                        or withdrawal.id not in history_events
                        or (withdrawal.actor, withdrawal.beneficiary)
                        != ("player", "player")
                        or (terms.actor, terms.beneficiary) != (o.creditor, "player")
                        or (receipt.actor, receipt.beneficiary)
                        != (o.creditor, "player")
                        or (handover.actor, handover.beneficiary)
                        != ("player", o.creditor)
                        or any(
                            x.amount != deposit.amount
                            for x in (withdrawal, receipt, terms, handover)
                        )
                    ):
                        raise ValueError(
                            "cash deposit amount, custody, named receiver or receipt authority mismatch"
                        )
                    contract = events[terms.parents[0]]
                    consumed.update((withdrawal.id, receipt.id, terms.id, handover.id))
                else:
                    originals = [events[p] for p in deposit.parents]
                    if len(originals) != 1 or deposit.id not in history_events:
                        raise ValueError(
                            "service deposit requires one original contract and monetary history"
                        )
                    contract = originals[0]
                if (
                    contract.kind != "service_contract_for_player"
                    or (contract.actor, contract.beneficiary) != (o.creditor, "player")
                    or (delivery.actor, delivery.beneficiary) != (o.creditor, "player")
                    or (deposit.actor, deposit.beneficiary) != ("player", o.creditor)
                    or (e.actor, e.beneficiary) != (o.creditor, "player")
                    or o.debtor != "player"
                    or o.purpose != "personal_spending"
                    or delivery.parents != (contract.id, deposit.id)
                    or delivery.amount != contract.amount
                    or contract.amount - deposit.amount != o.principal
                    or contract.id in used_originals
                    or bool(consumed & used_originals)
                ):
                    raise ValueError(
                        "service balance reuses or contradicts actual contract/deposit/delivery"
                    )
                used_originals.update(consumed | {contract.id})
                continue
            if (
                e.kind not in {"service_delivered_on_credit", "cash_service_delivered"}
                or (e.actor, e.beneficiary) != (o.creditor, o.debtor)
                or o.debtor != "player"
                or o.purpose != "personal_spending"
            ):
                raise ValueError("outgoing liability does not match delivered service")
            continue
        parents = [events[p] for p in e.parents]
        if o.purpose != PURPOSE[w.source]:
            raise ValueError("entitlement purpose does not match economic source")
        if w.source == "service":
            if (
                e.kind != "accepted_work_receivable"
                or not parents
                or (e.actor, e.beneficiary) != (o.debtor, "player")
                or any(
                    p.kind != "accepted_service_stage"
                    or (p.actor, p.beneficiary) != ("player", o.debtor)
                    or len(p.parents) != 1
                    for p in parents
                )
                or sum(p.amount for p in parents) != o.principal
            ):
                raise ValueError("earned receivable must equal accepted service stages")
            contracts = {p.parents[0] for p in parents}
            if len(contracts) != 1:
                raise ValueError("service stages require one bound original contract")
            original = events[next(iter(contracts))]
            if (
                original.kind != "service_contract"
                or original.amount != o.principal
                or (original.actor, original.beneficiary) != (o.debtor, "player")
            ):
                raise ValueError("service contract amount or parties mismatch")
            if original.id in used_originals:
                raise ValueError("service contract reused")
            used_originals.add(original.id)
        if w.source == "asset":
            if (
                e.kind != "owned_asset_transferred"
                or len(parents) != 1
                or parents[0].kind != "title_acquired"
                or parents[0].beneficiary != "player"
                or (e.actor, e.beneficiary) != ("player", o.debtor)
            ):
                raise ValueError("disposal lacks paid title or actual buyer")
            title = parents[0]
            acquisitions = [events[p] for p in title.parents]
            if (
                len(acquisitions) != 1
                or acquisitions[0].kind != "asset_purchase_paid"
                or acquisitions[0].id not in history_events
                or (acquisitions[0].actor, acquisitions[0].beneficiary)
                != ("player", title.actor)
                or acquisitions[0].amount != title.amount
            ):
                raise ValueError("title must follow its actual purchase settlement")
            matching = [r for r in w.rights if r.get("basis") == title.id]
            if (
                title.id in used_originals
                or len(matching) != 1
                or matching[0].get("disposed_to") != o.debtor
            ):
                raise ValueError("title reused or bound to another disposal")
            used_originals.add(title.id)
        if w.source in {"refund", "debt"}:
            required = "paid_advance" if w.source == "refund" else "loan_disbursement"
            originals = [
                p for p in parents if p.kind == required and p.id in history_events
            ]
            if len(originals) != 1 or originals[0].amount != o.principal + sum(
                p.amount
                for p in parents
                if p.kind
                in {"accepted_nonrefundable_service", "prior_principal_repaid"}
            ):
                raise ValueError(
                    "refund or repayment exceeds original less consumed principal"
                )
            original = originals[0]
            reduction_kind = (
                "accepted_nonrefundable_service"
                if w.source == "refund"
                else "prior_principal_repaid"
            )
            reductions = [p for p in parents if p.kind == reduction_kind]
            expected_kind = (
                "partial_cancellation_refund_due"
                if w.source == "refund"
                else "remaining_principal_due"
            )
            if (
                e.kind != expected_kind
                or len(parents) != 2
                or len(reductions) != 1
                or (e.actor, e.beneficiary) != (o.debtor, "player")
                or (original.actor, original.beneficiary) != ("player", o.debtor)
                or any(
                    (p.actor, p.beneficiary) != (o.debtor, "player")
                    or p.parents != (original.id,)
                    for p in reductions
                )
                or original.id in used_originals
            ):
                raise ValueError(
                    "refund/loan parties, basis or prior settlement mismatch"
                )
            used_originals.add(original.id)
        if w.source == "cost":
            authorities = [p for p in parents if p.kind == "cost_agency_authority"]
            costs = [p for p in parents if p.kind == "allocated_cost_paid"]
            if (
                e.kind != "principal_reimbursement_due"
                or len(parents) != 2
                or len(authorities) != 1
                or len(costs) != 1
                or (e.actor, e.beneficiary) != (o.debtor, "player")
            ):
                raise ValueError("reimbursement lacks actual principal/agent basis")
            authority, cost = authorities[0], costs[0]
            matching = [
                r
                for r in w.rights
                if r.get("authority") == authority.id
                and r.get("allocated_cost") == cost.id
            ]
            if (
                authority.amount != o.principal
                or cost.amount != o.principal
                or (authority.actor, authority.beneficiary) != (o.debtor, "player")
                or cost.actor != "player"
                or cost.beneficiary in {"player", o.debtor}
                or cost.parents != (authority.id,)
                or cost.id not in history_events
                or len(matching) != 1
                or authority.id in used_originals
            ):
                raise ValueError("agency amount, payment or principal mismatch")
            used_originals.add(authority.id)
    if any(
        e.kind
        in {
            "service_deposit_paid",
            "service_cash_deposit_paid",
            "cash_withdrawn_for_service_deposit",
            "signed_service_deposit_cash_receipt",
            "cash_service_deposit_handed_over",
            "service_cash_deposit_required",
        }
        and e.id not in used_originals
        for e in w.events
    ):
        raise ValueError(
            "historical service deposit is unrelated to a current residual liability"
        )
    for right in w.rights:
        if w.source == "asset":
            e = events.get(right.get("basis"))
            if (
                e is None
                or e.kind != "title_acquired"
                or right.get("owner") != e.beneficiary
                or right.get("controller") != e.beneficiary
                or right.get("disposed_to") not in parties
            ):
                raise ValueError("title owner/controller mismatch")
        elif w.source == "cost":
            e = events.get(right.get("authority"))
            paid_event = events.get(right.get("allocated_cost"))
            if (
                e is None
                or paid_event is None
                or e.kind != "cost_agency_authority"
                or right.get("principal") != e.actor
                or right.get("agent") != e.beneficiary
                or e.id not in paid_event.parents
            ):
                raise ValueError("unsupported agency allocation")
    if w.source in {"asset", "cost"} and len(w.rights) != sum(
        o.creditor == "player" for o in w.obligations
    ):
        raise ValueError("missing title or agency right")
    checks = {x.payment: x for x in w.observations}
    if len(checks) != len(w.observations) or checks.keys() != payments.keys():
        raise ValueError("observation roster differs from payment roster")
    for pid, c in checks.items():
        p = payments[pid]
        o = obligations[p.obligation]
        if (
            c.confirms != "authority"
            or c.event != o.basis
            or c.issuer
            != (p.payer if p.operation == "incoming_transfer" else p.beneficiary)
            or instant(c.checked_at) < instant(events[c.event].at)
            or instant(c.checked_at) > instant(START)
        ):
            raise ValueError("unsupported or future settlement confirmation")
    c = w.crime
    if (
        not {
            c["source_owner"],
            c["source_controller"],
            c["source_custodian"],
            c["collector"],
        }
        <= parties.keys()
    ):
        raise ValueError("unbound criminal ownership/control/custody")
    source = payments.get(c["source_payment"])
    custody = events.get(c["custody_event"])
    offence = events.get(c["offence_event"])
    if (
        source is None
        or source.operation != "incoming_transfer"
        or c["source_amount"] != source.amount
        or source.payer != c["source_custodian"]
        or custody is None
        or offence is None
        or custody.kind != "diverted_funds_in_sender_custody"
        or offence.kind != "escrow_embezzlement"
        or offence.id not in custody.parents
        or custody.amount != source.amount
        or offence.amount != source.amount
    ):
        raise ValueError("criminal source conservation or custody failure")
    entrusted = [events[p] for p in offence.parents]
    if (
        len(entrusted) != 1
        or entrusted[0].kind != "unrelated_funds_entrusted"
        or entrusted[0].amount != c["source_amount"]
        or entrusted[0].actor != c["source_owner"]
        or entrusted[0].beneficiary != c["source_custodian"]
        or offence.actor != c["source_controller"]
        or offence.beneficiary != c["collector"]
        or c["source_owner"] in {"player", c["source_controller"], c["collector"]}
        or custody.actor != c["source_custodian"]
        or custody.beneficiary != c["collector"]
    ):
        raise ValueError("offence ownership/control differs from custody")
    allocations = {r["payment"]: r for r in c["routing"]}
    if len(allocations) != len(c["routing"]):
        raise ValueError("duplicate crime allocation")
    available = 0
    for p in w.payments:
        if p.id == source.id:
            available += c["source_amount"]
        if p.id in allocations:
            r = allocations[p.id]
            if (
                p.payer != "player"
                or not 0 < r["amount"] <= p.amount
                or r["actual_beneficiary"] != c["collector"]
                or r["custodian"] != "player"
            ):
                raise ValueError("invalid criminal destination allocation")
            if r["channel"] != (
                "cash_handover"
                if p.operation == "cash_withdrawal"
                else "controlled_account"
            ):
                raise ValueError("crime routing channel differs from actual delivery")
            available -= r["amount"]
            if available < 0:
                raise ValueError("criminal proceeds routed before receipt")
    if available or not allocations.keys() <= payments.keys():
        raise ValueError("criminal proceeds not conserved")
    validate_evidence_worlds(w, instant)


def _project(w, label, mode):
    case_file = w.evidence_worlds[
        {0: "lawful", 1: "criminal", None: "unresolved"}[label]
    ]
    ledger = dict(
        participants=[
            asdict(p) for p in w.participants if p.id not in {"victim", "collector"}
        ],
        historical_payments=w.history,
    )
    config = _configuration(dict(ledger=ledger))
    behavior = config["behavior"]
    behavior["profile"] = deepcopy(w.profile)
    cards = {
        c["code"]: {k: c[k] for k in ("id", "code", "version")}
        for c in config["card_snapshots"]
    }
    obligations = {o.id: o for o in w.obligations}
    steps = []
    facts = []
    records = []
    actual = []
    paid = defaultdict(int)
    for index, p in enumerate(w.payments):
        o = obligations[p.obligation]
        c = next(check for check in w.observations if check.payment == p.id)
        credit = p.operation == "incoming_transfer"
        wrong_cover = mode == "wrong_cover" and index == 0
        evidence = deepcopy(
            case_file["documents"][p.id][
                "wrong_cover" if wrong_cover else "actual_purpose"
            ]
        )
        claimed_purpose = evidence["claimed_purpose"]
        masked = (
            mode == "opaque"
            or (mode == "sources" and not credit)
            or (mode == "obligations" and credit)
        )
        status = (
            "unverified"
            if masked
            else "unknown"
            if evidence["outcome"] == "unknown"
            else "contradicted"
            if evidence["outcome"] == "refutes"
            else "verified"
        )
        claim = "claim-" + p.id
        facts.append(
            dict(
                id=claim,
                fact_type="source_of_funds" if credit else "payment_purpose",
                verification_status=status,
                provenance="customer_statement" if masked else "independent_record",
                available_at=c.checked_at,
                valid_from=START,
                valid_to=END,
                counterparty_ids=[] if p.operation == "cash_withdrawal" else [c.issuer],
                operation_codes=[p.operation],
                purpose_code=claimed_purpose,
                max_credit_amount=money(p.amount if credit else 0),
                max_debit_amount=money(0 if credit else p.amount),
            )
        )
        step = dict(
            step_id=str(uuid5(NAMESPACE_URL, p.id)),
            card=cards[p.operation],
            amount=money(p.amount),
            context={},
            action_details=dict(incoming_kind="bank_transfer", bank_country="RU")
            if credit
            else {},
            interval_minutes=None if index == 0 else 1,
            purpose_code=claimed_purpose,
            claim_id=claim,
        )
        if credit:
            step["sender_id"] = p.payer
        elif p.operation != "cash_withdrawal":
            step["recipient_id"] = p.beneficiary
        steps.append(step)
        ap = deepcopy(case_file["actual_payments"][p.id])
        if ap["settles_obligation"]:
            paid[o.id] += p.amount
        actual.append(ap)
        records.append(
            dict(
                id=p.id,
                amount=money(p.amount),
                origin_event_id=o.basis,
                obligation_id=o.id,
                operation=p.operation,
                step_number=index + 1,
                record_check=evidence,
                actual_payment=ap,
                observed_record_status=status,
            )
        )
    facts.append(
        dict(
            id="opening",
            fact_type="opening_balance",
            verification_status="verified",
            provenance="scenario_record",
            available_at=START,
            valid_from=START,
            valid_to=END,
            counterparty_ids=[],
            operation_codes=[],
            purpose_code="unknown",
            max_credit_amount="180000.00",
            max_debit_amount="180000.00",
        )
    )
    purposes = sorted(
        {o.purpose for o in w.obligations}
        | {f["purpose_code"] for f in facts}
        | {"unknown"}
    )
    behavior["aml_context"] = dict(
        version="aml-context-v1",
        as_of=END,
        expected_activity=dict(
            period_start=START,
            period_end=END,
            activity_kinds=[p for p in purposes if p != "unknown"],
            expected_credit_min="240000.00",
            expected_credit_max="240000.00",
            expected_debit_min="400000.00",
            expected_debit_max="400000.00",
        ),
        opening_balance_facts=["opening"],
        purpose_catalog=[dict(code=p, title=p.replace("_", " ")) for p in purposes],
        facts=facts,
        history_coverage="complete",
        history_start="2026-08-14T09:00:00+03:00",
        history_end=START,
    )
    truth = dict(
        aml_episode_present=None if label is None else bool(label),
        opening_funds="180000 lawful accumulated savings",
        actual_payments=actual,
        account_controls=deepcopy(case_file["account_controls"]),
        remaining_obligations=[
            dict(
                asdict(o),
                outstanding_after_round=None
                if label is None
                else o.principal - paid[o.id],
            )
            for o in w.obligations
        ],
        criminal_episode=deepcopy(w.crime) if label == 1 else None,
        actual_world_sha256=digest(dict(world=asdict(w), label=label)),
    )
    crime_event_ids = {w.crime["offence_event"], w.crime["custody_event"]}
    offence = next(e for e in w.events if e.id == w.crime["offence_event"])
    crime_event_ids.update(offence.parents)
    truth["actual_events"] = (
        [asdict(e) for e in w.events if label == 1 or e.id not in crime_event_ids]
        if label is not None
        else []
    )
    truth["actual_rights"] = deepcopy(w.rights) if label is not None else []
    return dict(config=config, steps=steps), records, truth


def compile_root(w):
    validate_world(w)
    rows = []
    for mode, label in [
        (mode, label)
        for mode in ("records", "opaque", "sources", "obligations", "wrong_cover")
        for label in (0, 1)
    ] + [("opaque", None)]:
        public, records, truth = _project(w, label, mode)
        row = dict(
            scenario_id=f"{w.id}-{mode}-{label}",
            provenance_group_id=w.id,
            family_id=FAMILY[w.source],
            aml_label=label,
            label_status="unresolved" if label is None else "confirmed",
            review_status="authored_unreviewed",
            review=None,
            author_id="typed-world-grammar-v1",
            label_source="authored-causal-world",
            label_protocol_version="aml-labels-v1",
            population_id="aml-game-balanced-v1",
            label_rationale="Actual sources and destinations establish authored outcome; missing records never establish truth.",
            author_truth=truth,
            economic_records=records,
            observability=dict(
                distinguishable=label is not None and mode != "opaque",
                reason="Independent scoped authorities can reveal payment allocation; opaque opposite worlds intentionally collide.",
            ),
            hypothesis_source=dict(root_dossier_sha256=digest(asdict(w))),
            alternative_explanation=dict(
                lawful="Actual rights settled",
                illicit="Entrusted funds diverted and routed; cover rights remain outstanding",
            ),
            necessary_facts=[
                "actual source ownership",
                "actual beneficiary and allocation",
            ],
            forbidden_information=["world truth", "root and label identifiers"],
            public_snapshot=public,
            variant_recipe=mode,
            template_ancestry=["typed-economic-world-v1"],
            provenance=dict(
                root_id=w.id,
                counterfactual_pair_id=w.id + "-" + mode,
                history_origin_id=w.id + "-history",
                parent_ids=[],
            ),
        )
        rows.append(row)
    return rows


def validate_record(w, row):
    validate_world(w)
    public, records, truth = _project(w, row["aml_label"], row["variant_recipe"])
    if (
        row["public_snapshot"] != public
        or row["economic_records"] != records
        or row["author_truth"] != truth
    ):
        raise ValueError("compiler/world/observation consistency failure")


def build_pilot(output):
    """Publish only fully checked drafts; audit against exact existing inputs."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    candidates = author_roots()
    roots = []
    rows = []
    rejected = []
    for root in candidates:
        try:
            batch = compile_root(root)
            for row in batch:
                validate_record(root, row)
            validate_sources(batch, protocol())
        except (ValueError, KeyError) as exc:
            rejected.append(dict(root_id=root.id, reason=str(exc)))
            continue
        roots.append(root)
        rows.extend(batch)
    features = validate_sources(rows, protocol())
    graph = connected_groups(rows, features)
    clusters = defaultdict(list)
    for row in rows:
        if row["aml_label"] is not None:
            clusters[digest(features[row["scenario_id"]])].append(row)
    collisions = [
        dict(feature_sha256=key, scenario_ids=[r["scenario_id"] for r in group])
        for key, group in clusters.items()
        if len({r["aml_label"] for r in group}) > 1
    ]
    inputs = [
        "resources/aml_dataset/aml-v1/origins-reviewed/v3/casebook.jsonl",
        "resources/aml_dataset/aml-v1/origins-draft/v5/casebook.jsonl",
    ]
    combined = list(rows)
    for name in inputs:
        combined.extend(
            json.loads(line)
            for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    combined_features = validate_sources(combined, protocol())
    combined_graph = connected_groups(combined, combined_features)
    combined_clusters = defaultdict(set)
    for row in combined:
        if row["aml_label"] is not None:
            combined_clusters[digest(combined_features[row["scenario_id"]])].add(
                row["aml_label"]
            )
    hashes = {
        **source_hashes(),
        **{
            name: sha256((ROOT / name).read_bytes()).hexdigest()
            for name in [
                "scripts/aml_dataset/aml_world_graph.py",
                "scripts/aml_dataset/aml_origins.py",
                "docs/verification/semantic-interface-audit/fixtures.json",
                "scripts/aml_dataset/aml_casebook.py",
                "docs/research/2026-09-16-aml-behavior-and-legitimate-context.md",
            ]
        },
    }
    report = dict(
        version="typed-world-graph-draft-v2",
        release_ready=False,
        reviewed_rows=0,
        review_status="authored_unreviewed",
        authored_roots=len(roots),
        attempted_roots=len(candidates),
        rejected_roots=len(rejected),
        confirmed_candidate_rows=sum(r["aml_label"] is not None for r in rows),
        unresolved_rows=sum(r["aml_label"] is None for r in rows),
        class_counts=dict(
            Counter(str(r["aml_label"]) for r in rows if r["aml_label"] is not None)
        ),
        post_closure_components=len(graph["groups"]),
        contradictory_feature_clusters=len(collisions),
        component_sizes=dict(
            Counter(
                graph["scenario_groups"][r["scenario_id"]]
                for r in rows
                if r["aml_label"] is not None
            )
        ),
        merging_reasons=dict(Counter(link["reason"] for link in graph["links"])),
        families=sorted({r["family_id"] for r in rows}),
        profiles=sorted({r.source for r in roots}),
        channels=sorted({p.operation for r in roots for p in r.payments}),
        source_hashes=hashes,
        combined=dict(
            rows=len(combined),
            pilot_casebook_sha256=sha256(jsonl_bytes(rows)).hexdigest(),
            contradictory_feature_clusters=sum(
                len(v) > 1 for v in combined_clusters.values()
            ),
            components=len(combined_graph["groups"]),
            confirmed=sum(r["aml_label"] is not None for r in combined),
            input_hashes={
                name: sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs
            },
            merging_reasons=dict(
                Counter(link["reason"] for link in combined_graph["links"])
            ),
        ),
        minimum_components_required=1200,
        minimum_confirmed_rows_required=30000,
    )
    output.mkdir(parents=True)
    for name, data in {
        "roots.jsonl": jsonl_bytes([asdict(r) for r in roots]),
        "casebook.jsonl": jsonl_bytes(rows),
        "provenance.json": json_bytes(graph),
        "combined-provenance.json": json_bytes(combined_graph),
        "collisions.json": json_bytes(collisions),
        "rejections.json": json_bytes(rejected),
        "feasibility.json": json_bytes(report),
    }.items():
        (output / name).write_bytes(data)
    return report
