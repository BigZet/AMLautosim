"""Bounded economic-ledger-first authoring; output is NEVER independent review.

Ten explicit compatible dossiers demonstrate the architecture.  Re-running or
renaming them does not create new origins.  Existing provenance closure, including
feature/shape collisions, is applied without exemptions before reporting counts.
"""

import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from scripts.aml_dataset.aml_casebook import protocol
from scripts.aml_dataset.aml_provenance import connected_groups, digest
from scripts.aml_dataset.aml_training import (
    SEED,
    json_bytes,
    jsonl_bytes,
    source_hashes,
    validate_sources,
)
from src.aml_workshop_simulator.services.semantic_contract import new_config

ROOT = Path(__file__).resolve().parents[2]
VERSION = "aml-economic-origins-draft-v2"
# This is a compatibility roster, not a Cartesian product or an origin quota.
ROSTER = (
    ("service_jobs", "P03", "service", "independent", "reimbursement"),
    ("service_milestones", "P03", "service", "instalments", "principal"),
    ("asset_portfolio", "P04", "asset", "independent", "principal"),
    ("asset_single", "P04", "asset", "instalments", "provider"),
    ("supplier_cancellations", "P02", "advance_return", "independent", "refund"),
    ("supplier_duplicate", "P02", "advance_return", "instalments", "refund"),
    ("loan_consolidation", "P06", "new_loan", "instalments", "principal"),
    ("debt_collection", "P06", "debt_repayment", "independent", "principal"),
    ("family_pool", "P01", "contribution", "independent", "organiser"),
    ("family_cost_return", "P01", "reimbursement", "independent", "reimbursement"),
)
SOURCE_PURPOSE = {
    "service": "service_payment",
    "asset": "asset_sale",
    "advance_return": "refund",
    "new_loan": "loan",
    "debt_repayment": "loan",
    "contribution": "shared_expense",
    "reimbursement": "shared_expense",
}
DEBIT_PURPOSE = {
    "reimbursement": "shared_expense",
    "principal": "loan",
    "provider": "personal_spending",
    "refund": "refund",
    "organiser": "shared_expense",
}
# Three causally admissible schedules, each with exactly the same liabilities.
# An obligation is already due; interleaving never makes an unpaid obligation
# disappear. Incoming receipts and payouts all settle within the same due window.
SCHEDULES = (
    ("in-1", "out-1", "out-2", "in-2", "in-3", "out-3", "cash", "out-4", "out-5"),
    ("in-1", "in-2", "out-1", "in-3", "out-2", "out-3", "cash", "out-4", "out-5"),
    ("in-1", "out-1", "in-2", "out-2", "in-3", "out-3", "out-4", "cash", "out-5"),
)
OBSERVATIONS = ("records", "unavailable", "sources_only", "obligations_only")


def author_roots():
    """Compose finite causal dossiers, with original ownership/debt/cost events."""
    roots = []
    for ordinal, (name, family, source, dependency, debit) in enumerate(ROSTER):
        events, obligations, payments, participants = [], [], [], []
        participants.append(dict(id="player", role="account holder"))
        history = []

        def event(identity, kind, actor, beneficiary, amount, parents=()):
            item = dict(
                id=identity,
                kind=kind,
                actor=actor,
                beneficiary=beneficiary,
                amount=f"{Decimal(amount):.2f}",
                depends_on=list(parents),
                occurred_at=(
                    datetime.fromisoformat("2026-09-01T09:00:00+03:00")
                    + timedelta(hours=len(events))
                ).isoformat(),
            )
            events.append(item)
            return identity

        def obligation(identity, debtor, creditor, amount, basis, purpose):
            obligations.append(
                dict(
                    id=identity,
                    debtor=debtor,
                    creditor=creditor,
                    principal=f"{Decimal(amount):.2f}",
                    outstanding=f"{Decimal(amount):.2f}",
                    origin_event_id=basis,
                    purpose=purpose,
                    due_from="2026-09-13T09:00:00+03:00",
                    due_to="2026-09-14T09:00:00+03:00",
                )
            )

        def historical(identity, code, amount, party, basis):
            # Times derive from causal event ordering, never from a desired group ID.
            time = datetime.fromisoformat(
                next(e["occurred_at"] for e in events if e["id"] == basis)
            )
            history.append(
                dict(
                    id=identity,
                    occurred_at=time.isoformat(),
                    operation_code=code,
                    amount=f"{Decimal(amount):.2f}",
                    counterparty_id=party,
                    category=None,
                    origin_event_id=basis,
                )
            )

        count = 1 if dependency == "instalments" else 3
        for i in range(1, count + 1):
            party = f"funding-{i}"
            amount = 240000 if count == 1 else 80000
            participants.append(
                dict(
                    id=party,
                    role={
                        "service": "customer owing for completed work",
                        "asset": "buyer of player-owned asset",
                        "advance_return": "supplier returning player-funded advance",
                        "new_loan": "lender disbursing new principal",
                        "debt_repayment": "borrower repaying player-funded principal",
                        "contribution": "relative owing agreed shared cost contribution",
                        "reimbursement": "relative repaying player-funded allocated cost",
                    }[source],
                )
            )
            if source == "service":
                contract = event(
                    f"contract-{i}", "service_contract", party, "player", amount
                )
                if dependency == "instalments":
                    stages = [
                        event(
                            f"work-{i}-{j}",
                            "accepted_service_stage",
                            "player",
                            party,
                            80000,
                            [contract],
                        )
                        for j in range(1, 4)
                    ]
                    basis = event(
                        f"accepted-{i}",
                        "completed_project_accepted",
                        party,
                        "player",
                        amount,
                        stages,
                    )
                else:
                    basis = event(
                        f"accepted-{i}",
                        "completed_independent_job_accepted",
                        party,
                        "player",
                        amount,
                        [contract],
                    )
            elif source == "asset":
                owned = event(
                    f"acquisition-{i}", "player_acquired_title", "player", party, amount
                )
                historical(
                    f"acquisition-paid-{i}", "card_transfer", amount, party, owned
                )
                basis = event(
                    f"sale-{i}",
                    "transfer_owned_asset_title_to_buyer",
                    "player",
                    party,
                    amount,
                    [owned],
                )
            elif source == "advance_return":
                ordered = event(f"order-{i}", "supplier_order", "player", party, amount)
                paid = event(
                    f"advance-{i}",
                    "player_paid_supplier_advance",
                    "player",
                    party,
                    amount,
                    [ordered],
                )
                historical(f"advance-paid-{i}", "card_transfer", amount, party, paid)
                ancestors = [paid]
                if dependency == "instalments":
                    duplicate = event(
                        f"duplicate-{i}",
                        "duplicate_supplier_prepayment",
                        "player",
                        party,
                        amount,
                        [paid],
                    )
                    historical(
                        f"duplicate-paid-{i}", "card_transfer", amount, party, duplicate
                    )
                    ancestors.append(duplicate)
                basis = event(
                    f"return-{i}",
                    "duplicate_prepayment_recognised"
                    if dependency == "instalments"
                    else "supplier_cancelled_order",
                    party,
                    "player",
                    amount,
                    ancestors,
                )
            elif source == "new_loan":
                basis = event(
                    f"facility-{i}",
                    "new_executed_loan_facility",
                    party,
                    "player",
                    amount,
                )
            elif source == "debt_repayment":
                basis = event(
                    f"loan-{i}", "player_disbursed_prior_loan", "player", party, amount
                )
                historical(f"loan-paid-{i}", "card_transfer", amount, party, basis)
            elif source == "contribution":
                allocation = event(
                    f"allocation-{i}",
                    "family_cost_allocation_agreed",
                    party,
                    "player",
                    amount,
                )
                basis = event(
                    f"contribution-{i}",
                    "contribution_became_due",
                    party,
                    "player",
                    amount,
                    [allocation],
                )
            else:
                basis = event(
                    f"cost-{i}",
                    "player_paid_cost_for_relative",
                    "player",
                    party,
                    amount,
                )
                historical(f"cost-paid-{i}", "card_transfer", amount, party, basis)
            obligation(
                f"receivable-{i}",
                party,
                "player",
                amount,
                basis,
                SOURCE_PURPOSE[source],
            )
        for i in range(1, 4):
            index = 1 if count == 1 else i
            payments.append(
                dict(
                    id=f"in-{i}",
                    direction="credit",
                    amount="80000.00",
                    obligation_id=f"receivable-{index}",
                    origin_event_id=obligations[index - 1]["origin_event_id"],
                    payer=f"funding-{index}",
                    beneficiary="player",
                    purpose=SOURCE_PURPOSE[source],
                    instalment=i if count == 1 else 1,
                )
            )
        consolidated = debit == "organiser" or (
            debit == "principal" and source != "new_loan"
        )
        for i in range(1, 2 if consolidated else 6):
            party = f"payee-{i}"
            amount = 390000 if consolidated else 78000
            participants.append(
                dict(
                    id=party,
                    role={
                        "reimbursement": "original payer of player allocated cost",
                        "principal": "prior creditor of player",
                        "provider": "personal provider owed for delivered goods",
                        "refund": "original customer owed return of prior advance",
                        "organiser": "family organiser settling allocated vendor costs",
                    }[debit],
                )
            )
            kind = {
                "reimbursement": "payee_paid_cost_for_player",
                "principal": "payee_lent_principal_to_player",
                "provider": "personal_goods_delivered",
                "refund": "customer_advance_received",
                "organiser": "organiser_assumed_vendor_obligation",
            }[debit]
            basis = event(f"payable-basis-{i}", kind, party, "player", amount)
            if debit in {"principal", "refund"}:
                historical(
                    f"prior-credit-{i}", "incoming_transfer", amount, party, basis
                )
            if debit == "refund":
                basis = event(
                    f"cancellation-{i}",
                    "customer_cancelled_order",
                    "player",
                    party,
                    amount,
                    [basis],
                )
            if debit == "organiser":
                basis = event(
                    f"pooled-budget-{i}",
                    "player_owes_organiser_including_own_contribution",
                    "player",
                    party,
                    amount,
                    [basis, *[o["origin_event_id"] for o in obligations]],
                )
            obligation(
                f"payable-{i}", "player", party, amount, basis, DEBIT_PURPOSE[debit]
            )
        for i in range(1, 6):
            index = 1 if consolidated else i
            payable = next(o for o in obligations if o["id"] == f"payable-{index}")
            payments.append(
                dict(
                    id=f"out-{i}",
                    direction="debit",
                    amount="78000.00",
                    obligation_id=payable["id"],
                    origin_event_id=payable["origin_event_id"],
                    payer="player",
                    beneficiary=f"payee-{index}",
                    purpose=DEBIT_PURPOSE[debit],
                    instalment=i if consolidated else 1,
                )
            )
        cash_basis = event(
            "cash-quote",
            "cash_only_personal_vendor_quote_accepted",
            "cash-vendor",
            "player",
            10000,
        )
        participants.append(
            dict(id="cash-vendor", role="personal vendor requiring cash at collection")
        )
        obligation(
            "cash-liability",
            "player",
            "cash-vendor",
            10000,
            cash_basis,
            "personal_spending",
        )
        payments.append(
            dict(
                id="cash",
                direction="debit",
                amount="10000.00",
                obligation_id="cash-liability",
                origin_event_id=cash_basis,
                payer="player",
                beneficiary="cash-vendor",
                purpose="personal_spending",
                instalment=1,
            )
        )
        # Ordinary prior salary is an actual supporting event, shared patterns may merge.
        if not history:
            participants.append(
                dict(
                    id="employer",
                    role="employer paying previous completed employment period",
                )
            )
            earned = event(
                "prior-employment",
                "completed_employment_period",
                "player",
                "employer",
                30000,
            )
            historical("salary-paid", "salary", 30000, "employer", earned)
        roots.append(
            dict(
                root_id=name,
                family_id=family,
                ordinal=ordinal,
                generator_version=VERSION,
                review_status="authored_unreviewed",
                review=None,
                template_ancestry=[
                    "economic-ledger-v1",
                    f"funding-{source}-v1",
                    f"obligation-{debit}-v1",
                ],
                compatibility=dict(
                    funding=source, incoming_dependency=dependency, outgoing=debit
                ),
                ledger=dict(
                    opening_balance="180000.00",
                    opening_origin="lawful savings accumulated before this round; observed historical flows are already reflected",
                    participants=participants,
                    events=events,
                    obligations=obligations,
                    payments=payments,
                    historical_payments=history,
                    future_obligations=[
                        dict(
                            id="new-loan-repayment",
                            debtor="player",
                            creditor="funding-1",
                            principal="240000.00",
                            origin_event_id="facility-1",
                            due_from="2027-09-13T09:00:00+03:00",
                        )
                    ]
                    if source == "new_loan"
                    else [],
                    history_coverage="complete",
                ),
                branch_contract=dict(
                    lawful="All listed completed source events and outstanding liabilities are actual.",
                    criminal="First receipt actual. Second/third receipts are extortion proceeds; all card-transfer cover payments route to collector-controlled accounts instead of settling asserted liabilities. Remaining receipts, opening savings and other debits remain lawful.",
                    unresolved="Origin of second/third receipt and recipient beneficial control are not established; no outcome asserted.",
                ),
            )
        )
    for root in roots:
        root["worlds"] = _author_worlds(root)
        root["branch_contract"]["criminal"] = (
            "See the separately authored criminal world, its predicate events, actual payments, account control, remaining obligations and independent record checks."
        )
    return roots


def _author_worlds(root):
    """Author actual sources/control and check records before observation masking.

    Account party is an observed identifier; actual beneficial participants are
    separately represented. A contrary finding is an affirmative issuer/control
    record, never mere absence of a supporting document.
    """
    ledger = root["ledger"]
    lawful = deepcopy(ledger)
    lawful.update(aml_episode_present=False, claimed_ledger_sha256=digest(ledger))
    lawful["record_checks"] = {}
    for payment in ledger["payments"]:
        identity = payment["id"]
        lawful["record_checks"][identity] = dict(
            check_id="original-check-" + identity,
            availability="available",
            outcome="corroborates",
            checked_at="2026-09-13T09:00:00+03:00",
            payment_id=identity,
            payer=payment["payer"],
            beneficiary=payment["beneficiary"],
            amount=payment["amount"],
            origin_event_id=payment["origin_event_id"],
            evidence=dict(
                kind="signed_original_event_and_payment_authority",
                issuer=payment["payer"]
                if payment["direction"] == "credit"
                else payment["beneficiary"],
                confirms_obligation_id=payment["obligation_id"],
                confirms_amount=payment["amount"],
            ),
            finding=f"Before the round, the issuer confirms event {payment['origin_event_id']}, liability {payment['obligation_id']} and authority for the scheduled {payment['amount']} payment between these parties. This is not confirmation that the future payment has occurred.",
        )
    lawful["remaining_obligations"] = [
        dict(o, outstanding_after_round="0.00") for o in ledger["obligations"]
    ]
    lawful["account_control"] = []
    criminal = deepcopy(lawful)
    criminal["aml_episode_present"] = True
    crime_kinds = {
        "service_jobs": (
            "false_service_order_fraud",
            "customer paid for intentionally nonexistent work",
        ),
        "service_milestones": (
            "false_acceptance_invoice_fraud",
            "project owner paid a fabricated acceptance invoice",
        ),
        "asset_portfolio": (
            "sale_of_stolen_goods",
            "original owner was deprived of a distinct goods lot sold by the scheme",
        ),
        "asset_single": (
            "fraudulent_asset_deposit",
            "prospective buyer paid a deposit for a vehicle the scheme could not sell",
        ),
        "supplier_cancellations": (
            "supplier_escrow_embezzlement",
            "supplier diverted an unrelated customer's escrow",
        ),
        "supplier_duplicate": (
            "fabricated_overpayment_refund_fraud",
            "unrelated business paid a fabricated duplicate-payment demand",
        ),
        "loan_consolidation": (
            "extortion",
            "victim paid a coercive demand to a scheme-controlled funding account",
        ),
        "debt_collection": (
            "employer_funds_embezzlement",
            "debtor diverted employer money rather than repaying with owned funds",
        ),
        "family_pool": (
            "charity_collection_fraud",
            "donor paid a fictional charitable collection",
        ),
        "family_cost_return": (
            "false_care_cost_fraud",
            "care client paid for fictional care expenses",
        ),
    }
    offence, description = crime_kinds[root["root_id"]]
    criminal["predicate_offence"] = offence
    criminal["participants"].append(
        dict(
            id="collector",
            role="knowing scheme collector and beneficial controller of receiving accounts",
        )
    )
    by_payment = {p["id"]: p for p in criminal["payments"]}
    for index in (2, 3):
        identity = f"in-{index}"
        payment = by_payment[identity]
        victim = f"harmed-party-{index}"
        criminal["participants"].append(dict(id=victim, role=description))
        origin = f"offence-{index}"
        custody = f"custody-{index}"
        criminal["events"].extend(
            [
                dict(
                    id=origin,
                    kind=offence,
                    actor=payment["payer"],
                    beneficiary="collector",
                    source_owner=victim,
                    amount=payment["amount"],
                    depends_on=[],
                    occurred_at="2026-09-12T09:00:00+03:00",
                ),
                dict(
                    id=custody,
                    kind="criminal_proceeds_held_in_observed_sender_account",
                    actor=victim,
                    beneficiary=payment["payer"],
                    amount=payment["amount"],
                    depends_on=[origin],
                    occurred_at="2026-09-12T10:00:00+03:00",
                ),
            ]
        )
        money_owner = victim
        if root["root_id"] == "asset_portfolio":
            money_owner = f"stolen-goods-buyer-{index}"
            criminal["participants"].append(
                dict(
                    id=money_owner,
                    role="buyer paying the scheme for a misappropriated asset; distinct from its harmed original owner",
                )
            )
            sale_id = f"stolen-asset-sale-{index}"
            criminal["events"].insert(
                -1,
                dict(
                    id=sale_id,
                    kind="sale_of_misappropriated_asset_to_buyer",
                    actor=payment["payer"],
                    beneficiary=money_owner,
                    amount=payment["amount"],
                    depends_on=[origin],
                    occurred_at="2026-09-12T09:30:00+03:00",
                ),
            )
            criminal["events"][-1].update(actor=money_owner, depends_on=[sale_id])
        payment.update(
            origin_event_id=custody,
            criminal_proceeds=True,
            source_owner=victim,
            source_account_controller=payment["payer"],
            settles_obligation=False,
            cover_obligation_id=payment.pop("obligation_id"),
        )
        payment["source_owner"] = money_owner
        criminal["account_control"].append(
            dict(
                account_party=payment["payer"],
                controller=payment["payer"],
                role="knowing intermediary holding the listed criminal proceeds",
                payment_ids=[identity],
                origin_event_id=custody,
            )
        )
        finding = criminal["record_checks"][identity]
        finding.update(
            outcome="refutes",
            evidence=dict(
                kind="signed_issuer_denial_of_claimed_allocation",
                issuer=payment["payer"],
                denied_obligation_id=payment["cover_obligation_id"],
                denied_payment_id=identity,
                authorised_allocation_amount="0.00",
                scheduled_receipt_class="third_party_pass_through",
            ),
            finding=f"Before the round, the issuer's signed instruction identifies scheduled payment {identity} as third-party pass-through and explicitly denies authority to allocate its {payment['amount']} to {payment['cover_obligation_id']}. This is an affirmative contrary instruction, not missing documentation or confirmation of a completed payment.",
        )
    criminal["events"].append(
        dict(
            id="collector-instruction",
            kind="knowing_collector_remittance_instruction",
            actor="collector",
            beneficiary="player",
            amount="390000.00",
            depends_on=[],
            occurred_at="2026-09-12T08:00:00+03:00",
        )
    )
    for index in range(1, 6):
        identity = f"out-{index}"
        payment = by_payment[identity]
        observed_party = payment["beneficiary"]
        payment.update(
            beneficiary="collector",
            observed_account_party=observed_party,
            origin_event_id="collector-instruction",
            settles_obligation=False,
            cover_obligation_id=payment.pop("obligation_id"),
        )
        criminal["account_control"].append(
            dict(
                account_party=observed_party,
                controller="collector",
                role="nominee destination; asserted creditor has not authorised this account to receive settlement",
                payment_ids=[identity],
                origin_event_id="collector-instruction",
            )
        )
        finding = criminal["record_checks"][identity]
        finding.update(
            outcome="refutes",
            evidence=dict(
                kind="creditor_rejection_and_beneficiary_register",
                issuer=observed_party,
                denied_payment_id=identity,
                denied_obligation_id=payment["cover_obligation_id"],
                authorised_settlement=False,
                account_controller="collector",
            ),
            finding=f"Before the round, creditor {observed_party} explicitly rejects the proposed destination of {identity} as authorised settlement of {payment['cover_obligation_id']}; the independent account-control register identifies a nominee account not authorised by that creditor. The check establishes payment authority, not completion of the future payment.",
        )
    settled = defaultdict(Decimal)
    for payment in criminal["payments"]:
        if payment.get("settles_obligation", True):
            settled[payment["obligation_id"]] += Decimal(payment["amount"])
    criminal["remaining_obligations"] = [
        dict(
            o,
            outstanding_after_round=f"{Decimal(o['outstanding']) - settled[o['id']]:.2f}",
        )
        for o in ledger["obligations"]
    ]
    if root["compatibility"]["funding"] == "new_loan":
        disbursed = sum(
            Decimal(p["amount"])
            for p in criminal["payments"]
            if p["direction"] == "credit" and p.get("settles_obligation", True)
        )
        criminal["future_obligations"][0]["principal"] = f"{disbursed:.2f}"
        criminal["future_obligations"][0]["basis"] = (
            "Only in-1 disburses the facility; the remaining 160000 commitment was not drawn."
        )
    unresolved = deepcopy(lawful)
    unresolved["aml_episode_present"] = None
    for payment in unresolved["payments"]:
        if payment["id"] in {"in-2", "in-3"} or payment["id"].startswith("out-"):
            payment["origin_established"] = False
    for finding in unresolved["record_checks"].values():
        finding.update(
            availability="unavailable",
            outcome="unknown",
            evidence={},
            finding="No original record finding is established in this unresolved world.",
        )
    return dict(lawful=lawful, criminal=criminal, unresolved=unresolved)


def _validate_ledger(root):
    ledger = root["ledger"]
    if set(root.get("worlds", {})) != {"lawful", "criminal", "unresolved"}:
        raise ValueError("explicit actual-world ledgers are required")
    if Decimal(ledger["opening_balance"]) != Decimal("180000.00"):
        raise ValueError("ledger opening balance contradicts fixed financial contract")
    events = {e["id"]: e for e in ledger["events"]}
    obligations = {o["id"]: o for o in ledger["obligations"]}
    parties = {p["id"] for p in ledger["participants"]}
    paid = defaultdict(Decimal)
    for payment in ledger["payments"]:
        obligation = obligations.get(payment["obligation_id"])
        if obligation is None:
            raise ValueError("payment references unknown obligation")
        if payment["origin_event_id"] != obligation["origin_event_id"]:
            raise ValueError("payment origin does not match obligation")
        if (
            payment["payer"] != obligation["debtor"]
            or payment["beneficiary"] != obligation["creditor"]
        ):
            raise ValueError("payment reverses obligation parties")
        paid[obligation["id"]] += Decimal(payment["amount"])
    for obligation in obligations.values():
        if obligation["origin_event_id"] not in events:
            raise ValueError("obligation references unknown origin event")
        if not {obligation["debtor"], obligation["creditor"]} <= parties:
            raise ValueError("unknown obligation participant")
        if paid[obligation["id"]] != Decimal(obligation["outstanding"]):
            raise ValueError("settlement fails to conserve outstanding obligation")
    seen = set()
    for event in ledger["events"]:
        if not set(event["depends_on"]) <= seen:
            raise ValueError("economic dependencies are not causal")
        seen.add(event["id"])
    for payment in ledger["historical_payments"]:
        event = events.get(payment["origin_event_id"])
        if event is None or Decimal(payment["amount"]) != Decimal(event["amount"]):
            raise ValueError("historical payment disagrees with original event amount")
        if payment["occurred_at"] != event["occurred_at"]:
            raise ValueError(
                "historical payment disagrees with original event chronology"
            )
    for obligation in obligations.values():
        if Decimal(obligation["principal"]) != Decimal(
            events[obligation["origin_event_id"]]["amount"]
        ):
            raise ValueError("obligation principal disagrees with original event")
    for world in root.get("worlds", {}).values():
        if Decimal(world["opening_balance"]) != Decimal(ledger["opening_balance"]):
            raise ValueError(
                "actual-world opening balance differs from fixed observed balance"
            )
        if world["claimed_ledger_sha256"] != digest(ledger):
            raise ValueError(
                "authored worlds require reauthoring after economic ledger changes"
            )
        world_events = {e["id"]: e for e in world["events"]}
        participants = {p["id"] for p in world["participants"]}
        if len(world_events) != len(world["events"]) or len(participants) != len(
            world["participants"]
        ):
            raise ValueError("duplicate actual-world event or participant")
        for event in world["events"]:
            if not set(event["depends_on"]) <= set(world_events):
                raise ValueError("unknown actual-world dependency")
            if any(
                datetime.fromisoformat(world_events[parent]["occurred_at"])
                > datetime.fromisoformat(event["occurred_at"])
                for parent in event["depends_on"]
            ):
                raise ValueError("actual-world dependency follows its consequence")
        actual = {p["id"]: p for p in world["payments"]}
        if set(actual) != {p["id"] for p in ledger["payments"]}:
            raise ValueError("actual-world payment roster differs from observed round")
        for claimed in ledger["payments"]:
            payment = actual[claimed["id"]]
            if (
                payment["amount"] != claimed["amount"]
                or payment["direction"] != claimed["direction"]
            ):
                raise ValueError("actual-world payment amount/direction mismatch")
            if (
                not {payment["payer"], payment["beneficiary"]} <= participants
                or payment["origin_event_id"] not in world_events
            ):
                raise ValueError(
                    "actual-world payment requires known origin and participants"
                )
            finding = world["record_checks"][claimed["id"]]
            checked_at = datetime.fromisoformat(finding["checked_at"])
            if checked_at.tzinfo is None or checked_at.utcoffset() is None:
                raise ValueError("record finding requires timezone-aware checked_at")
            if finding["outcome"] not in {
                "corroborates",
                "refutes",
                "unknown",
            } or finding["availability"] not in {"available", "unavailable"}:
                raise ValueError("invalid record finding outcome or availability")
            if any(
                finding[key] != claimed[key]
                for key in ("payer", "beneficiary", "amount", "origin_event_id")
            ):
                raise ValueError("record finding scope differs from claimed payment")
            if finding["outcome"] == "refutes" and finding.get("evidence", {}).get(
                "kind"
            ) not in {
                "signed_issuer_denial_of_claimed_allocation",
                "creditor_rejection_and_beneficiary_register",
            }:
                raise ValueError(
                    "contrary finding requires affirmative contrary evidence"
                )
            if finding["outcome"] == "corroborates":
                evidence = finding.get("evidence", {})
                issuer = (
                    claimed["payer"]
                    if claimed["direction"] == "credit"
                    else claimed["beneficiary"]
                )
                if (
                    evidence.get("kind")
                    != "signed_original_event_and_payment_authority"
                    or evidence.get("issuer") != issuer
                    or evidence.get("confirms_obligation_id")
                    != claimed["obligation_id"]
                    or evidence.get("confirms_amount") != claimed["amount"]
                ):
                    raise ValueError(
                        "corroborating finding requires scoped original-event and payment-authority evidence"
                    )
        if world["aml_episode_present"] is True:
            if sum(
                Decimal(p["amount"])
                for p in actual.values()
                if p.get("criminal_proceeds")
            ) != Decimal("160000.00"):
                raise ValueError(
                    "authored criminal episode has inconsistent source amount"
                )
            for payment in actual.values():
                if (
                    payment.get("criminal_proceeds")
                    and not {
                        payment["source_owner"],
                        payment["source_account_controller"],
                    }
                    <= participants
                ):
                    raise ValueError("criminal source account/owner is unbound")
        if (
            root["compatibility"]["funding"] == "new_loan"
            and world["aml_episode_present"] is not None
        ):
            disbursed = sum(
                Decimal(p["amount"])
                for p in actual.values()
                if p["direction"] == "credit" and p.get("settles_obligation", True)
            )
            if Decimal(world["future_obligations"][0]["principal"]) != disbursed:
                raise ValueError(
                    "future loan liability differs from actual facility disbursement"
                )


def _configuration(root):
    # Reuse immutable mechanics, never an old scenario's story/steps/history/labels.
    fixture = json.loads(
        (ROOT / "config/aml_scenario_templates.json").read_text(
            encoding="utf-8"
        )
    )
    config = new_config(fixture["config"])
    config["schema_version"] = 10
    behavior = config["behavior"]
    behavior["timeline"]["starts_at"] = "2026-09-13T09:00:00+03:00"
    behavior["counterparties"] = [
        dict(
            id=p["id"],
            name=p["role"],
            kind="institution" if p["id"] == "employer" else "person",
            information_status="sufficient",
            personal_relationship="known" if p["id"] != "employer" else "unknown",
            category="employer" if p["id"] == "employer" else None,
        )
        for p in root["ledger"]["participants"]
        if p["id"] not in {"player", "cash-vendor"}
    ]
    behavior["counterparties"].append(
        dict(
            id="exchange",
            name="Available exchange",
            kind="institution",
            information_status="sufficient",
            personal_relationship="unknown",
            category="crypto_exchange",
        )
    )
    behavior["profile"] = dict(
        id="account-holder",
        title="Account holder",
        description="Known obligations and record scope are shown separately for each payment.",
    )
    behavior["history"]["operations"] = [
        {k: v for k, v in e.items() if k != "origin_event_id"}
        for e in root["ledger"]["historical_payments"]
    ]
    for e in behavior["history"]["operations"]:
        if e["operation_code"] == "incoming_transfer":
            e.update(incoming_kind="bank_transfer", bank_country="RU")
    return config


def _project(root, world, schedule, evidence_mode):
    config = _configuration(root)
    ledger = root["ledger"]
    start = config["behavior"]["timeline"]["starts_at"]
    end = "2026-09-14T09:00:00+03:00"
    facts, steps, records = [], [], []
    payments = {p["id"]: p for p in ledger["payments"]}
    cards = {
        c["code"]: {k: c[k] for k in ("id", "code", "version")}
        for c in config["card_snapshots"]
    }
    for number, identity in enumerate(SCHEDULES[schedule], 1):
        payment = payments[identity]
        credit = payment["direction"] == "credit"
        code = (
            "incoming_transfer"
            if credit
            else "cash_withdrawal"
            if identity == "cash"
            else "card_transfer"
        )
        finding = world["record_checks"][identity]
        # Missing originals and control checks are independent observation regimes.
        unavailable = (
            finding["availability"] == "unavailable"
            or evidence_mode == "unavailable"
            or (evidence_mode == "sources_only" and not credit)
            or (evidence_mode == "obligations_only" and credit)
        )
        status = (
            "unknown"
            if finding["outcome"] == "unknown"
            else "unverified"
            if unavailable
            else "contradicted"
            if finding["outcome"] == "refutes"
            else "verified"
        )
        claim = "claim-" + identity
        fact = dict(
            id=claim,
            fact_type="source_of_funds" if credit else "payment_purpose",
            verification_status=status,
            provenance="customer_statement" if unavailable else "independent_record",
            available_at=max(
                datetime.fromisoformat(start),
                datetime.fromisoformat(finding["checked_at"]),
            ).isoformat(),
            valid_from=start,
            valid_to=end,
            counterparty_ids=[payment["payer"] if credit else payment["beneficiary"]]
            if identity != "cash"
            else [],
            operation_codes=[code],
            purpose_code=payment["purpose"],
            max_credit_amount=payment["amount"] if credit else "0.00",
            max_debit_amount="0.00" if credit else payment["amount"],
        )
        facts.append(fact)
        step = dict(
            step_id=str(uuid5(NAMESPACE_URL, identity)),
            card=cards[code],
            amount=payment["amount"],
            context={},
            action_details=dict(incoming_kind="bank_transfer", bank_country="RU")
            if credit
            else {},
            interval_minutes=None if number == 1 else 1,
            purpose_code=payment["purpose"],
            claim_id=claim,
        )
        if credit:
            step["sender_id"] = payment["payer"]
        elif identity != "cash":
            step["recipient_id"] = payment["beneficiary"]
        steps.append(step)
        records.append(
            dict(
                record_id=claim,
                step_number=number,
                operation=code,
                **deepcopy(payment),
                observed_record_status=status,
                observed_record_reason="Original settlement and beneficiary-control check unavailable; absence does not establish an outcome."
                if unavailable
                else finding["finding"],
                record_check=deepcopy(finding),
                actual_payment=deepcopy(
                    next(p for p in world["payments"] if p["id"] == identity)
                ),
            )
        )
    facts.append(
        dict(
            id="opening",
            fact_type="opening_balance",
            verification_status="verified",
            provenance="scenario_record",
            available_at=start,
            valid_from=start,
            valid_to=end,
            counterparty_ids=[],
            operation_codes=[],
            purpose_code="unknown",
            max_credit_amount="180000.00",
            max_debit_amount="180000.00",
        )
    )
    purposes = sorted({p["purpose"] for p in ledger["payments"]} | {"unknown"})
    config["behavior"]["aml_context"] = dict(
        version="aml-context-v1",
        as_of=end,
        expected_activity=dict(
            period_start=start,
            period_end=end,
            activity_kinds=[p for p in purposes if p != "unknown"],
            expected_credit_min="240000.00",
            expected_credit_max="240000.00",
            expected_debit_min="400000.00",
            expected_debit_max="400000.00",
        ),
        opening_balance_facts=["opening"],
        purpose_catalog=[dict(code=p, title=p.replace("_", " ")) for p in purposes],
        facts=facts,
        history_coverage=ledger["history_coverage"],
        history_start="2026-08-14T09:00:00+03:00",
        history_end=start,
    )
    return dict(config=config, steps=steps), records


def compile_root(root):
    """12 matched pairs + preassigned alternating extra; unresolved is additional.

    This allocation is per authored dossier, not a claim of 25 per final component.
    Closure can merge dossiers; the report makes resulting quota failure explicit.
    """
    _validate_ledger(root)
    result = []
    recipes = [
        (s, mode, label, False)
        for s in range(3)
        for mode in OBSERVATIONS
        for label in (0, 1)
    ]
    recipes += [
        (0, "records", root["ordinal"] % 2, True),
        (0, "unavailable", None, False),
    ]
    for schedule, mode, label, extra in recipes:
        world = root["worlds"][{0: "lawful", 1: "criminal", None: "unresolved"}[label]]
        if world["aml_episode_present"] != (None if label is None else bool(label)):
            raise ValueError("world outcome does not match authored branch")
        public, records = _project(root, world, schedule, mode)
        if extra:
            opening = next(
                f
                for f in public["config"]["behavior"]["aml_context"]["facts"]
                if f["id"] == "opening"
            )
            opening.update(
                verification_status="unverified", provenance="customer_statement"
            )
        recipe = f"schedule-{schedule}-{mode}" + (
            "-opening-unverified" if extra else ""
        )
        sid = f"{root['root_id']}-{recipe}-{label}{'-extra' if extra else ''}"
        truth = dict(
            aml_episode_present=world["aml_episode_present"],
            opening_funds=f"Lawful accumulated savings, {world['opening_balance']} RUB.",
            lawful_receipts=[
                p["id"]
                for p in world["payments"]
                if p["direction"] == "credit"
                and not p.get("criminal_proceeds")
                and p.get("origin_established", True)
            ],
            actual_world_sha256=digest(world),
            actual_payments=deepcopy(world["payments"]),
            account_control=deepcopy(world["account_control"]),
            remaining_obligations=deepcopy(world["remaining_obligations"]),
            future_obligations=deepcopy(world["future_obligations"]),
        )
        if label == 1:
            available, allocations = Decimal(0), []
            for identity in SCHEDULES[schedule]:
                if identity in {"in-2", "in-3"}:
                    available += Decimal("80000.00")
                if identity.startswith("out-"):
                    amount = min(available, Decimal("78000.00"))
                    available -= amount
                    allocations.append(
                        dict(payment=identity, criminal_amount=f"{amount:.2f}")
                    )
            if available != 0:
                raise ValueError("schedule leaves authored criminal proceeds unrouted")
            truth["criminal_episode"] = dict(
                predicate_offence=world["predicate_offence"],
                actual_source_events=[
                    deepcopy(e)
                    for e in world["events"]
                    if e["id"].startswith(("offence-", "custody-"))
                ],
                criminal_amount="160000.00",
                lawful_funds_contributed_to_collectors="230000.00",
                routing_allocations=allocations,
                collector_controlled_payments=[f"out-{i}" for i in range(1, 6)],
                cover_obligations_not_settled=[f"out-{i}" for i in range(1, 6)],
                continuing_lawful_payments=["cash"],
                actual_obligation_override="Claimed card-transfer liabilities are cover: collectors receive these payments without settling those liabilities. The lawful cash vendor liability persists. The actual source receivable remains outstanding for the two criminal receipts.",
                cover_source_events=[
                    r["origin_event_id"] for r in records if r["id"] in {"in-2", "in-3"}
                ],
                cover_debit_events=[
                    r["origin_event_id"] for r in records if r["id"].startswith("out-")
                ],
            )
        result.append(
            dict(
                scenario_id=sid,
                provenance_group_id=root["root_id"],
                family_id=root["family_id"],
                aml_label=label,
                label_status="unresolved" if label is None else "confirmed",
                review_status="authored_unreviewed",
                review=None,
                author_id="economic-ledger-author-v1",
                label_source="authored-economic-ledger",
                label_protocol_version="aml-labels-v1",
                population_id="aml-game-balanced-v1",
                label_rationale="Outcome unestablished; exclude from supervised learning."
                if label is None
                else "Complete authored world has lawful actual sources and obligations."
                if label == 0
                else "Actual authored criminal proceeds are knowingly routed to collectors; record findings independently determine observations.",
                author_truth=truth,
                economic_records=records,
                observability=dict(
                    distinguishable=label is not None and mode != "unavailable",
                    reason="Available source/control or obligation records distinguish the specific counterfactual; hidden offence is never visible."
                    if label is not None and mode != "unavailable"
                    else "Matched opposite-truth worlds have identical available observations; preserve collision.",
                ),
                hypothesis_source=dict(
                    root_dossier_sha256=digest(root),
                    original_event_records=[e["id"] for e in root["ledger"]["events"]],
                ),
                alternative_explanation=dict(
                    lawful="Documented independent source obligations can fund the due liabilities.",
                    illicit="Apparent settlement can conceal a separately authored criminal-proceeds episode.",
                ),
                necessary_facts=[
                    "actual economic source of each receipt",
                    "actual liability and beneficial recipient of each debit",
                ],
                forbidden_information=[
                    "predicate offence truth",
                    "author labels",
                    "root and template identifiers",
                ],
                public_snapshot=public,
                variant_recipe=recipe,
                preassigned_extra=extra,
                template_ancestry=root["template_ancestry"],
                provenance=dict(
                    root_id=root["root_id"],
                    counterfactual_pair_id=root["root_id"] + "-" + recipe,
                    history_origin_id=root["root_id"] + "-causal-history",
                ),
            )
        )
    return result


def build_origins(output):
    """Validate every candidate, close provenance, write review-ready DRAFT files."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    roots = author_roots()
    rows = [row for root in roots for row in compile_root(root)]
    features = validate_sources(rows, protocol())
    graph = connected_groups(rows, features)
    confirmed = [r for r in rows if r["label_status"] == "confirmed"]
    counts = Counter(graph["scenario_groups"][r["scenario_id"]] for r in confirmed)
    collisions = defaultdict(list)
    for row in confirmed:
        collisions[digest(features[row["scenario_id"]])].append(row)
    conflicts = [
        dict(feature_sha256=k, scenario_ids=[r["scenario_id"] for r in group])
        for k, group in collisions.items()
        if len({r["aml_label"] for r in group}) > 1
    ]
    report = dict(
        version=VERSION,
        seed=SEED,
        release_ready=False,
        review_status="authored_unreviewed",
        reviewed_rows=0,
        authored_roots=len(roots),
        confirmed_candidate_rows=len(confirmed),
        unresolved_rows=len(rows) - len(confirmed),
        class_counts=dict(Counter(str(r["aml_label"]) for r in confirmed)),
        post_closure_components=len(graph["groups"]),
        component_sizes=dict(counts),
        minimum_components_required=1200,
        minimum_confirmed_rows_required=30000,
        reviewed_component_count=0,
        contradictory_feature_clusters=len(conflicts),
        variant_contract="12 matched pairs plus alternating extra per dossier; NOT a final-component allocation",
        final_component_uniform_25_achieved=all(n == 25 for n in counts.values()),
        challenge_freeze_status="not_frozen_not_held_out",
        limitations=[
            "Finite ten-dossier catalogue; no count inflation by resampling.",
            "Independent root and semantic transformation review remains required.",
            "Generic grammar ancestry is shared and is not independent design.",
            "All candidates are development material. No release split or challenge holdout is claimed.",
            "P05/P07/P08/P09/P10 and additional channels are unimplemented in this bounded catalogue.",
            "Family/combination challenge rosters require separate preregistration before model fitting.",
        ],
        source_hashes={
            **source_hashes(),
            "scripts/aml_dataset/aml_origins.py": digest(
                Path(__file__).read_text(encoding="utf-8")
            ),
        },
    )
    files = {
        "roots.jsonl": jsonl_bytes(roots),
        "casebook.jsonl": jsonl_bytes(rows),
        "provenance.json": json_bytes(graph),
        "collisions.json": json_bytes(conflicts),
        "feasibility.json": json_bytes(report),
        "roster.json": json_bytes(
            dict(
                review_status="authored_unreviewed",
                catalogue=ROSTER,
                transformations=dict(schedules=SCHEDULES, observations=OBSERVATIONS),
                excluded_cells=[
                    "No Cartesian multiplication: unlisted combinations have not been authored."
                ],
            )
        ),
    }
    output.mkdir(parents=True)
    for name, content in files.items():
        (output / name).write_bytes(content)
    return report
