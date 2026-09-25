"""Five preregistered shared-context economic dossiers; draft expectations only.

No model loading, fitting, scoring, independent review or freeze occurs here.
All five players in a round receive the same full public configuration.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import json

from scripts.aml_dataset.aml_origins import _configuration
from scripts.aml_dataset.aml_casebook import protocol
from scripts.aml_dataset.aml_provenance import connected_groups, digest
from scripts.aml_dataset.aml_training import (
    validate_sources,
    source_hashes,
    json_bytes,
    jsonl_bytes,
    evaluate,
    submit_blockers,
)
from scripts.aml_demo_casebook import validate_roster, require_independent

ROOT = Path(__file__).resolve().parents[2]
# Stable economic roles are the subgroup-support key. Concrete public dossiers
# remain in title/description/history; role names never establish independence.
PROFILE_CATEGORIES = {
    "demo-housing_closeout": "project_coordinator",
    "demo-instrument_workshop": "artisan_owner",
    "demo-collection_conservation": "collection_owner",
    "demo-course_cancellation": "event_organizer",
    "demo-equipment_pool": "equipment_pool_organizer",
}
START = "2026-09-13T09:00:00+03:00"
END = "2026-09-14T09:00:00+03:00"
SPECS = (
    (
        "housing_closeout",
        "Housing project coordinator",
        "Refunds of partially used contractor advances and the remaining earned coordination fee.",
        "P02",
    ),
    (
        "instrument_workshop",
        "Instrument restorer and owner",
        "Accepted restoration balances and disposal of an instrument acquired for the workshop.",
        "P03",
    ),
    (
        "collection_conservation",
        "Inherited collection conservator",
        "Separately inherited lots sold after conservation, with a prior buyer installment and carrier overcharge refund.",
        "P04",
    ),
    (
        "course_cancellation",
        "Course cancellation organiser",
        "Partly returned training and venue advances; unpaid provider balances remain explicit.",
        "P02",
    ),
    (
        "equipment_pool",
        "Equipment lending pool organiser",
        "A borrower repays principal, a buyer completes an owned-equipment purchase and a lessor returns unused advance.",
        "P10",
    ),
)
BANDS = ("low", "low", "high", "high", "ambiguous")


def money(value):
    return f"{Decimal(value):.2f}"


def _dossier(spec):
    key, title, description, family = spec
    d = dict(
        id="demo-" + key,
        title=title,
        description=description,
        family=family,
        participants=[dict(id="player", role="account holder", kind="person")],
        events=[],
        history=[],
        obligations=[],
        rights=[],
        strategies=[],
    )

    def party(identity, role, kind="person", category=None):
        if not any(p["id"] == identity for p in d["participants"]):
            d["participants"].append(
                dict(id=identity, role=role, kind=kind, category=category)
            )
        return identity

    def event(kind, actor, beneficiary, amount, parents=()):
        identity = f"{key}-e{len(d['events'])}"
        at = (
            datetime.fromisoformat("2026-08-20T09:00:00+03:00")
            + timedelta(hours=len(d["events"]))
        ).isoformat()
        d["events"].append(
            dict(
                id=identity,
                kind=kind,
                actor=actor,
                beneficiary=beneficiary,
                amount=money(amount),
                parents=list(parents),
                at=at,
            )
        )
        return identity

    def historical(kind, actor, beneficiary, amount, parents=(), operation=None):
        basis = event(kind, actor, beneficiary, amount, parents)
        operation = operation or (
            "incoming_transfer" if beneficiary == "player" else "card_transfer"
        )
        d["history"].append(
            dict(
                id=f"{key}-history-{len(d['history'])}",
                occurred_at=d["events"][-1]["at"],
                operation_code=operation,
                amount=money(amount),
                counterparty_id=actor if beneficiary == "player" else beneficiary,
                category=None,
                origin_event_id=basis,
            )
        )
        return basis

    def due(identity, debtor, creditor, amount, basis, purpose):
        d["obligations"].append(
            dict(
                id=identity,
                debtor=debtor,
                creditor=creditor,
                principal=money(amount),
                basis=basis,
                purpose=purpose,
                due=START,
            )
        )
        return identity

    sources = [
        party(f"{key}-source-{i}", role)
        for i, role in enumerate(
            (
                "original contractual counterparty A",
                "original contractual counterparty B",
                "original contractual counterparty C",
            )
        )
    ]
    source_basis = []
    purposes = []
    principals = []
    if key == "housing_closeout":
        deposit = historical("coordination_fee_advance", sources[2], "player", 120000)
        a = historical("contractor_advance_paid", "player", sources[0], 100000)
        b = historical("contractor_advance_paid", "player", sources[1], 140000)
        for original, party_id, used in (
            (a, sources[0], 20000),
            (b, sources[1], 60000),
        ):
            accepted = event(
                "nonrefundable_completed_work", party_id, "player", used, [original]
            )
            source_basis.append(
                event(
                    "unused_advance_return_due",
                    party_id,
                    "player",
                    80000,
                    [original, accepted],
                )
            )
        accepted = event(
            "coordination_services_accepted", "player", sources[2], 200000, [deposit]
        )
        source_basis.append(
            event(
                "earned_fee_balance_due",
                sources[2],
                "player",
                80000,
                [deposit, accepted],
            )
        )
        purposes = ["refund", "refund", "service_payment"]
        principals = [80000] * 3
    elif key == "instrument_workshop":
        prepay = historical("restoration_customer_advance", sources[0], "player", 50000)
        materials = party(key + "-materials", "materials supplier")
        parts = historical(
            "restoration_materials_paid", "player", materials, 30000, [prepay]
        )
        assistant = party(key + "-assistant", "specialist repair subcontractor")
        labor = historical(
            "restoration_subcontract_paid", "player", assistant, 20000, [parts]
        )
        partial = historical(
            "accepted_restoration_stage_paid", sources[0], "player", 40000, [labor]
        )
        seller = party(key + "-seller", "original instrument owner")
        bought = historical("instrument_acquisition_paid", "player", seller, 70000)
        title_event = event(
            "instrument_title_assigned", seller, "player", 70000, [bought]
        )
        d["rights"].append(
            dict(
                asset="restored-instrument",
                owner="player",
                controller="player",
                basis=title_event,
            )
        )
        accepted = event(
            "restoration_job_accepted",
            "player",
            sources[0],
            170000,
            [parts, labor, partial],
        )
        source_basis.append(
            event(
                "restoration_balance_due",
                sources[0],
                "player",
                80000,
                [accepted, prepay, partial],
            )
        )
        source_basis.append(
            event(
                "owned_instrument_title_transferred",
                "player",
                sources[1],
                80000,
                [title_event],
            )
        )
        third = event(
            "second_instrument_restoration_accepted",
            "player",
            sources[2],
            80000,
            [labor],
        )
        source_basis.append(third)
        purposes = ["service_payment", "asset_sale", "service_payment"]
        principals = [80000] * 3
    elif key == "collection_conservation":
        ancestor = party(
            key + "-estate", "estate representative assigning inherited title"
        )
        titles = [
            event(
                "inherited_lot_title_assigned",
                ancestor,
                "player",
                110000 if i == 0 else 80000,
            )
            for i in range(3)
        ]
        d["rights"].extend(
            dict(
                asset=f"inherited-lot-{i}", owner="player", controller="player", basis=t
            )
            for i, t in enumerate(titles)
        )
        conservator = party(key + "-conservator", "collection conservator")
        care = historical(
            "conservation_invoice_paid", "player", conservator, 45000, titles
        )
        instalment = historical(
            "first_lot_buyer_instalment", sources[0], "player", 30000, [titles[0], care]
        )
        carrier = party(key + "-carrier", "insured carrier")
        shipping = historical("carrier_advance_paid", "player", carrier, 25000, [care])
        archived = party(
            key + "-archived-buyer",
            "buyer of a separate previously disposed inherited lot",
        )
        other_title = event(
            "separate_archived_lot_title_assigned", ancestor, "player", 60000
        )
        sold = historical(
            "archived_lot_sale_settled", archived, "player", 60000, [other_title]
        )
        historical(
            "carrier_overcharge_returned", carrier, "player", 5000, [shipping, sold]
        )
        source_basis = [
            event(
                "inherited_lot_sale_balance_due",
                sources[i],
                "player",
                80000,
                [titles[i], care] + ([instalment] if i == 0 else []),
            )
            for i in range(3)
        ]
        purposes = ["asset_sale"] * 3
        principals = [80000] * 3
    elif key == "course_cancellation":
        for i, (amount, returned) in enumerate(
            ((120000, 40000), (180000, 20000), (100000, 20000))
        ):
            advance = historical(
                "training_or_venue_advance_paid", "player", sources[i], amount
            )
            cancel = event(
                "course_or_venue_booking_cancelled",
                sources[i],
                "player",
                amount,
                [advance],
            )
            prior = historical(
                "partial_cancelled_advance_return",
                sources[i],
                "player",
                returned,
                [cancel],
            )
            source_basis.append(
                event(
                    "remaining_cancelled_advance_due",
                    sources[i],
                    "player",
                    amount - returned,
                    [advance, cancel, prior],
                )
            )
        purposes = ["refund"] * 3
        principals = [80000, 160000, 80000]
    else:
        loan = historical("member_loan_disbursed", "player", sources[0], 120000)
        repaid = historical(
            "member_principal_partly_repaid", sources[0], "player", 40000, [loan]
        )
        seller = party(key + "-seller", "original equipment owner")
        bought = historical(
            "owned_equipment_acquisition_paid", "player", seller, 100000
        )
        title_event = event(
            "equipment_title_assigned", seller, "player", 100000, [bought]
        )
        advance = historical("lease_advance_paid", "player", sources[2], 90000)
        previous = historical(
            "lease_advance_partly_returned", sources[2], "player", 10000, [advance]
        )
        deposit = historical(
            "equipment_buyer_deposit", sources[1], "player", 20000, [title_event]
        )
        d["rights"].append(
            dict(
                asset="pool-equipment",
                owner="player",
                controller="player",
                basis=title_event,
            )
        )
        source_basis = [
            event(
                "remaining_member_principal_due",
                sources[0],
                "player",
                80000,
                [loan, repaid],
            ),
            event(
                "equipment_sale_balance_due",
                sources[1],
                "player",
                80000,
                [title_event, deposit],
            ),
            event(
                "unused_lease_advance_due",
                sources[2],
                "player",
                80000,
                [advance, previous],
            ),
        ]
        purposes = ["loan", "asset_sale", "refund"]
        principals = [80000] * 3
    source_obligations = [
        due(
            f"{key}-receivable-{i}",
            sources[i],
            "player",
            principals[i],
            source_basis[i],
            purposes[i],
        )
        for i in range(3)
    ]
    d["source_obligations"] = source_obligations
    # These are alternative allocations of a common finite account budget.
    # Unselected real liabilities do not vanish; every actual world reports them.
    layouts = (
        (5, 80000, ()),
        (4, 80000, (80000,)),
        (5, 80000, ()),
        (4, 70000, (60000, 60000)),
        (5, 60000, (50000, 50000)),
    )
    for index, (cards, card_amount, cash_parts) in enumerate(layouts):
        band = BANDS[index]
        sid = f"{d['id']}-strategy-{index + 1}"
        payments = []
        for i, oid in enumerate(source_obligations):
            payments.append(
                dict(
                    id=f"{sid}-in-{i}",
                    obligation=oid,
                    payer=sources[i],
                    beneficiary="player",
                    amount="80000.00",
                    operation="incoming_transfer",
                )
            )
        debits = []
        for j, amount in enumerate([card_amount] * cards + list(cash_parts)):
            cash = j >= cards
            creditor = party(
                f"{key}-service-{index}-{j}",
                "completed " + ("cash delivery" if cash else "service") + " creditor",
            )
            basis = event(
                "completed_cash_delivery_due" if cash else "completed_service_due",
                creditor,
                "player",
                amount,
            )
            oid = due(
                f"{sid}-payable-{j}",
                "player",
                creditor,
                amount,
                basis,
                "personal_spending",
            )
            debits.append(
                dict(
                    id=f"{sid}-out-{j}",
                    obligation=oid,
                    payer="player",
                    beneficiary=creditor,
                    amount=money(amount),
                    operation="cash_withdrawal" if cash else "card_transfer",
                )
            )
        ordered = [
            payments[0],
            debits[0],
            debits[1],
            payments[1],
            debits[2],
            payments[2],
            debits[3],
        ]
        if cash_parts:
            ordered.append(debits[cards])
        ordered.extend(debits[4:cards])
        ordered.extend(debits[cards + 1 :])
        if index == 2:
            employer = party(
                key + "-employer",
                "employer for completed part-time work",
                "institution",
                "employer",
            )
            merchant = party(
                key + "-merchant", "household goods merchant", "merchant", None
            )
            for suffix, who, amount, code in (
                ("salary", employer, 30000, "salary"),
                ("purchase", merchant, 10000, "purchase"),
            ):
                credit = code == "salary"
                payer, beneficiary = (who, "player") if credit else ("player", who)
                basis = event(
                    "employment_period_completed"
                    if credit
                    else "household_goods_delivered",
                    who,
                    "player",
                    amount,
                )
                oid = due(
                    f"{sid}-{suffix}-due",
                    payer,
                    beneficiary,
                    amount,
                    basis,
                    "salary" if credit else "personal_spending",
                )
                ordered.append(
                    dict(
                        id=f"{sid}-{suffix}",
                        obligation=oid,
                        payer=payer,
                        beneficiary=beneficiary,
                        amount=money(amount),
                        operation=code,
                    )
                )
        episode = None
        if band == "high":
            victim = party(
                f"{key}-victim-{index}", "owner of entrusted third-party funds"
            )
            collector = party(
                f"{key}-controller-{index}",
                "beneficial controller of diverted third-party funds",
            )
            entrusted = event("third_party_funds_entrusted", victim, sources[2], 80000)
            offence = event(
                "intentional_escrow_embezzlement",
                sources[2],
                collector,
                80000,
                [entrusted],
            )
            custody = event(
                "diverted_funds_in_sender_account",
                sources[2],
                collector,
                80000,
                [offence],
            )
            route = []
            remainder = Decimal(80000)
            for p in reversed(debits):
                amount = min(remainder, Decimal(p["amount"]))
                if amount:
                    route.insert(
                        0,
                        dict(
                            payment=p["id"],
                            criminal_amount=money(amount),
                            custodian="player",
                            beneficial_recipient=collector,
                            channel="cash_handover"
                            if p["operation"] == "cash_withdrawal"
                            else "collector_controlled_account",
                        ),
                    )
                    remainder -= amount
            episode = dict(
                source_payment=payments[2]["id"],
                source_amount="80000.00",
                source_owner=victim,
                source_controller=sources[2],
                source_custodian=sources[2],
                collector=collector,
                entrustment_event=entrusted,
                offence_event=offence,
                custody_event=custody,
                routing=route,
            )
        rationale = (
            "Low expected: independently supported original entitlements fund actual completed-service liabilities; rapid transfers are lawful."
            if index == 0
            else "Low expected: supported actual sources and cash provider delivery; new counterparties and cash do not override the obligations."
            if index == 1
            else "High expected: affirmative issuer denial and collector-control evidence identify diverted proceeds; earned payroll and household purchase remain separately lawful."
            if index == 2
            else "High expected: third-party proceeds are knowingly received and physically handed to a collector; the purported cash providers deny settlement authority."
            if index == 3
            else "Ambiguous expected: sources and payment-authority allocations cannot be established from available records; no outcome is assigned."
        )
        strategy = dict(
            id=sid,
            band=band,
            label={"low": 0, "high": 1, "ambiguous": None}[band],
            payments=ordered,
            episode=episode,
            rationale=rationale,
            authority_records=[],
            account_control=[],
            actual_payments=[],
            allocations_known=index != 4,
        )
        obligation_map = {o["id"]: o for o in d["obligations"]}
        routes = {r["payment"]: r for r in episode["routing"]} if episode else {}
        for payment in ordered:
            obligation = obligation_map[payment["obligation"]]
            credit = payment["beneficiary"] == "player"
            issuer = payment["payer"] if credit else obligation["creditor"]
            diverted = bool(
                episode
                and (
                    payment["id"] == episode["source_payment"]
                    or payment["id"] in routes
                )
            )
            control = None
            if payment["id"] in routes:
                control_event = event(
                    "collector_cash_handover_instruction"
                    if payment["operation"] == "cash_withdrawal"
                    else "creditor_account_unauthorized_collector_control",
                    episode["collector"],
                    payment["beneficiary"],
                    payment["amount"],
                    [episode["offence_event"]],
                )
                control = dict(
                    payment=payment["id"],
                    observed_account_party=None
                    if payment["operation"] == "cash_withdrawal"
                    else payment["beneficiary"],
                    rightful_creditor=obligation["creditor"],
                    controller=episode["collector"],
                    settlement_authorized=False,
                    basis=control_event,
                )
                strategy["account_control"].append(control)
            outcome = (
                "unknown"
                if not strategy["allocations_known"]
                else "refutes"
                if diverted
                else "corroborates"
            )
            record = dict(
                payment=payment["id"],
                issuer=issuer,
                original_event=obligation["basis"],
                obligation=obligation["id"],
                claim_id="claim-" + payment["id"],
                amount=payment["amount"],
                payer=payment["payer"],
                beneficiary=payment["beneficiary"],
                purpose=obligation["purpose"],
                checked_at=START,
                confirms="original_event_and_payment_authority",
                outcome=outcome,
                source_event=None,
            )
            lawful_source = None
            if credit and outcome == "corroborates":
                funding = event(
                    "lawfully_accumulated_source_funds",
                    payment["payer"],
                    payment["payer"],
                    payment["amount"],
                )
                lawful_source = dict(
                    owner=payment["payer"],
                    controller=payment["payer"],
                    custodian=payment["payer"],
                    basis=funding,
                    amount=payment["amount"],
                )
            if outcome != "unknown":
                parents = [obligation["basis"]]
                if lawful_source:
                    parents.append(lawful_source["basis"])
                if diverted:
                    parents.append(
                        control["basis"] if control else episode["custody_event"]
                    )
                authority = event(
                    "signed_issuer_allocation_denial"
                    if diverted
                    else "signed_issuer_payment_authority",
                    issuer,
                    "player",
                    payment["amount"],
                    parents,
                )
                d["events"][-1]["signed_scope"] = {
                    k: deepcopy(record[k])
                    for k in (
                        "payment",
                        "issuer",
                        "original_event",
                        "obligation",
                        "claim_id",
                        "amount",
                        "payer",
                        "beneficiary",
                        "purpose",
                        "confirms",
                        "outcome",
                    )
                }
                d["events"][-1]["statement"] = (
                    "Issuer rejects this specific instruction and confirms the named obligation remains payable through its authorized settlement route."
                    if diverted
                    else "Issuer confirms this specific instruction, original obligation, amount, parties and purpose before execution; no future completed payment is asserted."
                )
                record["source_event"] = authority
            strategy["authority_records"].append(record)
            actual = deepcopy(payment)
            if lawful_source:
                actual["lawful_source"] = lawful_source
            actual.update(
                settles_obligation=None
                if not strategy["allocations_known"]
                else not diverted,
                actual_beneficiary=episode["collector"]
                if payment["id"] in routes
                else payment["beneficiary"],
                actual_origin_event=episode["custody_event"]
                if diverted and credit
                else control["basis"]
                if control
                else obligation["basis"],
            )
            if episode and payment["id"] == episode["source_payment"]:
                actual.update(
                    criminal_amount=episode["source_amount"],
                    source_owner=episode["source_owner"],
                    source_controller=episode["source_controller"],
                    source_custodian=episode["source_custodian"],
                )
            if payment["id"] in routes:
                actual.update(
                    criminal_amount=routes[payment["id"]]["criminal_amount"],
                    custodian="player",
                    delivery_channel=routes[payment["id"]]["channel"],
                )
            strategy["actual_payments"].append(actual)
        d["strategies"].append(strategy)
    return d


def _validate_dossier(d):
    events = {e["id"]: e for e in d["events"]}
    parties = {p["id"]: p for p in d["participants"]}
    obligations = {o["id"]: o for o in d["obligations"]}
    if (
        len(events) != len(d["events"])
        or len(parties) != len(d["participants"])
        or len(obligations) != len(d["obligations"])
    ):
        raise ValueError("duplicate economic identifier")
    seen = set()
    for e in d["events"]:
        if (
            not set(e["parents"]) <= seen
            or not {e["actor"], e["beneficiary"]} <= parties.keys()
            or Decimal(e["amount"]) <= 0
        ):
            raise ValueError("invalid causal original event")
        at = datetime.fromisoformat(e["at"])
        if (
            at.tzinfo is None
            or at >= datetime.fromisoformat(START)
            or any(datetime.fromisoformat(events[p]["at"]) >= at for p in e["parents"])
        ):
            raise ValueError("future or nonpreceding original event")
        seen.add(e["id"])
    historical = set()
    for h in d["history"]:
        e = events.get(h["origin_event_id"])
        if (
            e is None
            or e["id"] in historical
            or h["amount"] != e["amount"]
            or h["occurred_at"] != e["at"]
            or h["counterparty_id"]
            != (e["actor"] if e["beneficiary"] == "player" else e["beneficiary"])
        ):
            raise ValueError("historical settlement disagrees with original event")
        expected_code = (
            "incoming_transfer" if e["beneficiary"] == "player" else "card_transfer"
        )
        if h["operation_code"] != expected_code:
            raise ValueError("historical operation reverses real payment direction")
        historical.add(e["id"])
    for o in obligations.values():
        if (
            o["basis"] not in events
            or o["principal"] != events[o["basis"]]["amount"]
            or not {o["debtor"], o["creditor"]} <= parties.keys()
            or o["due"] != START
        ):
            raise ValueError("unsupported due obligation")
    title_uses = set()
    for oid in d["source_obligations"]:
        o = obligations[oid]
        e = events[o["basis"]]
        parents = [events[x] for x in e["parents"]]

        def named(kind):
            matches = [x for x in parents if x["kind"] == kind]
            if len(matches) != 1:
                raise ValueError("required original economic cause missing")
            return matches[0]

        kind = e["kind"]
        if kind == "unused_advance_return_due":
            original = named("contractor_advance_paid")
            used = named("nonrefundable_completed_work")
            if (
                original["beneficiary"] != o["debtor"]
                or used["actor"] != o["debtor"]
                or original["id"] not in used["parents"]
                or Decimal(original["amount"]) - Decimal(used["amount"])
                != Decimal(o["principal"])
            ):
                raise ValueError(
                    "partial cancellation exceeds actual advance less accepted work"
                )
        elif kind == "remaining_member_principal_due":
            original = named("member_loan_disbursed")
            prior = named("member_principal_partly_repaid")
            if (
                original["beneficiary"] != o["debtor"]
                or prior["actor"] != o["debtor"]
                or prior["beneficiary"] != "player"
                or original["id"] not in prior["parents"]
                or Decimal(original["amount"]) - Decimal(prior["amount"])
                != Decimal(o["principal"])
            ):
                raise ValueError("repayment right does not belong to actual borrower")
        elif kind in {"remaining_cancelled_advance_due", "unused_lease_advance_due"}:
            original = named(
                "training_or_venue_advance_paid"
                if kind == "remaining_cancelled_advance_due"
                else "lease_advance_paid"
            )
            prior = named(
                "partial_cancelled_advance_return"
                if kind == "remaining_cancelled_advance_due"
                else "lease_advance_partly_returned"
            )
            if (
                original["beneficiary"] != o["debtor"]
                or prior["actor"] != o["debtor"]
                or Decimal(original["amount"]) - Decimal(prior["amount"])
                != Decimal(o["principal"])
            ):
                raise ValueError(
                    "remaining refund not bound to actual provider and paid advance"
                )
        elif kind == "earned_fee_balance_due":
            advance = named("coordination_fee_advance")
            accepted = named("coordination_services_accepted")
            if (
                advance["actor"] != o["debtor"]
                or accepted["beneficiary"] != o["debtor"]
                or Decimal(accepted["amount"]) - Decimal(advance["amount"])
                != Decimal(o["principal"])
            ):
                raise ValueError("earned fee exceeds accepted work less advance")
        elif kind == "restoration_balance_due":
            accepted = named("restoration_job_accepted")
            advance = named("restoration_customer_advance")
            prior = named("accepted_restoration_stage_paid")
            if {advance["actor"], prior["actor"], accepted["beneficiary"]} != {
                o["debtor"]
            } or Decimal(accepted["amount"]) - Decimal(advance["amount"]) - Decimal(
                prior["amount"]
            ) != Decimal(o["principal"]):
                raise ValueError(
                    "restoration receivable double consumes prior payments"
                )
        if o["purpose"] == "asset_sale":
            titles = [
                x
                for x in parents
                if x["kind"]
                in {
                    "inherited_lot_title_assigned",
                    "instrument_title_assigned",
                    "equipment_title_assigned",
                }
            ]
            if (
                len(titles) != 1
                or titles[0]["id"] in title_uses
                or titles[0]["beneficiary"] != "player"
                or not any(r["basis"] == titles[0]["id"] for r in d["rights"])
            ):
                raise ValueError("asset sale lacks unique original title/control")
            title_uses.add(titles[0]["id"])
    for right in d["rights"]:
        e = events.get(right["basis"])
        if (
            e is None
            or e["beneficiary"] != right["owner"]
            or right["owner"] != right["controller"]
        ):
            raise ValueError("title/control not established")
    for s in d["strategies"]:
        paid = defaultdict(Decimal)
        ids = set()
        for p in s["payments"]:
            o = obligations.get(p["obligation"])
            if (
                p["id"] in ids
                or o is None
                or (p["payer"], p["beneficiary"]) != (o["debtor"], o["creditor"])
                or Decimal(p["amount"]) <= 0
            ):
                raise ValueError("payment lacks entitlement or repeats identity")
            ids.add(p["id"])
            paid[o["id"]] += Decimal(p["amount"])
        if any(
            amount > Decimal(obligations[oid]["principal"])
            for oid, amount in paid.items()
        ):
            raise ValueError("double use of source or liability")
        c = s["episode"]
        if (s["label"] == 1) != (c is not None) or s["label"] != {
            "low": 0,
            "high": 1,
            "ambiguous": None,
        }[s["band"]]:
            raise ValueError("outcome requires actual criminal subgraph")
        if c:
            source = next(p for p in s["payments"] if p["id"] == c["source_payment"])
            entrusted, offence, custody = (
                events[c[k]]
                for k in ("entrustment_event", "offence_event", "custody_event")
            )
            if (entrusted["kind"], offence["kind"], custody["kind"]) != (
                "third_party_funds_entrusted",
                "intentional_escrow_embezzlement",
                "diverted_funds_in_sender_account",
            ):
                raise ValueError("criminal predicate is not authored embezzlement")
            if not (
                entrusted["actor"] == c["source_owner"]
                and entrusted["beneficiary"]
                == source["payer"]
                == c["source_controller"]
                == c["source_custodian"]
                and offence["parents"] == [entrusted["id"]]
                and custody["parents"] == [offence["id"]]
                and offence["beneficiary"] == custody["beneficiary"] == c["collector"]
                and {
                    source["amount"],
                    entrusted["amount"],
                    offence["amount"],
                    custody["amount"],
                }
                == {c["source_amount"]}
            ):
                raise ValueError("crime ownership/amount/custody mismatch")
            routing = {r["payment"]: r for r in c["routing"]}
            balance = Decimal(0)
            if len(routing) != len(c["routing"]) or not routing.keys() <= ids:
                raise ValueError("invalid crime routing roster")
            for p in s["payments"]:
                if p["id"] == source["id"]:
                    balance += Decimal(c["source_amount"])
                if p["id"] in routing:
                    r = routing[p["id"]]
                    amount = Decimal(r["criminal_amount"])
                    if (
                        not 0 < amount <= Decimal(p["amount"])
                        or r["custodian"] != "player"
                        or r["beneficial_recipient"] != c["collector"]
                        or r["channel"]
                        != (
                            "cash_handover"
                            if p["operation"] == "cash_withdrawal"
                            else "collector_controlled_account"
                        )
                    ):
                        raise ValueError(
                            "crime routing incompatible with actual payment"
                        )
                    balance -= amount
                    if balance < 0:
                        raise ValueError("proceeds used before receipt")
            if balance:
                raise ValueError("criminal proceeds not conserved")
        _validate_authorities(d, s, events, obligations)


def _validate_authorities(d, s, events, obligations):
    payments = {p["id"]: p for p in s["payments"]}
    actual = {p["id"]: p for p in s["actual_payments"]}
    records = {r["payment"]: r for r in s["authority_records"]}
    controls = {r["payment"]: r for r in s["account_control"]}
    c = s["episode"]
    routes = {r["payment"]: r for r in c["routing"]} if c else {}
    if (
        records.keys() != payments.keys()
        or actual.keys() != payments.keys()
        or len(records) != len(s["authority_records"])
        or len(actual) != len(s["actual_payments"])
        or len(controls) != len(s["account_control"])
        or controls.keys() != routes.keys()
    ):
        raise ValueError("actual/authority/control roster mismatch")
    for pid, p in payments.items():
        record = records[pid]
        o = obligations[p["obligation"]]
        a = actual[pid]
        issuer = p["payer"] if p["beneficiary"] == "player" else o["creditor"]
        at = datetime.fromisoformat(record["checked_at"])
        if (
            at.tzinfo is None
            or at > datetime.fromisoformat(START)
            or record["confirms"] != "original_event_and_payment_authority"
        ):
            raise ValueError("future or unsupported confirmation")
        scoped = dict(
            payment=pid,
            issuer=issuer,
            original_event=o["basis"],
            obligation=o["id"],
            claim_id="claim-" + pid,
            amount=p["amount"],
            payer=p["payer"],
            beneficiary=p["beneficiary"],
            purpose=o["purpose"],
            confirms="original_event_and_payment_authority",
            outcome=record["outcome"],
        )
        if any(record.get(k) != v for k, v in scoped.items()):
            raise ValueError("authority scope differs from actual claim")
        if record["outcome"] == "unknown":
            if record["source_event"] is not None or s["allocations_known"]:
                raise ValueError("missing evidence cannot assert outcome")
        else:
            e = events.get(record["source_event"])
            kind = {
                "corroborates": "signed_issuer_payment_authority",
                "refutes": "signed_issuer_allocation_denial",
            }.get(record["outcome"])
            if (
                e is None
                or kind is None
                or e["kind"] != kind
                or e["actor"] != issuer
                or e.get("signed_scope") != scoped
                or o["basis"] not in e["parents"]
                or datetime.fromisoformat(e["at"]) > at
                or not e.get("statement")
            ):
                raise ValueError("record lacks actual checked signed authority/denial")
        diverted = bool(c and (pid == c["source_payment"] or pid in routes))
        expected_settlement = None if not s["allocations_known"] else not diverted
        if (
            any(a.get(k) != v for k, v in p.items())
            or a["settles_obligation"] is not expected_settlement
        ):
            raise ValueError("actual payment disagrees with entitlement allocation")
        expected_beneficiary = c["collector"] if pid in routes else p["beneficiary"]
        expected_origin = (
            c["custody_event"]
            if c and pid == c["source_payment"]
            else controls[pid]["basis"]
            if pid in controls
            else o["basis"]
        )
        if (
            a.get("actual_beneficiary") != expected_beneficiary
            or a.get("actual_origin_event") != expected_origin
            or expected_origin not in events
        ):
            raise ValueError(
                "actual beneficiary/origin differs from checked economic route"
            )
        if c and pid == c["source_payment"]:
            expected_source = dict(
                criminal_amount=c["source_amount"],
                source_owner=c["source_owner"],
                source_controller=c["source_controller"],
                source_custodian=c["source_custodian"],
            )
            if (
                any(a.get(k) != v for k, v in expected_source.items())
                or "lawful_source" in a
            ):
                raise ValueError(
                    "criminal receipt source does not bind episode custody and owner"
                )
        elif any(
            k in a for k in ("source_owner", "source_controller", "source_custodian")
        ) or ("criminal_amount" in a and pid not in routes):
            raise ValueError("unexpected criminal source fields on another payment")
        if (record["outcome"] == "refutes") != diverted or (
            record["outcome"] == "corroborates"
        ) != (expected_settlement is True):
            raise ValueError("signed allocation contradicts actual instruction")
        if p["beneficiary"] == "player" and expected_settlement is True:
            funds = a.get("lawful_source", {})
            basis = events.get(funds.get("basis"))
            if (
                basis is None
                or basis["kind"] != "lawfully_accumulated_source_funds"
                or {
                    basis["actor"],
                    basis["beneficiary"],
                    funds.get("owner"),
                    funds.get("controller"),
                    funds.get("custodian"),
                }
                != {p["payer"]}
                or basis["amount"] != p["amount"]
                or funds.get("amount") != p["amount"]
                or basis["id"] not in events[record["source_event"]]["parents"]
            ):
                raise ValueError("lawful source ownership/custody not established")
        if pid in controls:
            control = controls[pid]
            basis = events.get(control["basis"])
            kind = (
                "collector_cash_handover_instruction"
                if p["operation"] == "cash_withdrawal"
                else "creditor_account_unauthorized_collector_control"
            )
            if (
                basis is None
                or basis["kind"] != kind
                or basis["actor"] != c["collector"]
                or basis["beneficiary"] != p["beneficiary"]
                or basis["amount"] != p["amount"]
                or basis["parents"] != [c["offence_event"]]
                or a.get("custodian") != routes[pid]["custodian"]
                or a.get("delivery_channel") != routes[pid]["channel"]
                or control["controller"] != c["collector"]
                or control["rightful_creditor"] != o["creditor"]
                or control["observed_account_party"]
                != (None if p["operation"] == "cash_withdrawal" else p["beneficiary"])
                or control["settlement_authorized"] is not False
                or a["actual_beneficiary"] != c["collector"]
                or a.get("criminal_amount") != routes[pid]["criminal_amount"]
            ):
                raise ValueError(
                    "observed account or cash delivery lacks collector-control binding"
                )


def _case_projection(d, s):
    obligations = {o["id"]: o for o in d["obligations"]}
    steps = []
    facts = []
    records = []
    actual = []
    paid = defaultdict(Decimal)
    c = s["episode"]
    config = _configuration(
        dict(
            ledger=dict(
                participants=d["participants"], historical_payments=d["history"]
            )
        )
    )
    cards = {
        c["code"]: {k: c[k] for k in ("id", "code", "version")}
        for c in config["card_snapshots"]
    }
    for index, p in enumerate(s["payments"]):
        o = obligations[p["obligation"]]
        credit = p["beneficiary"] == "player"
        code = p["operation"]
        claim = "claim-" + p["id"]
        evidence = deepcopy(
            next(r for r in s["authority_records"] if r["payment"] == p["id"])
        )
        status = {
            "unknown": "unknown",
            "refutes": "contradicted",
            "corroborates": "verified",
        }[evidence["outcome"]]
        facts.append(
            dict(
                id=claim,
                fact_type="source_of_funds" if credit else "payment_purpose",
                verification_status=status,
                provenance="customer_statement"
                if evidence["outcome"] == "unknown"
                else "independent_record",
                available_at=START,
                valid_from=START,
                valid_to=END,
                counterparty_ids=[]
                if code == "cash_withdrawal"
                else [p["payer"] if credit else p["beneficiary"]],
                operation_codes=[code],
                purpose_code=o["purpose"],
                max_credit_amount=p["amount"] if credit else "0.00",
                max_debit_amount="0.00" if credit else p["amount"],
            )
        )
        step = dict(
            step_id=str(uuid5(NAMESPACE_URL, p["id"])),
            card=cards[code],
            amount=p["amount"],
            context={},
            action_details=dict(incoming_kind="bank_transfer", bank_country="RU")
            if code == "incoming_transfer"
            else dict(income_basis="payroll_registry")
            if code == "salary"
            else {},
            interval_minutes=None if index == 0 else 1,
            purpose_code=o["purpose"],
            claim_id=claim,
        )
        if credit:
            step["sender_id"] = p["payer"]
        elif code != "cash_withdrawal":
            step["recipient_id"] = p["beneficiary"]
        steps.append(step)
        payment = deepcopy(next(a for a in s["actual_payments"] if a["id"] == p["id"]))
        if payment["settles_obligation"]:
            paid[o["id"]] += Decimal(p["amount"])
        actual.append(payment)
        records.append(
            dict(
                id=p["id"],
                step_number=index + 1,
                obligation=o["id"],
                amount=p["amount"],
                evidence=evidence,
                actual_payment=deepcopy(payment),
            )
        )
    truth = dict(
        aml_episode_present=None if not s["allocations_known"] else c is not None,
        opening_funds=dict(
            amount="180000.00",
            owner="player",
            controller="player",
            custodian="player",
            source="lawful accumulated savings",
        ),
        actual_payments=actual,
        remaining_obligations=[
            dict(
                id=o["id"],
                principal=o["principal"],
                outstanding=None
                if not s["allocations_known"]
                else money(Decimal(o["principal"]) - paid[o["id"]]),
            )
            for o in d["obligations"]
        ],
        criminal_episode=deepcopy(c),
        account_control=deepcopy(s["account_control"]),
        authority_records=deepcopy(s["authority_records"]),
        rights=deepcopy(d["rights"]),
        dossier_sha256=digest(d),
    )
    return steps, facts, records, truth


def _compile(d):
    _validate_dossier(d)
    projections = [_case_projection(d, s) for s in d["strategies"]]
    config = _configuration(
        dict(
            ledger=dict(
                participants=d["participants"], historical_payments=d["history"]
            )
        )
    )
    behavior = config["behavior"]
    roster = {p["id"]: p for p in d["participants"]}
    for p in behavior["counterparties"]:
        if p["id"] in roster:
            original = roster[p["id"]]
            p.update(
                kind=original["kind"],
                category=original.get("category"),
                personal_relationship="known"
                if original["kind"] == "person"
                else "unknown",
            )
    # Hidden owners/controllers are not public counterparties unless an operation
    # or original observed historical settlement actually names that party.
    used = {h["counterparty_id"] for h in d["history"]}
    for s in d["strategies"]:
        for p in s["payments"]:
            if p["operation"] != "cash_withdrawal":
                used.update({p["payer"], p["beneficiary"]} - {"player"})
    behavior["counterparties"] = [
        p
        for p in behavior["counterparties"]
        if p["id"] in used or p["id"] == "exchange"
    ]
    behavior["profile"] = dict(
        id=PROFILE_CATEGORIES[d["id"]], title=d["title"], description=d["description"]
    )
    facts = [f for _, fs, _, _ in projections for f in fs]
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
    purposes = sorted({o["purpose"] for o in d["obligations"]} | {"unknown"})
    behavior["aml_context"] = dict(
        version="aml-context-v1",
        as_of=END,
        expected_activity=dict(
            period_start=START,
            period_end=END,
            activity_kinds=[p for p in purposes if p != "unknown"],
            expected_credit_min="240000.00",
            expected_credit_max="270000.00",
            expected_debit_min="400000.00",
            expected_debit_max="410000.00",
        ),
        opening_balance_facts=["opening"],
        purpose_catalog=[dict(code=p, title=p.replace("_", " ")) for p in purposes],
        facts=facts,
        history_coverage="complete",
        history_start="2026-08-14T09:00:00+03:00",
        history_end=START,
    )
    cases = []
    for s, (steps, _, records, truth) in zip(d["strategies"], projections):
        row = dict(
            scenario_id=s["id"],
            provenance_group_id=d["id"],
            family_id=d["family"],
            aml_label=s["label"],
            label_status="unresolved" if s["label"] is None else "confirmed",
            review_status="authored_unreviewed",
            review=None,
            author_id="independent-demo-author-v1",
            label_source="new-authored-economic-dossier",
            label_protocol_version="aml-labels-v1",
            population_id="aml-game-balanced-v1",
            label_rationale=s["rationale"],
            author_truth=truth,
            economic_records=records,
            observability=dict(
                distinguishable=s["label"] is not None,
                reason="Only authorities applicable to the selected claim and original entitlement cover a payment; unresolved allocations remain unknown.",
            ),
            hypothesis_source=dict(
                dossier_sha256=digest(d),
                original_event_ids=[e["id"] for e in d["events"]],
            ),
            alternative_explanation=dict(
                lawful="Original rights and actually completed obligations settle.",
                illicit="Unrelated entrusted funds are diverted and routed, while their cover obligations remain outstanding.",
            ),
            necessary_facts=[
                "actual original entitlement",
                "actual source ownership",
                "actual beneficiary and authority",
            ],
            forbidden_information=[
                "label and expected band",
                "hidden predicate offence and controller",
                "root identity",
            ],
            public_snapshot=dict(config=deepcopy(config), steps=steps),
            variant_recipe="preregistered-strategy",
            template_ancestry=["independent-demo-author-v1"],
            provenance=dict(
                root_id=d["id"],
                history_origin_id=d["id"] + "-original-history",
                parent_ids=[],
            ),
        )
        cases.append(
            dict(expected_band=s["band"], rationale=s["rationale"], record=row)
        )
    return dict(round_key=d["id"], title=d["title"], cases=cases)


def author_casebook():
    dossiers = [_dossier(spec) for spec in SPECS]
    return dict(
        version="aml-demo-casebook-v1", rounds=[_compile(d) for d in dossiers]
    ), dossiers


def validate_case(d, row):
    _validate_dossier(d)
    expected = next(
        (
            c["record"]
            for c in _compile(d)["cases"]
            if c["record"]["scenario_id"] == row["scenario_id"]
        ),
        None,
    )
    if expected is None or row != expected:
        raise ValueError(
            "record, actual world or scoped claim differs from authored dossier"
        )


def build_demo(output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    book, dossiers = author_casebook()
    rows = validate_roster(book)
    for d, g in zip(dossiers, book["rounds"]):
        for case in g["cases"]:
            validate_case(d, case["record"])
    validate_sources(rows, protocol())
    inputs = [
        f"resources/aml_dataset/aml-v1/{name}/casebook.jsonl"
        for name in (
            "origins-reviewed/v3",
            "origins-reviewed/v5",
            "diagnostics-reviewed/v1",
            "world-graph-draft/v2",
        )
    ]
    old_inputs = [
        name.replace("world-graph-draft/v2/", "world-graph-draft/v1/")
        for name in inputs
    ]
    # Capture each external casebook once. Both closure and hashes consume these
    # exact bytes, including common inputs in the historical comparison.
    snapshots = {
        name: (ROOT / name).read_bytes() for name in sorted(set(inputs + old_inputs))
    }
    development = []
    for name in inputs:
        development.extend(
            json.loads(line)
            for line in snapshots[name].decode("utf-8").splitlines()
            if line.strip()
        )
    combined = development + rows
    all_features = validate_sources(combined, protocol())
    graph = connected_groups(combined, all_features)
    demo_ids = {r["scenario_id"] for r in rows}
    development_ids = {r["scenario_id"] for r in development}
    cross = [
        gid
        for gid, members in graph["groups"].items()
        if set(members) & demo_ids and set(members) & development_ids
    ]
    demo_groups = {graph["scenario_groups"][sid] for sid in demo_ids}
    engines = {
        r["scenario_id"]: evaluate(
            r["public_snapshot"]["steps"], r["public_snapshot"]["config"]
        )
        for r in rows
    }
    if any(submit_blockers(result) for result in engines.values()):
        raise ValueError("engine rejected demo")
    report = dict(
        version="aml-demo-author-draft-v3",
        required_profile_categories=sorted(PROFILE_CATEGORIES.values()),
        release_ready=False,
        reviewed_rows=0,
        freeze_status="awaiting-independent-domain-review",
        actual_probabilities_available=False,
        demo_records=len(rows),
        rounds=5,
        expected_bands=dict(
            Counter(c["expected_band"] for g in book["rounds"] for c in g["cases"])
        ),
        development_records=len(development),
        demo_components=len(demo_groups),
        combined_components=len(graph["groups"]),
        cross_development_components=cross,
        development_hashes={
            name: sha256(snapshots[name]).hexdigest() for name in inputs
        },
        source_hashes={
            **source_hashes(),
            **{
                name: sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "scripts/aml_dataset/aml_demo_author.py",
                    "scripts/aml_dataset/aml_origins.py",
                    "scripts/aml_dataset/aml_casebook.py",
                    "scripts/aml_demo_casebook.py",
                    "config/aml_scenario_templates.json",
                    "docs/research/2026-09-16-aml-behavior-and-legitimate-context.md",
                )
            },
        },
        rejected_drafts=[],
        limitations=[
            "Expected bands have not been scored.",
            "Independent review and freeze remain pending.",
            "Independence must be rerun whenever development inputs change.",
        ],
    )
    require_independent(graph, demo_ids, development_ids)
    old_inputs = [
        name.replace("world-graph-draft/v2/", "world-graph-draft/v1/")
        for name in inputs
    ]
    old_development = []
    for name in old_inputs:
        old_development.extend(
            json.loads(line)
            for line in snapshots[name].decode("utf-8").splitlines()
            if line.strip()
        )
    old_combined = old_development + rows
    old_features = validate_sources(old_combined, protocol())
    old_graph = connected_groups(old_combined, old_features)
    require_independent(
        old_graph, demo_ids, {r["scenario_id"] for r in old_development}
    )
    report["historical_v1_comparison"] = dict(
        development_hashes={
            name: sha256(snapshots[name]).hexdigest() for name in old_inputs
        },
        combined_records=len(old_combined),
        combined_components=len(old_graph["groups"]),
        demo_components=len({old_graph["scenario_groups"][sid] for sid in demo_ids}),
        cross_development_components=[],
    )
    artifacts = {
        "casebook.json": json_bytes(book),
        "records.jsonl": jsonl_bytes(rows),
        "dossiers.json": json_bytes(dossiers),
        "provenance.json": json_bytes(graph),
        "engine-audit.json": json_bytes(engines),
        "historical-v1-provenance.json": json_bytes(old_graph),
        "audit.json": json_bytes(report),
    }
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "CHECKSUMS.json").write_bytes(
        json_bytes({name: sha256(data).hexdigest() for name, data in artifacts.items()})
    )
    return report
