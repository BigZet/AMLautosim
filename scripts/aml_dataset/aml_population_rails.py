"""Authored settlement routes for existing economic obligations.

Routes retain their parent history and never manufacture independent groups.
Cryptocurrency proceeds require an asset sale plus an explicit ownership,
conversion and settlement ledger. Values are fictional contractual RUB values,
not market-price observations. No route is a label or a public verification flag.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta

from scripts.aml_dataset import aml_population_author as population
from scripts.aml_dataset import aml_world_graph as graph
from scripts.aml_dataset.aml_provenance import digest


RAILS = {"payment_service", "crypto_p2p", "exchange_withdrawal"}


def compile_inactive_history(world):
    """A genuine empty recent statement; older causal payments remain in truth.

    Date-shifted siblings retain original ancestry, so this is a holdout variant,
    never a new independent root. Its entire component must be reserved.
    """
    population.validate_role_world(world)
    shifted = deepcopy(world)
    shift = timedelta(days=120)
    shifted.events = [
        replace(e, at=(datetime.fromisoformat(e.at) - shift).isoformat())
        for e in shifted.events
    ]
    for payment in shifted.history:
        payment["occurred_at"] = (
            datetime.fromisoformat(payment["occurred_at"]) - shift
        ).isoformat()
    shifted.evidence_worlds = graph.author_evidence_worlds(shifted)
    shifted = population.author_role_world(shifted, world.profile["id"])
    rows = []
    for row in graph.compile_root(shifted):
        if row["aml_label"] is None:
            continue
        behavior = row["public_snapshot"]["config"]["behavior"]
        context = behavior["aml_context"]
        start = datetime.fromisoformat(context["history_start"])
        end = datetime.fromisoformat(context["history_end"])
        full = deepcopy(behavior["history"]["operations"])
        recent = [
            h for h in full if start <= datetime.fromisoformat(h["occurred_at"]) < end
        ]
        if recent:
            raise ValueError(
                "Inactivity construction contains recent account operations"
            )
        behavior["history"]["operations"] = recent
        row["author_truth"]["complete_pre_round_account_history"] = full
        row["author_truth"]["statement_window"] = dict(
            start=context["history_start"],
            end=context["history_end"],
            operations=recent,
        )
        row["scenario_id"] = (
            f"{world.id}-inactive-{row['variant_recipe']}-{row['aml_label']}"
        )
        row["family_id"] = "P09"
        row["provenance"]["parent_ids"] = [
            world.id + "-opaque-0",
            world.id + "-opaque-1",
        ]
        row["activity_dossier"] = deepcopy(shifted.activity)
        rows.append(row)
    return rows


def author_route(world, rail):
    population.validate_role_world(world)
    if rail not in RAILS:
        raise ValueError("Unsupported settlement rail")
    if rail != "payment_service" and world.source != "asset":
        raise ValueError("Digital settlement requires an actual owned asset sale")
    obligations = {o.id: o for o in world.obligations}
    worlds = {}
    for name, truth in world.evidence_worlds.items():
        routes = []
        for index, payment in enumerate(world.payments):
            if payment.operation != "incoming_transfer":
                continue
            actual = truth["actual_payments"][payment.id]
            obligation = obligations[payment.obligation]
            source = actual.get("origin_event", obligation.basis)
            owner = actual.get("source_owner", payment.payer)
            custodian = actual.get("source_custodian", payment.payer)
            prefix = f"{payment.id}-{rail}"
            # These are actual authored settlement instructions. Their existence
            # does not make an illicit payer's allocation lawful.
            events = [
                dict(
                    id=prefix + "-instruction",
                    kind="payment_service_settlement_instruction"
                    if rail == "payment_service"
                    else "asset_sale_digital_settlement_agreement",
                    parents=[source],
                    obligation=obligation.id,
                    amount=graph.money(payment.amount),
                    currency="RUB",
                    funding_owner=owner,
                    funding_custodian=custodian,
                    instructing_party=payment.payer,
                    destination_owner="player",
                    at=(
                        datetime.fromisoformat(graph.START) - timedelta(minutes=3)
                    ).isoformat(),
                )
            ]
            if rail == "payment_service":
                # P07 is genuinely cross-border; the public service rail alone
                # does not establish a country or an AML outcome.
                events[0].update(
                    originating_account_jurisdiction="KG",
                    destination_account_jurisdiction="RU",
                    operator="contracted-cross-border-payment-service",
                    settlement_currency="RUB",
                    foreign_exchange_required=False,
                )
            if rail != "payment_service":
                events.append(
                    dict(
                        id=prefix + "-conversion",
                        kind="digital_units_acquired_and_delivered",
                        parents=[events[-1]["id"]],
                        asset="fictional-settlement-token",
                        units=graph.money(payment.amount // 1000),
                        contractual_rub_per_unit="1000.00",
                        rub_value=graph.money(payment.amount),
                        funding_owner=owner,
                        funding_custodian=custodian,
                        receiving_wallet_owner="player",
                        at=(
                            datetime.fromisoformat(graph.START) - timedelta(minutes=2)
                        ).isoformat(),
                    )
                )
            processor = (
                "exchange"
                if rail == "exchange_withdrawal"
                else "digital-buyer-" + payment.id
                if rail == "crypto_p2p"
                else payment.payer
            )
            events.append(
                dict(
                    id=prefix + "-settled",
                    kind="exchange_sale_and_ruble_withdrawal"
                    if rail == "exchange_withdrawal"
                    else "peer_purchase_of_digital_units"
                    if rail == "crypto_p2p"
                    else "payment_service_credit",
                    parents=[events[-1]["id"]],
                    account_owner="player",
                    observed_sender=processor,
                    funding_party=payment.payer,
                    amount=graph.money(payment.amount),
                    fee="0.00",
                    fee_basis="contractually fee-free settlement",
                    settles_obligation=actual["settles_obligation"],
                    at=(
                        datetime.fromisoformat(graph.START) + timedelta(minutes=index)
                    ).isoformat(),
                )
            )
            routes.append(
                dict(
                    payment_id=payment.id,
                    obligation_id=obligation.id,
                    rail=rail,
                    events=events,
                    original_actual_payment=deepcopy(actual),
                    observed_sender=processor,
                    settlement_authority=deepcopy(
                        truth["documents"][payment.id]["actual_purpose"]
                    ),
                )
            )
        worlds[name] = routes
    return dict(
        version="economic-settlement-rail-v1",
        rail=rail,
        base_world=asdict(world),
        worlds=worlds,
    )


def compile_route(dossier, *, modes=("records", "opaque", "obligations")):
    world = population.world_from_dict(dossier["base_world"])
    if digest(dossier) != digest(author_route(world, dossier["rail"])):
        raise ValueError("Settlement authority, custody or conversion ledger mismatch")
    if not modes or not set(modes) <= {"records", "opaque", "obligations"}:
        raise ValueError("Unsupported settlement evidence availability")
    output = []
    for row in graph.compile_root(world):
        if row["aml_label"] is None or row["variant_recipe"] not in modes:
            continue
        name = "criminal" if row["aml_label"] else "lawful"
        routes = {r["payment_id"]: r for r in dossier["worlds"][name]}
        public = row["public_snapshot"]
        behavior = public["config"]["behavior"]
        if dossier["rail"] == "crypto_p2p":
            behavior["counterparties"].extend(
                dict(
                    id=route["observed_sender"],
                    name="Buyer of delivered digital units",
                    kind="person",
                    category=None,
                    information_status="sufficient",
                    personal_relationship="unknown",
                )
                for route in routes.values()
            )
        facts = {f["id"]: f for f in behavior["aml_context"]["facts"]}
        for record, step in zip(row["economic_records"], public["steps"], strict=True):
            route = routes.get(record["id"])
            if route is None:
                continue
            step["action_details"] = {"incoming_kind": dossier["rail"]}
            step["sender_id"] = route["observed_sender"]
            facts[step["claim_id"]]["counterparty_ids"] = [route["observed_sender"]]
            record["settlement_route"] = deepcopy(route)
            settled = deepcopy(record["actual_payment"])
            settled.update(
                payer=route["observed_sender"],
                original_funding_party=route["original_actual_payment"]["payer"],
                settlement_event=route["events"][-1]["id"],
            )
            record["actual_payment"] = settled
            for index, actual in enumerate(row["author_truth"]["actual_payments"]):
                if actual["id"] == record["id"]:
                    row["author_truth"]["actual_payments"][index] = deepcopy(settled)
        row["author_truth"]["settlement_routes"] = deepcopy(list(routes.values()))
        row["author_truth"]["actual_world_sha256"] = digest(
            dict(
                base=row["author_truth"]["actual_world_sha256"],
                routes=list(routes.values()),
            )
        )
        mode = row["variant_recipe"]
        row["scenario_id"] = (
            f"{world.id}-rail-{dossier['rail']}-{mode}-{row['aml_label']}"
        )
        row["family_id"] = "P07" if dossier["rail"] == "payment_service" else "P08"
        row["variant_recipe"] = f"rail-{dossier['rail']}-{mode}"
        row["provenance"]["parent_ids"] = [
            world.id + "-opaque-0",
            world.id + "-opaque-1",
        ]
        row["provenance"]["counterfactual_pair_id"] = (
            f"{world.id}-rail-{dossier['rail']}-{mode}"
        )
        row["settlement_dossier_sha256"] = digest(dossier)
        row["activity_dossier"] = deepcopy(world.activity)
        output.append(row)
    return output
