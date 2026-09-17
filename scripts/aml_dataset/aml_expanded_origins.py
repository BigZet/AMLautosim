"""Additional finite economic worlds. Draft only; no new independence exemptions.

Uses the existing ledger validator and observation compiler, not its economic roots.
The shared settlement skeleton is deliberately declared and audited by closure.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from scripts.aml_dataset.aml_origins import compile_root as compile_ledger
from scripts.aml_dataset.aml_casebook import protocol
from scripts.aml_dataset.aml_training import (
    validate_sources,
    json_bytes,
    jsonl_bytes,
    source_hashes,
)
from scripts.aml_dataset.aml_provenance import connected_groups, digest

VERSION = "aml-expanded-economic-worlds-draft-v5"
# These are authored causal dossiers, not combinatorial choices.
DOSSIERS = (
    dict(
        name="cash_mobile_repair",
        family="P05",
        purpose="service_payment",
        ownership="Three customers own repaired farm tools; player owns the earned repair receivables.",
        cause="customers_accept_repaired_farm_tools",
        prior="repair_orders_signed",
        obligation="Five parts suppliers delivered parts on credit; a mobile repair subcontractor requires 10000 cash on collection.",
        debit="parts_delivered_on_trade_credit",
        cash="mobile_subcontractor_cash_fee_due",
        crime="diversion_of_customer_escrow",
        history="purchase",
    ),
    dict(
        name="cash_market_stall",
        family="P05",
        purpose="asset_sale",
        ownership="Player owns three identifiable market inventory lots bought from a wholesaler before the round.",
        cause="market_inventory_title_transferred",
        prior="inventory_title_acquired",
        obligation="Five carriers have completed separate delivery jobs; the market operator collects a 10000 cash stall fee.",
        debit="carrier_delivery_accepted",
        cash="cash_market_stall_rent_due",
        crime="misappropriation_of_market_cooperative_receipts",
        history="card_transfer",
    ),
    dict(
        name="foreign_estate_distribution",
        family="P07",
        purpose="asset_sale",
        ownership="Three foreign coheirs purchased the player's inherited interests; probate assigned these interests to player.",
        cause="coheir_buyout_of_inherited_interest",
        prior="probate_interest_assigned",
        obligation="Five local contractors completed restoration of player's retained house; a locksmith is paid 10000 in cash.",
        debit="restoration_milestone_accepted",
        cash="locksmith_cash_collection_due",
        crime="estate_executor_embezzlement",
        history="incoming_transfer",
    ),
    dict(
        name="crypto_self_custody_disposal",
        family="P08",
        purpose="asset_sale",
        ownership="Player acquired three own-wallet token lots with lawful savings; signed wallet control and acquisition receipts bind the lots to player.",
        cause="owned_token_lot_delivered_to_p2p_buyer",
        prior="owned_wallet_lot_acquired",
        obligation="Five equipment vendors delivered personally owned equipment; a collection service requires 10000 cash.",
        debit="equipment_delivered_and_title_assigned",
        cash="cash_equipment_collection_due",
        crime="custodial_token_proceeds_embezzlement",
        history="card_transfer",
    ),
    dict(
        name="dormant_land_compensation",
        family="P09",
        purpose="asset_sale",
        ownership="Player owns three acquired land strips; three private adjacent owners compensate actual title transfer. Account has no transactions throughout the complete observed history window.",
        cause="adjacent_owner_land_strip_buyout",
        prior="land_title_registered",
        obligation="Five surveyors completed separate boundary and valuation work; archival copy collection costs 10000 cash.",
        debit="survey_and_valuation_report_accepted",
        cash="archive_copy_cash_fee_due",
        crime="land_broker_client_escrow_embezzlement",
        history=None,
    ),
    dict(
        name="mixed_household_transition",
        family="P10",
        purpose="service_payment",
        ownership="Lawful payroll pays completed employment; a current household purchase is independent of three transfers for contract work, owned appliance sale and return of a paid training advance.",
        cause="mixed_independent_entitlements_due",
        prior="household_transition_agreements",
        obligation="Five removal vendors completed transport/storage jobs; porter assistance costs 10000 cash and a merchant delivered household goods for 10000. Payroll, household purchase, real work receipt and porter payment stay lawful in the criminal world.",
        debit="removal_or_storage_service_accepted",
        cash="porter_cash_fee_due",
        crime="training_provider_escrow_embezzlement",
        history="purchase",
    ),
)


def author_roots():
    roots = []
    for ordinal, spec in enumerate(DOSSIERS):
        events, obligations, payments = [], [], []
        participants = [dict(id="player", role="account holder")]

        def event(identity, kind, actor, beneficiary, amount, parents=()):
            events.append(
                dict(
                    id=identity,
                    kind=kind,
                    actor=actor,
                    beneficiary=beneficiary,
                    amount=amount,
                    depends_on=list(parents),
                    occurred_at="2026-09-01T09:00:00+03:00",
                )
            )
            return identity

        for i in range(1, 4):
            party = f"funding-{i}"
            participants.append(
                dict(id=party, role=f"Economic source counterparty {i}")
            )
            prior = event(
                f"entitlement-{i}", spec["prior"], "player", party, "80000.00"
            )
            purpose = spec["purpose"]
            kind = spec["cause"]
            if spec["family"] == "P10":
                kind, purpose = [
                    ("contract_work_accepted", "service_payment"),
                    ("owned_appliance_title_transferred", "asset_sale"),
                    ("training_cancelled_and_advance_return_due", "refund"),
                ][i - 1]
            basis = event(f"source-{i}", kind, party, "player", "80000.00", [prior])
            obligations.append(
                dict(
                    id=f"receivable-{i}",
                    debtor=party,
                    creditor="player",
                    principal="80000.00",
                    outstanding="80000.00",
                    origin_event_id=basis,
                    purpose=purpose,
                )
            )
            payments.append(
                dict(
                    id=f"in-{i}",
                    direction="credit",
                    amount="80000.00",
                    obligation_id=f"receivable-{i}",
                    origin_event_id=basis,
                    payer=party,
                    beneficiary="player",
                    purpose=purpose,
                    instalment=1,
                )
            )
        for i in range(1, 7):
            cash = i == 6
            party = "cash-vendor" if cash else f"payee-{i}"
            identity = "cash" if cash else f"out-{i}"
            amount = "10000.00" if cash else "78000.00"
            participants.append(
                dict(
                    id=party,
                    role="Cash collection provider"
                    if cash
                    else f"Creditor for completed obligation {i}",
                )
            )
            basis = event(
                f"liability-{i}",
                spec["cash"] if cash else spec["debit"],
                party,
                "player",
                amount,
            )
            oid = f"payable-{i}"
            obligations.append(
                dict(
                    id=oid,
                    debtor="player",
                    creditor=party,
                    principal=amount,
                    outstanding=amount,
                    origin_event_id=basis,
                    purpose="personal_spending",
                )
            )
            payments.append(
                dict(
                    id=identity,
                    direction="debit",
                    amount=amount,
                    obligation_id=oid,
                    origin_event_id=basis,
                    payer="player",
                    beneficiary=party,
                    purpose="personal_spending",
                    instalment=1,
                )
            )
        if spec["family"] == "P10":
            for identity, party, role, kind, amount, credit, purpose in (
                (
                    "background-salary",
                    "employer",
                    "Employer owing earned payroll",
                    "employment_period_completed",
                    "30000.00",
                    True,
                    "salary",
                ),
                (
                    "background-purchase",
                    "household-merchant",
                    "Merchant delivering household goods",
                    "household_goods_delivered",
                    "10000.00",
                    False,
                    "personal_spending",
                ),
            ):
                participants.append(dict(id=party, role=role))
                payer, beneficiary = (party, "player") if credit else ("player", party)
                basis = event(identity + "-basis", kind, payer, beneficiary, amount)
                oid = identity + "-obligation"
                obligations.append(
                    dict(
                        id=oid,
                        debtor=payer,
                        creditor=beneficiary,
                        principal=amount,
                        outstanding=amount,
                        origin_event_id=basis,
                        purpose=purpose,
                    )
                )
                payments.append(
                    dict(
                        id=identity,
                        direction="credit" if credit else "debit",
                        amount=amount,
                        obligation_id=oid,
                        origin_event_id=basis,
                        payer=payer,
                        beneficiary=beneficiary,
                        purpose=purpose,
                        instalment=1,
                    )
                )
        for obligation in obligations:
            obligation.update(
                due_from="2026-09-13T09:00:00+03:00", due_to="2026-09-14T09:00:00+03:00"
            )
        history = []

        def historical(basis, code, party):
            original = next(e for e in events if e["id"] == basis)
            history.append(
                dict(
                    id="paid-" + basis,
                    operation_code=code,
                    amount=original["amount"],
                    occurred_at=original["occurred_at"],
                    counterparty_id=party,
                    category=None,
                    origin_event_id=basis,
                )
            )

        if spec["family"] == "P08" or spec["name"] == "cash_market_stall":
            party = (
                "acquisition-seller"
                if spec["family"] == "P08"
                else "inventory-wholesaler"
            )
            participants.append(dict(id=party, role="Original owned-lot seller"))
            for i in range(1, 4):
                original = next(e for e in events if e["id"] == f"entitlement-{i}")
                original.update(beneficiary=party)
                historical(original["id"], "card_transfer", party)
        elif spec["family"] == "P10":
            for i, kind in enumerate(
                (
                    "work_contract_signed",
                    "owned_appliance_acquired",
                    "training_advance_paid",
                ),
                1,
            ):
                original = next(e for e in events if e["id"] == f"entitlement-{i}")
                original["kind"] = kind
            historical("entitlement-3", "card_transfer", "funding-3")
        elif spec["family"] == "P07":
            participants.append(
                dict(
                    id="probate-representative",
                    role="Personal representative reimbursed for obtaining certified probate copies",
                )
            )
            basis = event(
                "registry-fee",
                "representative_certified_copy_outlay_reimbursed",
                "player",
                "probate-representative",
                "30000.00",
            )
            historical(basis, "card_transfer", "probate-representative")
        elif spec["history"]:
            participants.append(
                dict(id="prior-provider", role="Merchant selling repair tools")
            )
            basis = event(
                "prior-tools",
                "repair_tools_acquired",
                "player",
                "prior-provider",
                "30000.00",
            )
            historical(basis, "purchase", "prior-provider")
        ledger = dict(
            opening_balance="180000.00",
            opening_origin="Lawful accumulated savings after the listed historical settlements",
            participants=participants,
            events=events,
            obligations=obligations,
            payments=payments,
            historical_payments=history,
            future_obligations=[],
            history_coverage="complete",
        )
        root = dict(
            root_id=spec["name"],
            family_id=spec["family"],
            ordinal=ordinal,
            generator_version=VERSION,
            review_status="authored_unreviewed",
            review=None,
            economic_narrative=deepcopy(spec),
            template_ancestry=[
                "economic-ledger-v1",
                "three-receipts-five-obligations-cash-v1",
            ],
            compatibility=dict(funding=spec["cause"]),
            ledger=ledger,
        )
        root["worlds"] = author_worlds(root, spec)
        roots.append(root)
    return roots


def author_worlds(root, spec):
    ledger = root["ledger"]
    lawful = deepcopy(ledger)
    lawful.update(
        aml_episode_present=False,
        claimed_ledger_sha256=digest(ledger),
        account_control=[],
        record_checks={},
    )
    for p in ledger["payments"]:
        lawful["record_checks"][p["id"]] = dict(
            check_id="issuer-check-" + p["id"],
            payment_id=p["id"],
            availability="available",
            outcome="corroborates",
            checked_at="2026-09-13T09:00:00+03:00",
            **{k: p[k] for k in ("payer", "beneficiary", "amount", "origin_event_id")},
            evidence=dict(
                kind="signed_original_event_and_payment_authority",
                issuer=p["payer"] if p["direction"] == "credit" else p["beneficiary"],
                confirms_obligation_id=p["obligation_id"],
                confirms_amount=p["amount"],
            ),
            finding=f"Issuer original confirms {p['origin_event_id']}, exact amount and authority to settle {p['obligation_id']}; future payment is not asserted completed.",
        )
    lawful["remaining_obligations"] = [
        dict(o, outstanding_after_round="0.00") for o in ledger["obligations"]
    ]
    criminal = deepcopy(lawful)
    criminal.update(aml_episode_present=True, predicate_offence=spec["crime"])
    criminal["participants"].append(
        dict(
            id="collector",
            role="Beneficial controller knowingly collecting diverted proceeds",
        )
    )
    criminal["events"].append(
        dict(
            id="collector-instruction",
            kind="knowing_remittance_instruction",
            actor="collector",
            beneficiary="player",
            amount="400000.00" if spec["family"] == "P05" else "390000.00",
            depends_on=[],
            occurred_at="2026-09-12T08:00:00+03:00",
        )
    )
    for p in criminal["payments"]:
        credit = p["id"] in {"in-2", "in-3"}
        cash_route = spec["family"] == "P05" and p["id"] == "cash"
        debit = p["id"].startswith("out-") or cash_route
        if not (credit or debit):
            continue
        oid = p.pop("obligation_id")
        p.update(settles_obligation=False, cover_obligation_id=oid)
        finding = criminal["record_checks"][p["id"]]
        if credit:
            victim = "owner-" + p["id"]
            criminal["participants"].append(
                dict(
                    id=victim,
                    role="Actual owner of diverted funds distinct from player",
                )
            )
            offence = "offence-" + p["id"]
            custody = "custody-" + p["id"]
            criminal["events"].extend(
                [
                    dict(
                        id=offence,
                        kind=spec["crime"],
                        actor=p["payer"],
                        beneficiary="collector",
                        source_owner=victim,
                        amount=p["amount"],
                        depends_on=[],
                        occurred_at="2026-09-12T09:00:00+03:00",
                    ),
                    dict(
                        id=custody,
                        kind="diverted_proceeds_held_by_sender",
                        actor=victim,
                        beneficiary=p["payer"],
                        amount=p["amount"],
                        depends_on=[offence],
                        occurred_at="2026-09-12T10:00:00+03:00",
                    ),
                ]
            )
            p.update(
                criminal_proceeds=True,
                source_owner=victim,
                source_account_controller=p["payer"],
                origin_event_id=custody,
            )
            finding.update(
                outcome="refutes",
                evidence=dict(
                    kind="signed_issuer_denial_of_claimed_allocation",
                    issuer=p["payer"],
                    denied_obligation_id=oid,
                    denied_payment_id=p["id"],
                    authorised_allocation_amount="0.00",
                ),
                finding="Issuer expressly rejects applying this receipt to the claimed entitlement; it is a third-party remittance.",
            )
            account, controller = p["payer"], p["payer"]
        else:
            account, controller = p["beneficiary"], "collector"
            p.update(
                observed_account_party=account,
                beneficiary=controller,
                origin_event_id="collector-instruction",
            )
            finding.update(
                outcome="refutes",
                evidence=dict(
                    kind="creditor_rejection_and_beneficiary_register",
                    issuer=account,
                    denied_payment_id=p["id"],
                    denied_obligation_id=oid,
                    authorised_settlement=False,
                    account_controller=controller,
                ),
                finding="Creditor rejects proposed account as authorised settlement; control register confirms collector control.",
            )
            if cash_route:
                p.pop("observed_account_party")
                p["cash_custodian"] = "player"
                p["cash_handover_recipient"] = "collector"
                finding.update(
                    evidence=dict(
                        kind="signed_issuer_denial_of_claimed_allocation",
                        issuer="cash-vendor",
                        denied_payment_id="cash",
                        denied_obligation_id=oid,
                        authorised_allocation_amount="0.00",
                    ),
                    finding="Cash vendor expressly denies authorising this withdrawal as payment for its obligation. A separately authored instruction requires the player to hand withdrawn notes to the collector; no bank-account control of a cash vendor is asserted.",
                )
                criminal.setdefault("cash_handover_instructions", []).append(
                    dict(
                        payment_id="cash",
                        custodian="player",
                        recipient="collector",
                        amount=p["amount"],
                        after_event="cash_withdrawal_completed",
                        origin_event_id="collector-instruction",
                    )
                )
                # Cash custody is not a fictitious bank-account-control record.
                continue
        criminal["account_control"].append(
            dict(
                account_party=account,
                controller=controller,
                payment_ids=[p["id"]],
                origin_event_id=p["origin_event_id"],
            )
        )
    paid = defaultdict(Decimal)
    for p in criminal["payments"]:
        if p.get("settles_obligation", True):
            paid[p["obligation_id"]] += Decimal(p["amount"])
    criminal["remaining_obligations"] = [
        dict(
            o,
            outstanding_after_round=f"{Decimal(o['outstanding']) - paid[o['id']]:.2f}",
        )
        for o in ledger["obligations"]
    ]
    unresolved = deepcopy(lawful)
    unresolved["aml_episode_present"] = None
    for p in unresolved["payments"]:
        if (
            p["id"] in {"in-2", "in-3"}
            or p["id"].startswith("out-")
            or (spec["family"] == "P05" and p["id"] == "cash")
        ):
            p["origin_established"] = False
    for f in unresolved["record_checks"].values():
        f.update(
            availability="unavailable",
            outcome="unknown",
            evidence={},
            finding="Original evidence unavailable; outcome unestablished.",
        )
    return dict(lawful=lawful, criminal=criminal, unresolved=unresolved)


def compile_root(root):
    rows = compile_ledger(root)
    for row in rows:
        behavior = row["public_snapshot"]["config"]["behavior"]
        if root["root_id"] == "cash_mobile_repair":
            next(
                p for p in behavior["counterparties"] if p["id"] == "prior-provider"
            ).update(
                kind="merchant", category="household", personal_relationship="unknown"
            )
        for step in row["public_snapshot"]["steps"]:
            if step["card"]["code"] == "incoming_transfer":
                if root["family_id"] == "P08":
                    step["action_details"] = dict(incoming_kind="crypto_p2p")
                elif root["family_id"] == "P07":
                    step["action_details"]["bank_country"] = "KG"
        if root["family_id"] == "P05" and row["aml_label"] == 1:
            _bind_cash_episode(row, root)
        if root["family_id"] == "P10":
            _project_background(row, root)
        row["author_id"] = "expanded-economic-world-author-v5"
    return rows


def _bind_cash_episode(row, root):
    """Reserve actual proceeds for the cash handover in every causal schedule."""
    available, reserve, allocations = Decimal(0), Decimal("10000"), []
    for record in row["economic_records"]:
        identity = record["id"]
        if identity in {"in-2", "in-3"}:
            available += Decimal(record["amount"])
        if identity.startswith("out-") or identity == "cash":
            amount = (
                reserve
                if identity == "cash"
                else min(
                    Decimal(record["amount"]), max(Decimal(0), available - reserve)
                )
            )
            if amount > available:
                raise ValueError("cash routing precedes receipt of its proceeds")
            available -= amount
            if identity == "cash":
                reserve = Decimal(0)
            allocations.append(dict(payment=identity, criminal_amount=f"{amount:.2f}"))
    if available != 0 or reserve != 0:
        raise ValueError("cash episode leaves proceeds unallocated")
    episode = row["author_truth"]["criminal_episode"]
    episode.update(
        routing_allocations=allocations,
        lawful_funds_contributed_to_collectors="240000.00",
        collector_controlled_payments=[f"out-{i}" for i in range(1, 6)] + ["cash"],
        cover_obligations_not_settled=[f"out-{i}" for i in range(1, 6)] + ["cash"],
        continuing_lawful_payments=[],
        actual_obligation_override="Card destinations and withdrawn notes are remitted to collectors; none settles the claimed vendor liabilities. The original cash-vendor liability remains outstanding.",
    )
    episode["cover_debit_events"].append(
        next(r["origin_event_id"] for r in row["economic_records"] if r["id"] == "cash")
    )
    row["author_truth"]["cash_handover_instructions"] = deepcopy(
        root["worlds"]["criminal"]["cash_handover_instructions"]
    )


def _project_background(row, root):
    """Project two existing ledger payments, never append unbound cosmetic steps."""
    public = row["public_snapshot"]
    config, steps = public["config"], public["steps"]
    behavior = config["behavior"]
    next(
        p for p in behavior["counterparties"] if p["id"] == "household-merchant"
    ).update(kind="merchant", personal_relationship="unknown", category="household")
    world = root["worlds"][
        {0: "lawful", 1: "criminal", None: "unresolved"}[row["aml_label"]]
    ]
    context = behavior["aml_context"]
    for identity, code in (
        ("background-salary", "salary"),
        ("background-purchase", "purchase"),
    ):
        payment = next(p for p in root["ledger"]["payments"] if p["id"] == identity)
        actual = next(p for p in world["payments"] if p["id"] == identity)
        finding = world["record_checks"][identity]
        credit = payment["direction"] == "credit"
        recipe = row["variant_recipe"]
        masked = (
            finding["availability"] == "unavailable"
            or "unavailable" in recipe
            or ("sources_only" in recipe and not credit)
            or ("obligations_only" in recipe and credit)
        )
        status = (
            "unknown"
            if finding["outcome"] == "unknown"
            else "unverified"
            if masked
            else "verified"
        )
        claim = "claim-" + identity
        context["facts"].append(
            dict(
                id=claim,
                fact_type="source_of_funds" if credit else "payment_purpose",
                verification_status=status,
                provenance="customer_statement" if masked else "independent_record",
                available_at=finding["checked_at"],
                valid_from=behavior["timeline"]["starts_at"],
                valid_to=context["as_of"],
                counterparty_ids=[
                    payment["payer"] if credit else payment["beneficiary"]
                ],
                operation_codes=[code],
                purpose_code=payment["purpose"],
                max_credit_amount=payment["amount"] if credit else "0.00",
                max_debit_amount="0.00" if credit else payment["amount"],
            )
        )
        card = next(c for c in config["card_snapshots"] if c["code"] == code)
        step = dict(
            step_id=str(uuid5(NAMESPACE_URL, identity)),
            card={k: card[k] for k in ("id", "code", "version")},
            amount=payment["amount"],
            context={},
            action_details=dict(income_basis="payroll_registry") if credit else {},
            interval_minutes=1,
            purpose_code=payment["purpose"],
            claim_id=claim,
        )
        step["sender_id" if credit else "recipient_id"] = (
            payment["payer"] if credit else payment["beneficiary"]
        )
        steps.append(step)
        row["economic_records"].append(
            dict(
                record_id=claim,
                step_number=len(steps),
                operation=code,
                **deepcopy(payment),
                observed_record_status=status,
                observed_record_reason="Original unavailable; missing evidence does not set the outcome."
                if masked
                else finding["finding"],
                record_check=deepcopy(finding),
                actual_payment=deepcopy(actual),
            )
        )
    context["expected_activity"].update(
        expected_credit_min="270000.00",
        expected_credit_max="270000.00",
        expected_debit_min="410000.00",
        expected_debit_max="410000.00",
    )
    if row["aml_label"] == 1:
        row["author_truth"]["criminal_episode"]["continuing_lawful_payments"].extend(
            ["background-salary", "background-purchase"]
        )


def build_origins(output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    roots = author_roots()
    rows = [row for root in roots for row in compile_root(root)]
    features = validate_sources(rows, protocol())
    graph = connected_groups(rows, features)
    confirmed = [r for r in rows if r["aml_label"] is not None]
    clusters = defaultdict(list)
    for row in confirmed:
        clusters[digest(features[row["scenario_id"]])].append(row)
    collisions = [
        dict(feature_sha256=k, scenario_ids=[r["scenario_id"] for r in group])
        for k, group in clusters.items()
        if len({r["aml_label"] for r in group}) > 1
    ]
    report = dict(
        version=VERSION,
        release_ready=False,
        review_status="authored_unreviewed",
        reviewed_rows=0,
        authored_roots=len(roots),
        confirmed_candidate_rows=len(confirmed),
        unresolved_rows=len(rows) - len(confirmed),
        class_counts=dict(Counter(str(r["aml_label"]) for r in confirmed)),
        post_closure_components=len(graph["groups"]),
        component_sizes=dict(
            Counter(graph["scenario_groups"][r["scenario_id"]] for r in confirmed)
        ),
        contradictory_feature_clusters=len(collisions),
        minimum_components_required=1200,
        minimum_confirmed_rows_required=30000,
        source_hashes={
            **source_hashes(),
            **{
                "scripts/aml_dataset/" + name: sha256(
                    Path(__file__).with_name(name).read_bytes()
                ).hexdigest()
                for name in ("aml_expanded_origins.py", "aml_origins.py")
            },
        },
        limitations=[
            "Draft only; independent review pending.",
            "Shared settlement grammar can merge genuinely different authored causes.",
            "P05 currently contains one 10000 cash withdrawal, not cash-dominant settlement.",
            "No release splits or held-out challenges claimed.",
        ],
    )
    output.mkdir(parents=True)
    for name, content in {
        "roots.jsonl": jsonl_bytes(roots),
        "casebook.jsonl": jsonl_bytes(rows),
        "provenance.json": json_bytes(graph),
        "collisions.json": json_bytes(collisions),
        "feasibility.json": json_bytes(report),
    }.items():
        (output / name).write_bytes(content)
    return report
