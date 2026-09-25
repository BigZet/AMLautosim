"""Reproducible 120-case authored pilot, not a reviewed training dataset."""

import json
import re
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from src.aml_workshop_simulator.services.semantic_contract import new_config

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = "docs/research/2026-09-16-aml-behavior-and-legitimate-context.md"
PURPOSES = [
    "shared_expense",
    "refund",
    "service_payment",
    "asset_sale",
    "personal_spending",
    "loan",
    "family_support",
    "asset_sale",
    "service_payment",
    "shared_expense",
]
# Distinct substantive obligations, not amounts used as label rules.
DETAILS = [
    [
        "siblings settling renovation costs",
        "parents funding moving costs",
        "relatives splitting care expenses",
        "family pooling a planned event",
    ],
    [
        "cancelled repair advance",
        "duplicate customer advance",
        "cancelled lessons advance",
        "unused event deposit",
    ],
    [
        "completed tutoring sessions",
        "delivered repair work",
        "completed design service",
        "completed translation work",
    ],
    [
        "sale of household equipment",
        "sale of a personal vehicle",
        "sale of inherited furniture",
        "sale of a personal collection",
    ],
    [
        "cash payment for personal repairs",
        "cash purchase of used household goods",
        "cash payment for moving help",
        "cash spending on a family event",
    ],
    [
        "repaying a documented personal loan",
        "settling agreed recurring shared costs",
        "repaying instalments for borrowed funds",
        "settling a personal reimbursement obligation",
    ],
    [
        "family relocation support",
        "cross-border shared expense settlement",
        "family care support",
        "repayment by a relative abroad",
    ],
    [
        "sale of owned crypto savings",
        "partial disposal of owned crypto holdings",
        "liquidation of owned crypto after purchase cancellation",
        "sale of a previously acquired crypto position",
    ],
    [
        "resuming freelance work after leave",
        "reactivating account for a personal sale",
        "resuming obligations after relocation",
        "using reserve account for family settlement",
    ],
    [
        "salary plus separately documented family costs",
        "salary plus separately documented refund",
        "salary plus separately documented personal loan",
        "salary plus a separately explained asset sale",
    ],
]


def protocol():
    text = (ROOT / RESEARCH).read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        match = re.match(r"\| ([PF]\d{2}) \|", line)
        if match:
            rows[match[1]] = [part.strip() for part in line.split("|")[2:-1]]
    return {
        "version": "aml-labels-v1",
        "population_id": "aml-game-balanced-v1",
        "outcome": "At least one authored episode moving or concealing criminal proceeds",
        "confirmed_class_prior": 0.5,
        "families": {f"P{i:02}": rows[f"P{i:02}"] for i in range(1, 11)},
        "factors": {f"F{i:02}": rows[f"F{i:02}"] for i in range(1, 26)},
        "unsupported_constraints": {
            f"F{i:02}": rows[f"F{i:02}"] for i in range(26, 33)
        },
        "research_source": RESEARCH,
        "pilot_cases": 120,
        "per_family_status": 4,
        "review_status": "authored_unreviewed",
        "release_gate": "independent domain review and final v10 engine/context audit required",
        "label_rules": {"confirmed": [0, 1], "unresolved": None},
        "forbidden_label_rules": [
            "old risk threshold",
            "three signals",
            "salary/purchase/wait discount",
        ],
    }


def build_casebook():
    fixture = json.loads(
        (ROOT / "config/aml_scenario_templates.json").read_text(
            encoding="utf-8"
        )
    )
    rows = []
    for family_index in range(10):
        family = f"P{family_index + 1:02}"
        for variant in range(4):
            for status in (0, 1, None):
                config = new_config(fixture["config"])
                config["schema_version"] = 10
                route_number = (
                    4
                    if family == "P05"
                    else 9
                    if family == "P10"
                    else [1, 3, 8, 12][variant]
                )
                steps = deepcopy(
                    next(
                        s["steps"]
                        for s in fixture["strategies"]
                        if s["number"] == route_number
                    )
                )
                purpose = PURPOSES[family_index]
                for step in steps:
                    code = step["card"]["code"]
                    step["purpose_code"] = (
                        "salary"
                        if code == "salary"
                        else "personal_spending"
                        if code in {"purchase", "cash_withdrawal"}
                        else purpose
                    )
                    if code == "incoming_transfer":
                        details = {
                            "incoming_kind": "bank_transfer",
                            "bank_country": "KG" if family == "P07" else "RU",
                        }
                        if family == "P08":
                            details = {
                                "incoming_kind": "exchange_withdrawal"
                                if variant % 2 == 0
                                else "crypto_p2p"
                            }
                            if variant % 2 == 0:
                                step["sender_id"] = "exchange"
                        step["action_details"] = details
                start = config["behavior"]["timeline"]["starts_at"]
                history_start = (
                    datetime.fromisoformat(start)
                    - timedelta(days=config["behavior"]["history"]["window_days"])
                ).isoformat()
                end = "2026-10-13T09:00:00+03:00"
                parties = sorted(
                    {
                        s[k]
                        for s in steps
                        for k in ("sender_id", "recipient_id")
                        if s.get(k)
                    }
                )
                verification = (
                    "unknown"
                    if status is None or variant == 3
                    else "verified"
                    if status == 0
                    else "contradicted"
                )
                facts = []
                for kind in ("source_of_funds", "payment_purpose", "relationship"):
                    facts.append(
                        dict(
                            id=kind,
                            fact_type=kind,
                            verification_status=verification,
                            provenance="independent_record"
                            if verification in {"verified", "contradicted"}
                            else "customer_statement",
                            available_at=start,
                            valid_from=start,
                            valid_to=end,
                            counterparty_ids=parties,
                            operation_codes=[
                                "incoming_transfer",
                                "card_transfer",
                                "cash_withdrawal",
                            ],
                            purpose_code=purpose,
                            max_credit_amount="240000.00",
                            max_debit_amount="400000.00",
                        )
                    )
                # Verified opening funds exist in both classes; do not make documentation itself the label.
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
                if status == 1 and variant == 1:
                    facts[0]["verification_status"] = "verified"
                    facts[0]["max_credit_amount"] = "80000.00"
                context = dict(
                    version="aml-context-v1",
                    as_of=end,
                    expected_activity=dict(
                        period_start=start,
                        period_end=end,
                        activity_kinds=[purpose, "salary"]
                        if family == "P10"
                        else [purpose],
                        expected_credit_min="0.00",
                        expected_credit_max="270000.00",
                        expected_debit_min="0.00",
                        expected_debit_max="450000.00",
                    ),
                    opening_balance_facts=["opening"],
                    purpose_catalog=[
                        dict(code=p, title=p.replace("_", " "))
                        for p in sorted(
                            set([purpose, "salary", "personal_spending", "unknown"])
                        )
                    ],
                    facts=facts,
                    history_coverage="partial" if variant == 2 else "complete",
                    history_start=history_start,
                    history_end=start,
                )
                config["behavior"]["aml_context"] = context
                description = DETAILS[family_index][variant]
                unresolved = status is None
                reason = (
                    "The origin and actual obligation cannot be established from available customer statements."
                    if unresolved or variant == 3
                    else "Scoped independent records corroborate the obligation."
                    if status == 0
                    else "Scoped records contradict the claimed obligation; hidden criminal origin remains authored truth, not public evidence."
                )
                rows.append(
                    dict(
                        scenario_id=f"{family}-{variant + 1}-{str(status).lower()}",
                        provenance_group_id=f"{family}-contrast-{variant + 1}",
                        family_id=family,
                        aml_label=status,
                        label_status="unresolved" if unresolved else "confirmed",
                        review_status="authored_unreviewed",
                        author_id="codex-casebook-author",
                        review=None,
                        label_source="authored-case",
                        label_protocol_version="aml-labels-v1",
                        label_rationale="Outcome not established; excluded from supervised fitting."
                        if unresolved
                        else "The authored funds and obligations are lawful; no independent criminal-proceeds episode."
                        if status == 0
                        else "The authored scenario establishes criminal proceeds routed using a false or partially valid obligation; lawful background does not erase this episode.",
                        population_id="aml-game-balanced-v1",
                        split="pilot",
                        hypothesis_source=dict(
                            research=RESEARCH, family=family, description=description
                        ),
                        author_truth=dict(
                            aml_episode_present=None if unresolved else bool(status),
                            narrative=description
                            if status == 0
                            else "Origin and obligation remain undecided between lawful settlement and criminal-proceeds transit."
                            if unresolved
                            else f"Criminal proceeds are knowingly routed under the cover of {description}.",
                            funds_origin="undetermined"
                            if unresolved
                            else "lawful"
                            if status == 0
                            else "criminal_proceeds",
                        ),
                        alternative_explanation=dict(
                            narrative=f"Lawful {description} could produce the same route."
                            if status != 0
                            else f"Criminal-proceeds transit could imitate {description}.",
                            disposition=reason,
                        ),
                        necessary_facts=[
                            "source of opening funds",
                            "source and ownership of each incoming payment",
                            "actual obligation and parties for each debit",
                            "coverage amount and availability time",
                        ],
                        forbidden_information=[
                            "hidden funds origin",
                            "author narrative",
                            "label and rationale",
                            "review outcome",
                            "old risk score",
                        ],
                        observability=dict(
                            distinguishable=not unresolved and variant != 3,
                            reason=reason,
                        ),
                        public_snapshot=dict(config=config, steps=steps),
                    )
                )
    return [refine_case(row) for row in rows]


def refine_case(row):
    """Author a separate original event and directional money fact for every step."""
    from decimal import Decimal

    public = row["public_snapshot"]
    config, steps = public["config"], public["steps"]
    context = config["behavior"]["aml_context"]
    family = row["family_id"]
    variant = int(row["scenario_id"].split("-")[1]) - 1
    label = row["aml_label"]
    incoming_purpose = {
        "P01": "family_support",
        "P02": "refund",
        "P03": "service_payment",
        "P04": "asset_sale",
        "P05": "family_support",
        "P06": "loan",
        "P07": "family_support",
        "P08": "asset_sale",
        "P09": ["service_payment", "asset_sale", "family_support", "loan"][variant],
        "P10": ["family_support", "refund", "loan", "asset_sale"][variant],
    }[family]
    outgoing_purpose = {
        "P01": "shared_expense",
        "P02": "refund",
        "P03": "personal_spending",
        "P04": "personal_spending",
        "P05": "personal_spending",
        "P06": "loan",
        "P07": "family_support",
        "P08": "personal_spending",
        "P09": ["personal_spending", "personal_spending", "shared_expense", "loan"][
            variant
        ],
        "P10": ["shared_expense", "refund", "loan", "personal_spending"][variant],
    }[family]
    variant_key = f"{family}-{variant + 1}"
    if variant_key in {"P01-4", "P06-2", "P06-4", "P07-2", "P09-4"}:
        incoming_purpose = outgoing_purpose = "shared_expense"
    elif variant_key == "P07-4":
        incoming_purpose = outgoing_purpose = "loan"
    if family == "P09":
        config["behavior"]["history"]["operations"] = []
        context["history_coverage"] = "complete"
    facts = [f for f in context["facts"] if f["fact_type"] == "opening_balance"]
    records = [
        dict(
            record_id="opening-ledger",
            event="Personal lawful savings accumulated before the observed window",
            owner="player",
            amount="180000.00",
            date="2026-07-01",
            role="Opening funds pay the first obligations and fees; later receipts replenish the account, not retroactively explain opening funds.",
        )
    ]
    start = config["behavior"]["timeline"]["starts_at"]
    credit = debit = Decimal(0)
    total_credit = total_debit = Decimal(0)
    criminal_steps = []
    income_index = 0
    for index, step in enumerate(steps, 1):
        code = step["card"]["code"]
        amount = Decimal(step["amount"])
        is_credit = code in {"incoming_transfer", "salary"}
        party = step.get("sender_id") if is_credit else step.get("recipient_id")
        purpose = (
            "salary"
            if code == "salary"
            else incoming_purpose
            if is_credit
            else "personal_spending"
            if code in {"cash_withdrawal", "purchase"}
            else outgoing_purpose
        )
        step["purpose_code"] = purpose
        claim = f"money-{index}"
        step["claim_id"] = claim
        if code == "salary":
            status = "verified"
            event = f"Employer {party} payroll registry pays player {amount:.2f} RUB for completed work; separate from other flows."
        elif is_credit:
            income_index += 1
            event = {
                "shared_expense": f"Participant {party} settles {amount:.2f} RUB under the explicit shared cost record supplied below.",
                "family_support": f"Sender {party} transfers {amount:.2f} RUB of their documented savings to player under family support agreement support-{index}, signed before the round.",
                "refund": f"Sender {party} returns {amount:.2f} RUB previously advanced by player on 2026-07-{10 + index:02}; original paid advance receipt advance-in-{index} names player as payer and {party} as recipient. Cancellation requires the full sum back.",
                "service_payment": f"Client {party} pays {amount:.2f} RUB to player for completed service order service-{index}; order and acceptance certificate name both parties, this exact fee, and completion before round start.",
                "asset_sale": f"Buyer {party} pays player {amount:.2f} RUB for player-owned {'crypto position' if family == 'P08' else 'personal asset lot'} lot-{index}; original ownership/acquisition record dated 2026-06-{index:02} and sale settlement record name player as seller and this exact proceeds amount. {'Exchange withdrawal of player-owned assets, not third-party routing; category alone does not prove ownership.' if step['action_details'].get('incoming_kind') == 'exchange_withdrawal' else 'The buyer or P2P settlement party is the named sender.'}",
                "loan": f"Lender {party} disburses {amount:.2f} RUB to player under signed personal loan loan-in-{index}, dated 2026-07-{10 + index:02}; the player is borrower, loan amount equals this payment and stated use is personal obligations.",
            }[purpose]
            status = (
                "unknown"
                if label is None or variant == 3
                else "verified"
                if label == 0 or (label == 1 and variant == 1 and income_index == 1)
                else "contradicted"
            )
        else:
            if code == "cash_withdrawal":
                event = f"Player withdraws {amount:.2f} RUB for cash settlement of personal obligation cash-{index}; prior quote names player as payer and cash is required for moving/repair work. Cash recipient is outside account observations; no counterparty identifier is invented."
            elif code == "purchase":
                event = f"Player buys personal household goods from merchant {party} for {amount:.2f} RUB; receipt purchase-{index} establishes player as final consumer."
            elif purpose == "refund":
                event = f"Player returns {amount:.2f} RUB to customer {party} on cancelled original advance advance-out-{index}; original receipt dated 2026-07-{index:02} records {party} paying player this amount, and cancellation agreement requires full repayment to the same customer. Opening savings and newly returned advances fund the refunds."
            elif purpose == "loan":
                event = f"Player repays {amount:.2f} RUB principal to lender {party} for separate prior personal loan loan-out-{index}; original 2026-07-{index:02} loan receipt records {party} lending this amount to player and repayment falls due during this round. New loan receipts do not assert that this creditor supplied the new loan."
            elif purpose == "shared_expense":
                event = f"Player pays {amount:.2f} RUB to family organiser {party} for player/family share of obligation shared-{index}; cost schedule signed 2026-07-{index:02} names both parties and organiser's duty to settle renovation/care/moving invoices."
            elif purpose == "family_support":
                event = f"Player provides {amount:.2f} RUB to relative {party} for their agreed care/relocation expense support-out-{index}; recipient is the final supported relative, independent of the sender of foreign receipts."
            else:
                event = f"Player pays {amount:.2f} RUB to provider {party} for separate personal moving/repair/household obligation personal-{index}; dated quote 2026-07-{index:02} names player as end customer and {party} as provider. Asset-sale proceeds explain funding, while this obligation independently explains the debit."
            status = (
                "unknown"
                if label is None or variant == 3
                else "verified"
                if label == 0 or code == "purchase"
                else "contradicted"
            )
        event, event_details = variant_event(
            variant_key, code, index, income_index, party, amount, event
        )
        facts.append(
            dict(
                id=claim,
                fact_type="source_of_funds" if is_credit else "payment_purpose",
                verification_status=status,
                provenance="independent_record"
                if status in {"verified", "contradicted"}
                else "customer_statement",
                available_at=start,
                valid_from=start,
                valid_to=context["expected_activity"]["period_end"],
                counterparty_ids=[party] if party else [],
                operation_codes=[code],
                purpose_code=purpose,
                max_credit_amount=f"{amount if is_credit else Decimal(0):.2f}",
                max_debit_amount=f"{Decimal(0) if is_credit else amount:.2f}",
            )
        )
        records.append(
            dict(
                record_id=claim,
                step_number=index,
                operation=code,
                amount=f"{amount:.2f}",
                payer=party if is_credit else "player",
                recipient="player" if is_credit else party or "player-cash",
                original_event=event,
                observed_record_status=status,
                observed_record_reason="The independent record corroborates the stated original event and amount."
                if status == "verified"
                else "The independent record establishes that the stated order/advance/obligation was not entered into by these parties for this payment."
                if status == "contradicted"
                else "Only a customer statement is available; original records are absent. No hidden outcome is asserted as evidence.",
            )
        )
        if event_details:
            records[-1]["event_details"] = event_details
        if is_credit:
            total_credit += amount
            if status == "verified":
                credit += amount
        else:
            total_debit += amount
            if status == "verified":
                debit += amount
        if label == 1 and code not in {"salary", "purchase"} and status != "verified":
            criminal_steps.append(index)
    purposes = sorted({f["purpose_code"] for f in facts})
    context["facts"] = facts
    context["purpose_catalog"] = [
        dict(code=p, title=p.replace("_", " ")) for p in purposes
    ]
    context["expected_activity"]["activity_kinds"] = sorted(
        {s["purpose_code"] for s in steps}
    )
    row["economic_records"] = records
    row["hypothesis_source"]["original_event_records"] = [
        r["record_id"] for r in records
    ]
    row["hypothesis_source"]["flow_summary"] = (
        f"Opening lawful savings 180000.00 RUB; round credits {total_credit:.2f}; round debits {total_debit:.2f}. Every material payment has a separately numbered original event with named participants, direction and amount. Fees remain determined by the game resource engine."
    )
    row["expected_evidence"] = dict(
        verified_credit_amount=f"{credit:.2f}",
        verified_debit_amount=f"{debit:.2f}",
        contradicted_steps=[
            r["step_number"]
            for r in records
            if r.get("observed_record_status") == "contradicted"
        ],
    )
    if label == 1 and variant_key == "P04-2":
        row["author_truth"]["vehicle_sale_counterexample"] = dict(
            asset_id="owned-vehicle-01",
            agreed_sale_total="240000.00",
            lawful_sale_receipt="80000.00",
            criminal_receipts="160000.00",
            narrative="One genuinely player-owned vehicle was sold under a 240000 RUB agreement payable in three instalments. The first 80000 receipt is genuine buyer payment. The last two 80000 receipts are extortion proceeds supplied by the scheme under the same buyer identifier, not payments fulfilling the vehicle debt. Independent records contradict those two claimed instalments; the actual lawful sale and first receipt remain valid.",
        )
    if label == 1:
        criminal_credits = [
            r["step_number"]
            for r in records
            if r.get("operation") == "incoming_transfer"
            and r["observed_record_status"] != "verified"
        ]
        first_criminal_credit = min(criminal_credits)
        row["author_truth"]["criminal_role"] = dict(
            criminal_credit_steps=criminal_credits,
            subsequent_routing_steps=[
                i
                for i in criminal_steps
                if i > first_criminal_credit
                and steps[i - 1]["card"]["code"] not in {"incoming_transfer", "salary"}
            ],
            prefunding_steps=[i for i in criminal_steps if i < first_criminal_credit],
            role="Player knowingly receives proceeds of an authored extortion offence under the listed cover events and routes them to the scheme's collectors. Earlier payments use lawful opening savings as prefunding and are not described as criminal-source receipts. Verified receipts, salary, purchases and opening funds remain separate lawful episodes; a verified credit does not explain an unrelated criminal receipt.",
        )
    return row


def variant_event(key, code, index, instalment, party, amount, default):
    """Concrete original events for the nine reviewed economic variants."""
    credit = code == "incoming_transfer"
    value = f"{amount:.2f}"
    direction = "in" if credit else "out"
    record_id = f"{key}-original-{direction}-{index}"
    details = dict(
        original_record_id=record_id,
        relationship="family members"
        if key.startswith(("P01", "P07", "P09"))
        else "known participant in the stated obligation",
    )
    if key == "P04-2" and credit:
        details.update(
            category="single_vehicle_sale",
            asset_id="owned-vehicle-01",
            sale_total="240000.00",
            instalment_number=instalment,
            original_record_id="vehicle-sale-agreement-01",
            relationship="vehicle buyer A and player seller",
        )
        return (
            f"Buyer {party} pays player {value} RUB as instalment {instalment} of 3 for the same owned-vehicle-01. Ownership certificate vehicle-acquisition-01 dated 2026-06-01 names player; vehicle-sale-agreement-01 dated 2026-09-01 names buyer A and player and sets one total price 240000.00 RUB in three 80000.00 instalments. This is one vehicle, not three asset lots. Verification separately checks each actual receipt against the buyer's instalment record.",
            details,
        )
    if key == "P01-4" and code in {"incoming_transfer", "card_transfer"}:
        details.update(category="family_event", event_id="family-celebration-01")
        if credit:
            text = f"Family contributor {party} pays player {value} RUB for planned family-celebration-01 under contribution schedule {record_id} dated 2026-08-01. Player coordinates the family event; this amount is that relative's agreed contribution, not a gift for repairs."
        else:
            text = f"Player pays family organiser {party} {value} RUB for event cost allocation {record_id} dated 2026-08-01: venue/catering obligation for family-celebration-01. Organiser must settle this exact allocated event cost, while player also contributes from lawful opening savings. No renovation/care/moving invoices explain this payment."
        return text, details
    if key == "P01-4" and code == "cash_withdrawal":
        details.update(
            category="family_event",
            event_id="family-celebration-01",
            relationship="player event coordinator and cash-only celebration vendor",
        )
        return (
            f"Player withdraws {value} RUB for family-celebration-01 event vendor obligation {record_id} dated 2026-08-01. The celebration decorations supplier requires exactly {value} RUB cash and a signed event receipt; this distinct cash allocation accompanies the organiser's venue/catering costs. No vendor account identifier is invented.",
            details,
        )
    if key in {"P05-2", "P05-4"} and code == "cash_withdrawal":
        if key == "P05-2":
            details.update(
                category="used_household_goods",
                goods_lot=f"used-goods-{index}",
                relationship="player end buyer and private used-goods seller",
            )
            text = f"Player withdraws {value} RUB to buy used household goods lot used-goods-{index} under agreed cash purchase quote {record_id} dated 2026-09-01. This separate furniture/appliance lot costs exactly {value} RUB; private seller requires cash and signs a collection receipt for this amount. Seller is outside observed account counterparties; no seller identifier is invented."
        else:
            details.update(
                category="family_event_cash",
                event_id="family-event-01",
                relationship="player family-event organiser and cash-only event vendor",
            )
            text = f"Player withdraws {value} RUB for family-event-01 cash-only vendor obligation {record_id} dated 2026-09-01. This distinct catering/decorations allocation requires exactly {value} RUB cash and a vendor receipt upon settlement. It is an event requirement, not moving/repair work; vendor is not an observed account counterparty."
        return text, details
    if key in {"P06-2", "P06-4", "P07-2", "P09-4"} and code in {
        "incoming_transfer",
        "card_transfer",
    }:
        category = {
            "P06-2": "recurring_shared_cost",
            "P06-4": "personal_reimbursement",
            "P07-2": "cross_border_shared_cost",
            "P09-4": "reserve_account_family_settlement",
        }[key]
        details.update(category=category)
        cost = {
            "P06-2": "recurring household utilities/rent cost",
            "P06-4": "personal household purchase",
            "P07-2": "family relocation shared cost",
            "P09-4": "family care/shared household cost",
        }[key]
        original_payer = "player" if credit else party
        owing = party if credit else "player"
        details.update(
            original_payer=original_payer,
            owing_participant=owing,
            original_cost_amount=value,
        )
        text = f"{'Relative abroad' if key == 'P07-2' and credit else 'Family participant' if key in {'P07-2', 'P09-4'} else 'Known cost participant'} {party} {'reimburses player' if credit else 'receives reimbursement from player'} {value} RUB under allocation {record_id}. Original receipt dated 2026-08-{min(index, 28):02} names {original_payer} as payer of this {cost} on behalf of {owing}; signed cost allocation establishes exactly {value} RUB owed by {owing}. This settles a previously paid expense, not loan principal or a new support gift."
        if key == "P06-2":
            text += " This is one separately dated monthly recurring cost allocation, independent of other receipts and payouts."
        if key == "P07-2":
            text += " Shared-cost schedule names the foreign-bank sender and the player as settlement participants; the bank country does not establish the obligation."
        if key == "P09-4":
            text += " The player uses the reserve account after the complete empty preceding 30-day history; relatives agreed to settle these previously allocated family costs during this round."
        return text, details
    if key == "P07-4" and code in {"incoming_transfer", "card_transfer"}:
        details.update(
            category="foreign_relative_repayment",
            relationship="relative and player in a prior personal loan",
            original_lender="player" if credit else party,
            original_borrower=party if credit else "player",
            principal=value,
        )
        text = f"Relative {party} {'repays player' if credit else 'receives repayment from player'} {value} RUB under prior family loan {record_id}. Original signed loan receipt dated 2026-07-{min(index, 28):02} records {'player lending to that relative' if credit else 'that relative lending to player'} exactly {value} RUB; the payment fully settles this separately documented principal. {'The relative sends repayment from a KG bank; this is return of player-funded prior debt, not a new gift or new borrowing.' if credit else 'This separate outgoing debt does not assert that its recipient supplied any of the new incoming repayments.'}"
        return text, details
    return default, {}


def main():
    target = ROOT / "resources/aml_dataset/aml-v1/pilot/casebook.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in build_casebook()),
        encoding="utf-8",
    )
    path = ROOT / "config/ml/aml-classifier-v1-protocol.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(protocol(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
