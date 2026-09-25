"""Economic provider-topology population author; never release or review approval.

Six actual delivered service contracts have independently paid deposits. A
canonical provider partition changes which real creditor fulfilled each contract.
All closure and financial gates are the existing authoritative implementations.
"""

from dataclasses import asdict, dataclass, field
from collections import Counter, defaultdict, deque
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import json

from scripts.aml_dataset import aml_world_graph as graph
from scripts.aml_dataset.aml_casebook import protocol
from scripts.aml_dataset.aml_provenance import connected_groups, digest
from scripts.aml_dataset.aml_training import (
    validate_sources,
    source_hashes,
    json_bytes,
    jsonl_bytes,
    coverage_report,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = (
    ("inspection", 60000, 10000),
    ("preparation", 70000, 15000),
    ("assembly", 85000, 20000),
    ("transport", 80000, 10000),
    ("installation", 100000, 20000),
    ("commissioning", 105000, 25000),
)
SOURCE_PARTITIONS = ((3,), (2, 1), (1, 1, 1))
SOURCES = ("service", "asset", "refund", "debt", "cost")
SCHEDULES = ((0, 1, 2, 3, 4, 5), (1, 0, 2, 3, 4, 5), (2, 0, 1, 3, 4, 5))
# Twelve matched recipes plus one preregistered alternating extra =25 per unit.
RECIPES = (
    (0, "records"),
    (0, "opaque"),
    (0, "sources"),
    (0, "wrong_cover"),
    (1, "records"),
    (1, "opaque"),
    (1, "obligations"),
    (1, "wrong_cover"),
    (2, "records"),
    (2, "wrong_cover"),
    (2, "sources"),
    (2, "obligations"),
)

ROLE_SOURCES = {
    "project_coordinator": ("cost", "service", "refund", "debt"),
    "artisan_owner": ("service", "asset", "refund"),
    "collection_owner": ("asset",),
    "event_organizer": ("refund", "service", "cost"),
    "equipment_pool_organizer": ("debt", "asset"),
}
ROLE_ACTIVITIES = {
    "project_coordinator": (
        "contracted fit-out project",
        "coordinator responsible for project contracts and their settlement",
    ),
    "artisan_owner": (
        "commissioned restoration workshop",
        "owner performing restoration commissions and administering workshop property",
    ),
    "collection_owner": (
        "privately owned display collection",
        "owner administering the collection, its display installation and disposal of identified lots",
    ),
    "event_organizer": (
        "booked practical training programme",
        "organizer responsible for participant commissions, supplier bookings and cancellations",
    ),
    "equipment_pool_organizer": (
        "owned shared equipment facility",
        "administrator of owned equipment and financing of its acquisition and use",
    ),
}


@dataclass
class ActivityWorld(graph.World):
    activity: dict = field(default_factory=dict)


def activity_dossier(w, role):
    if role not in ROLE_SOURCES or w.source not in ROLE_SOURCES[role]:
        raise ValueError("incompatible economic activity and source construction")
    subject, responsibility = ROLE_ACTIVITIES[role]
    events = {e.id: e for e in w.events}
    source_contracts = []
    for o in w.obligations:
        if o.creditor != "player":
            continue
        basis = events[o.basis]
        scope = {
            "service": "accepted commissioned work performed for this activity",
            "asset": "disposal of identified property owned within this activity",
            "refund": "return of the cancelled portion of this activity's paid supplier booking",
            "debt": "remaining principal of financing actually advanced for this activity's equipment",
            "cost": "reimbursement of costs paid under this activity's disclosed principal mandate",
        }[w.source]
        source_contracts.append(
            dict(
                obligation=o.id,
                basis=basis.id,
                debtor=o.debtor,
                creditor=o.creditor,
                principal=o.principal,
                original_events=list(basis.parents),
                activity_scope=scope,
                contracting_parties=[o.debtor, o.creditor],
            )
        )
    deliveries = []
    for o in w.obligations:
        if o.debtor != "player":
            continue
        balance = events[o.basis]
        delivery, deposit = [events[x] for x in balance.parents]
        original = events[deposit.parents[0]]
        if deposit.kind == "service_cash_deposit_paid":
            original = events[events[original.parents[0]].parents[0]]
        deliveries.append(
            dict(
                obligation=o.id,
                basis=balance.id,
                contract=original.id,
                delivery=delivery.id,
                deposit=deposit.id,
                contractor=o.creditor,
                customer="player",
                gross=original.amount,
                paid_deposit=deposit.amount,
                remaining=o.principal,
                activity_scope=f"{o.id.removeprefix('contract-')} of the {subject}",
            )
        )
    activity_events, activity_parties, activity_rights = activity_background(
        w, role, source_contracts, deliveries
    )
    return dict(
        version="authored-activity-contract-scope-v2",
        activity_id=w.id + "-activity",
        category=role,
        subject=subject,
        responsible_person="player",
        responsibility=responsibility,
        source_contracts=source_contracts,
        delivery_contracts=deliveries,
        activity_events=activity_events,
        activity_parties=activity_parties,
        activity_rights=activity_rights,
        asset_membership=[
            dict(
                asset=r["asset"],
                owner=r["owner"],
                title_event=r["basis"],
                disposed_to=r["disposed_to"],
                activity=w.id + "-activity",
            )
            for r in w.rights
            if "asset" in r
        ],
    )


def activity_background(w, role, sources, deliveries):
    """Actual non-account background: never inserts fictitious player history."""
    activity = w.id + "-activity"
    records, parties, rights = [], [], []
    scope = [s["basis"] for s in sources] + [d["contract"] for d in deliveries]
    foundation = min(datetime.fromisoformat(e.at) for e in w.events) - timedelta(days=1)
    establishment = dict(
        id=activity + "-establishment",
        kind="identified_activity_established",
        at=foundation.isoformat(),
        parents=[],
        responsible_person="player",
        subject=ROLE_ACTIVITIES[role][0],
    )
    records.append(establishment)
    if role in {"project_coordinator", "event_organizer"}:
        principal = activity + "-commissioner"
        parties.append(
            dict(
                id=principal,
                role="project commissioner"
                if role == "project_coordinator"
                else "programme commissioning sponsor",
            )
        )
        records.append(
            dict(
                id=activity + "-mandate",
                kind="coordination_mandate"
                if role == "project_coordinator"
                else "programme_organisation_agreement",
                at=(foundation + timedelta(hours=1)).isoformat(),
                parents=[establishment["id"]],
                principal=principal,
                appointed_person="player",
                signatories=[principal, "player"],
                scoped_source_bases=[s["basis"] for s in sources],
                scoped_delivery_contracts=[d["contract"] for d in deliveries],
                obligations="coordinate the specified activity, procure its six services and administer its source agreements",
            )
        )
    elif role == "artisan_owner":
        customer = activity + "-restoration-customer"
        parties.append(
            dict(
                id=customer,
                role="owner commissioning restoration of a mechanical display instrument",
            )
        )
        engagement = activity + "-restoration-engagement"
        item = activity + "-customer-instrument"
        records.extend(
            [
                dict(
                    id=engagement,
                    kind="restoration_commission",
                    at=(foundation + timedelta(hours=1)).isoformat(),
                    parents=[establishment["id"]],
                    customer=customer,
                    performer="player",
                    item=item,
                    signatories=[customer, "player"],
                    completion_due="2026-09-30T09:00:00+03:00",
                    agreed_fee=60000,
                    advance_due=0,
                    earned_fee=0,
                    fee_due_only_after_final_acceptance=True,
                    workshop_contracts=[d["contract"] for d in deliveries],
                ),
                dict(
                    id=activity + "-restoration-start",
                    kind="restoration_work_started",
                    at=(foundation + timedelta(hours=2)).isoformat(),
                    parents=[engagement],
                    performer="player",
                    customer=customer,
                    item=item,
                    work="instrument inspected and dismantled; restoration remains incomplete",
                    signatories=[customer, "player"],
                    fee_earned=0,
                    payment_received=0,
                ),
            ]
        )
        rights.append(
            dict(
                item=item,
                owner=customer,
                custodian="player",
                right="custody for commissioned restoration",
                basis=engagement,
            )
        )
    if role == "equipment_pool_organizer" and w.source == "debt":
        for original in (e for e in w.events if e.kind == "loan_disbursement"):
            borrower = original.beneficiary
            vendor = activity + "-vendor-" + borrower
            item = activity + "-equipment-" + borrower
            purchase = activity + "-purchase-" + borrower
            title = activity + "-title-" + borrower
            grant = activity + "-pool-grant-" + borrower
            parties.append(
                dict(id=vendor, role="vendor delivering the financed shared equipment")
            )
            at = datetime.fromisoformat(original.at)
            records.extend(
                [
                    dict(
                        id=purchase,
                        kind="equipment_purchase_paid",
                        at=(at + timedelta(minutes=10)).isoformat(),
                        parents=[original.id, establishment["id"]],
                        payer=borrower,
                        recipient=vendor,
                        amount=original.amount,
                        source_loan=original.id,
                        item=item,
                        actual_owner_of_funds=borrower,
                        actual_receiver=vendor,
                        signatories=[borrower, vendor],
                    ),
                    dict(
                        id=title,
                        kind="equipment_delivered_and_title_transferred",
                        at=(at + timedelta(minutes=20)).isoformat(),
                        parents=[purchase],
                        seller=vendor,
                        owner=borrower,
                        item=item,
                        value=original.amount,
                        signatories=[vendor, borrower],
                    ),
                    dict(
                        id=grant,
                        kind="shared_pool_use_and_administration_granted",
                        at=(at + timedelta(minutes=30)).isoformat(),
                        parents=[title, establishment["id"]],
                        owner=borrower,
                        administrator="player",
                        item=item,
                        activity=activity,
                        signatories=[borrower, "player"],
                        installation_contracts=[d["contract"] for d in deliveries],
                    ),
                ]
            )
            rights.append(
                dict(
                    item=item,
                    owner=borrower,
                    administrator="player",
                    right="shared equipment use and pool administration",
                    title=title,
                    basis=grant,
                    financing=original.id,
                )
            )
    elif role == "equipment_pool_organizer":
        for right in w.rights:
            if "asset" in right:
                records.append(
                    dict(
                        id=activity + "-pool-" + right["asset"],
                        kind="owned_equipment_allocated_to_pool",
                        at=(
                            datetime.fromisoformat(
                                next(e.at for e in w.events if e.id == right["basis"])
                            )
                            + timedelta(minutes=1)
                        ).isoformat(),
                        parents=[right["basis"], establishment["id"]],
                        item=right["asset"],
                        owner="player",
                        administrator="player",
                        activity=activity,
                        scope=scope,
                    )
                )
    return records, parties, rights


def author_role_world(base, role):
    # New substantive scope records bind the original contracts; retained raw
    # ancestry prevents a role completion from becoming an independent origin.
    fields = {k: deepcopy(getattr(base, k)) for k in graph.World.__dataclass_fields__}
    w = ActivityWorld(**fields)
    w.activity = activity_dossier(w, role)
    subject, responsibility = ROLE_ACTIVITIES[role]
    w.profile = dict(
        id=role,
        title=subject.capitalize(),
        description=f"The account holder is the {responsibility}. Original source agreements, property rights, separately completed installation contracts and actual deposits belong to the identified {subject}.",
    )
    validate_role_world(w)
    return w


def validate_role_world(w):
    graph.validate_world(w)
    role = w.profile["id"]
    if not isinstance(w, ActivityWorld) or w.activity != activity_dossier(w, role):
        raise ValueError(
            "activity scope does not bind actual contracts, responsibility and rights"
        )
    known = {e.id: datetime.fromisoformat(e.at) for e in w.events}
    cutoff = datetime.fromisoformat(graph.START)
    for record in w.activity["activity_events"]:
        at = datetime.fromisoformat(record["at"])
        if (
            at.utcoffset() is None
            or at >= cutoff
            or record["id"] in known
            or len(record["parents"]) != len(set(record["parents"]))
            or any(
                parent not in known or known[parent] >= at
                for parent in record["parents"]
            )
        ):
            raise ValueError(
                "activity event has unknown, noncausal or naive-time ancestry"
            )
        known[record["id"]] = at


def assign_roles(candidates, quotas):
    """Deterministic bipartite flow; no class, observation or model input."""
    if any(type(n) is not int or n < 0 for n in quotas.values()):
        raise ValueError("invalid role quota")
    edges = defaultdict(dict)

    def edge(a, b, n):
        edges[a][b] = n
        edges[b][a] = 0

    for gid in sorted(candidates):
        edge("start", "g:" + gid, 1)
        for role in sorted(candidates[gid]):
            if role in quotas:
                edge("g:" + gid, "r:" + role, 1)
    for role, n in sorted(quotas.items()):
        edge("r:" + role, "end", n)
    flow = 0
    while flow < sum(quotas.values()):
        parents = {"start": None}
        queue = deque(["start"])
        while queue and "end" not in parents:
            node = queue.popleft()
            for neighbor in sorted(edges[node]):
                if edges[node][neighbor] > 0 and neighbor not in parents:
                    parents[neighbor] = node
                    queue.append(neighbor)
        if "end" not in parents:
            raise ValueError(
                f"role quota capacity shortfall: {flow}/{sum(quotas.values())}"
            )
        node = "end"
        while parents[node] is not None:
            previous = parents[node]
            edges[previous][node] -= 1
            edges[node][previous] += 1
            node = previous
        flow += 1
    return {
        gid: role
        for gid in sorted(candidates)
        for role in sorted(quotas)
        if edges["r:" + role].get("g:" + gid, 0) == 1
    }


def world_from_dict(value):
    value = deepcopy(value)
    for key, cls in (
        ("participants", graph.Party),
        ("events", graph.Event),
        ("obligations", graph.Obligation),
        ("payments", graph.Payment),
        ("observations", graph.Observation),
    ):
        if key == "events":
            for item in value[key]:
                item["parents"] = tuple(item["parents"])
        value[key] = [cls(**item) for item in value[key]]
    return (ActivityWorld if "activity" in value else graph.World)(**value)


def prepare_selection(probe, external, output, quotas=None):
    """Persist every role candidate before deterministic component quota assignment."""
    quotas = quotas or {role: 240 for role in ROLE_SOURCES}
    output, probe, external = Path(output), Path(probe), Path(external)
    if output.exists():
        raise FileExistsError(output)
    snapshots = {
        str(path): path.read_bytes()
        for path in (
            probe / "roots.jsonl",
            probe / "audit.json",
            external / "provenance.json",
            external / "audit.json",
        )
    }
    root_raw = snapshots[str(probe / "roots.jsonl")]
    probe_audit = json.loads(snapshots[str(probe / "audit.json")])
    if sha256(root_raw).hexdigest() != probe_audit["artifact_hashes"]["roots.jsonl"]:
        raise ValueError("raw root digest mismatch")
    external_audit = json.loads(snapshots[str(external / "audit.json")])
    if external_audit["demo_crossing_components"]:
        raise ValueError("demo-connected raw origins cannot enter selection")
    closure = json.loads(snapshots[str(external / "provenance.json")])
    worlds = {
        v["id"]: world_from_dict(v) for v in map(json.loads, root_raw.splitlines())
    }
    options = defaultdict(lambda: defaultdict(list))
    candidates = []
    excluded = {}
    for root, w in sorted(worlds.items()):
        gid = closure["scenario_groups"][root + "-opaque-0"]
        if gid in external_audit["crossing_components"]:
            excluded[root] = "existing-development connection"
            continue
        for role, sources in ROLE_SOURCES.items():
            if w.source not in sources:
                continue
            authored = author_role_world(w, role)
            options[gid][role].append(root)
            candidates.append(
                dict(
                    root_id=root,
                    raw_component=gid,
                    category=role,
                    raw_world_sha256=digest(asdict(w)),
                    activity=authored.activity,
                )
            )
    assignment = assign_roles(
        {gid: set(roles) for gid, roles in options.items()}, quotas
    )
    selections = []
    selected_worlds = []
    for index, (gid, role) in enumerate(sorted(assignment.items())):
        root = min(
            options[gid][role],
            key=lambda rid: (ROLE_SOURCES[role].index(worlds[rid].source), rid),
        )
        w = author_role_world(worlds[root], role)
        selections.append(
            dict(
                raw_component=gid,
                root_id=root,
                profile=role,
                extra_label=index % 2,
                parent_ids=closure["groups"][gid],
                activity_sha256=digest(w.activity),
            )
        )
        selected_worlds.append(asdict(w))
    chosen = {s["root_id"] for s in selections}
    for root in worlds:
        if root in chosen or root in excluded:
            continue
        gid = closure["scenario_groups"][root + "-opaque-0"]
        excluded[root] = (
            "same closed ancestry representative"
            if gid in assignment
            else "reserved excess capacity"
        )
    report = dict(
        policy_version="population-v1-prefit-16pct-unavailable",
        quotas=quotas,
        selected_components=len(selections),
        selected_roots=len(chosen),
        role_candidates=len(candidates),
        raw_roots=len(worlds),
        exclusions=excluded,
        exclusion_counts=dict(Counter(excluded.values())),
        selections=selections,
        input_hashes={
            path: sha256(data).hexdigest() for path, data in snapshots.items()
        },
        source_hashes=compiler_hashes(),
        release_ready=False,
    )
    artifacts = {
        "activity-candidates.jsonl": jsonl_bytes(candidates),
        "selected-worlds.jsonl": jsonl_bytes(selected_worlds),
    }
    report["artifact_hashes"] = {
        name: sha256(data).hexdigest() for name, data in artifacts.items()
    }
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "selection.json").write_bytes(json_bytes(report))
    return report


def provider_partitions(n):
    if type(n) is not int or n < 1:
        raise ValueError("positive contract count required")
    result = []

    def visit(values):
        if len(values) == n:
            result.append(tuple(values))
            return
        for value in range(max(values) + 2):
            visit(values + [value])

    visit([0])
    return result


def author_world(source, incoming, providers, deposit_channels=None):
    deposit_channels = deposit_channels or ("card",) * 6
    if (
        source not in SOURCES
        or incoming not in SOURCE_PARTITIONS
        or providers not in provider_partitions(6)
        or len(deposit_channels) != 6
        or any(channel not in {"cash", "card"} for channel in deposit_channels)
    ):
        raise ValueError("unsupported economic topology")
    w = graph.World(
        "population-"
        + source
        + "-"
        + "".join(map(str, incoming))
        + "-"
        + "".join(map(str, providers))
        + (
            "-deposits-"
            + "".join("h" if c == "cash" else "b" for c in deposit_channels)
            if "cash" in deposit_channels
            else ""
        ),
        source,
        [graph.Party("player", "account holder")],
        [],
        [],
        [],
        [],
        [],
        [],
        {},
        {},
    )

    def party(identity, role):
        if not any(p.id == identity for p in w.participants):
            w.participants.append(graph.Party(identity, role))

    def event(kind, actor, beneficiary, amount, parents=()):
        identity = f"economic-event-{len(w.events)}"
        at = (
            datetime.fromisoformat("2026-09-01T09:00:00+03:00")
            + timedelta(hours=len(w.events))
        ).isoformat()
        w.events.append(
            graph.Event(identity, kind, actor, beneficiary, amount, tuple(parents), at)
        )
        return identity

    def historical(basis, amount, counterparty, operation="card_transfer"):
        e = next(e for e in w.events if e.id == basis)
        w.history.append(
            dict(
                id=f"original-settlement-{len(w.history)}",
                occurred_at=e.at,
                operation_code=operation,
                amount=graph.money(amount),
                counterparty_id=counterparty,
                category=None,
                origin_event_id=basis,
            )
        )

    def obligation(identity, debtor, creditor, amount, basis, purpose):
        w.obligations.append(
            graph.Obligation(identity, debtor, creditor, amount, basis, purpose)
        )
        return identity

    for i, count in enumerate(incoming):
        payer = f"source-{i}"
        party(
            payer,
            dict(
                service="customer for completed independent work",
                asset="buyer of separately owned property",
                refund="supplier holding paid advance",
                debt="actual borrower of disbursed principal",
                cost="principal whose allocated cost was paid",
            )[source],
        )
        amount = 80000 * count
        if source == "service":
            contract = event("service_contract", payer, "player", amount)
            stages = [
                event("accepted_service_stage", "player", payer, 80000, [contract])
                for _ in range(count)
            ]
            basis = event("accepted_work_receivable", payer, "player", amount, stages)
        elif source == "asset":
            seller = f"original-seller-{i}"
            party(seller, "original owner transferring acquired title")
            purchase = event("asset_purchase_paid", "player", seller, amount)
            historical(purchase, amount, seller)
            title = event("title_acquired", seller, "player", amount, [purchase])
            w.rights.append(
                dict(
                    asset=f"owned-lot-{i}",
                    owner="player",
                    controller="player",
                    basis=title,
                    disposed_to=payer,
                )
            )
            basis = event("owned_asset_transferred", "player", payer, amount, [title])
        elif source in {"refund", "debt"}:
            original = event(
                "paid_advance" if source == "refund" else "loan_disbursement",
                "player",
                payer,
                count * 100000,
            )
            historical(original, count * 100000, payer)
            reduction = event(
                "accepted_nonrefundable_service"
                if source == "refund"
                else "prior_principal_repaid",
                payer,
                "player",
                count * 20000,
                [original],
            )
            if source == "debt":
                historical(reduction, count * 20000, payer, "incoming_transfer")
            basis = event(
                "partial_cancellation_refund_due"
                if source == "refund"
                else "remaining_principal_due",
                payer,
                "player",
                amount,
                [original, reduction],
            )
        else:
            provider = f"original-cost-provider-{i}"
            party(provider, "provider paid for a disclosed principal")
            mandate = event("cost_agency_authority", payer, "player", amount)
            payment = event(
                "allocated_cost_paid", "player", provider, amount, [mandate]
            )
            historical(payment, amount, provider)
            basis = event(
                "principal_reimbursement_due",
                payer,
                "player",
                amount,
                [mandate, payment],
            )
            w.rights.append(
                dict(
                    principal=payer,
                    agent="player",
                    authority=mandate,
                    allocated_cost=payment,
                )
            )
        oid = obligation(
            f"source-right-{i}", payer, "player", amount, basis, graph.PURPOSE[source]
        )
        for _ in range(count):
            w.payments.append(
                graph.Payment(
                    f"in-{len(w.payments)}",
                    oid,
                    payer,
                    "player",
                    80000,
                    "incoming_transfer",
                )
            )
    for i, ((task, gross, deposit), provider_number) in enumerate(
        zip(CONTRACTS, providers)
    ):
        creditor = f"provider-{provider_number}"
        party(creditor, "contractor for separately accepted installation services")
        contract = event("service_contract_for_player", creditor, "player", gross)
        if deposit_channels[i] == "cash":
            terms = event(
                "service_cash_deposit_required", creditor, "player", deposit, [contract]
            )
            withdrawn = event(
                "cash_withdrawn_for_service_deposit",
                "player",
                "player",
                deposit,
                [terms],
            )
            historical(withdrawn, deposit, None, "cash_withdrawal")
            handover = event(
                "cash_service_deposit_handed_over",
                "player",
                creditor,
                deposit,
                [withdrawn],
            )
            receipt = event(
                "signed_service_deposit_cash_receipt",
                creditor,
                "player",
                deposit,
                [handover],
            )
            advance = event(
                "service_cash_deposit_paid",
                "player",
                creditor,
                deposit,
                [withdrawn, receipt],
            )
        else:
            advance = event(
                "service_deposit_paid", "player", creditor, deposit, [contract]
            )
            historical(advance, deposit, creditor)
        delivery = event(
            "service_contract_completed", creditor, "player", gross, [contract, advance]
        )
        basis = event(
            "service_balance_due",
            creditor,
            "player",
            gross - deposit,
            [delivery, advance],
        )
        oid = obligation(
            "contract-" + task,
            "player",
            creditor,
            gross - deposit,
            basis,
            "personal_spending",
        )
        w.payments.append(
            graph.Payment(
                f"out-{i}", oid, "player", creditor, gross - deposit, "card_transfer"
            )
        )
    for p in w.payments:
        o = next(o for o in w.obligations if o.id == p.obligation)
        w.observations.append(
            graph.Observation(
                p.id,
                p.payer if p.operation == "incoming_transfer" else p.beneficiary,
                o.basis,
            )
        )
    payer = w.payments[2].payer
    party("victim", "owner of unrelated entrusted funds")
    party("collector", "controller of embezzled proceeds")
    entrustment = event("unrelated_funds_entrusted", "victim", payer, 80000)
    offence = event("escrow_embezzlement", payer, "collector", 80000, [entrustment])
    custody = event(
        "diverted_funds_in_sender_custody", payer, "collector", 80000, [offence]
    )
    w.crime = dict(
        source_payment="in-2",
        source_amount=80000,
        source_owner="victim",
        source_controller=payer,
        source_custodian=payer,
        offence_event=offence,
        custody_event=custody,
        collector="collector",
        routing=[
            dict(
                payment="out-5",
                amount=80000,
                actual_beneficiary="collector",
                custodian="player",
                channel="controlled_account",
            )
        ],
    )
    w.profile = dict(
        id="account-holder",
        title=dict(
            service="Service provider settling accepted installation contracts",
            asset="Property owner funding contracted improvements",
            refund="Customer recovering advances while settling completed contracts",
            debt="Private lender collecting principal for completed installation work",
            cost="Disclosed cost agent settling personal contractual liabilities",
        )[source],
        description="Separate completed contracts, actual prior deposits and remaining amounts are recorded independently of available source evidence.",
    )
    w = schedule_world(w, 0)
    w.evidence_worlds = graph.author_evidence_worlds(w)
    return w


def schedule_world(w, number):
    if number not in range(len(SCHEDULES)):
        raise ValueError("unsupported settlement schedule")
    result = deepcopy(w)
    byid = {p.id: p for p in result.payments}
    order = SCHEDULES[number]
    sequence = [
        "in-0",
        f"out-{order[0]}",
        f"out-{order[1]}",
        "in-1",
        f"out-{order[2]}",
        f"out-{order[3]}",
        "in-2",
        f"out-{order[4]}",
        f"out-{order[5]}",
    ]
    result.payments = [byid[pid] for pid in sequence]
    return result


def compile_variants(w, extra_label):
    if type(extra_label) is not int or extra_label not in (0, 1):
        raise ValueError("extra outcome must be preregistered")
    if isinstance(w, ActivityWorld):
        validate_role_world(w)
    rows = []
    for schedule in range(3):
        scheduled = schedule_world(w, schedule)
        for row in graph.compile_root(scheduled):
            mode = row["variant_recipe"]
            if row["aml_label"] is None or (schedule, mode) not in RECIPES:
                continue
            row["scenario_id"] = f"{w.id}-schedule-{schedule}-{mode}-{row['aml_label']}"
            row["variant_recipe"] = f"schedule-{schedule}-{mode}"
            row["provenance"]["counterfactual_pair_id"] = (
                w.id + "-" + row["variant_recipe"]
            )
            row["author_id"] = "causal-population-author-v1"
            row["template_ancestry"] = [
                "causal-population-contract-topology-v1",
                "typed-economic-world-v2",
            ]
            rows.append(row)
    extra = deepcopy(
        next(
            r
            for r in rows
            if r["variant_recipe"] == "schedule-0-records"
            and r["aml_label"] == extra_label
        )
    )
    extra["scenario_id"] += "-opening-unverified"
    extra["variant_recipe"] = "schedule-0-records-opening-unverified"
    extra["provenance"]["counterfactual_pair_id"] = w.id + "-opening-unverified"
    opening = next(
        f
        for f in extra["public_snapshot"]["config"]["behavior"]["aml_context"]["facts"]
        if f["id"] == "opening"
    )
    opening.update(verification_status="unverified", provenance="customer_statement")
    rows.append(extra)
    return rows


def compiler_hashes():
    return {
        **source_hashes(),
        **{
            name: sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "scripts/aml_dataset/aml_population_author.py",
                "scripts/aml_dataset/aml_world_graph.py",
                "scripts/aml_dataset/aml_origins.py",
                "scripts/aml_dataset/aml_casebook.py",
                "config/aml_scenario_templates.json",
                "docs/research/2026-09-16-aml-behavior-and-legitimate-context.md",
            )
        },
    }


def compile_diagnostics(w):
    rows = []
    for row in graph.compile_root(schedule_world(w, 2)):
        if row["variant_recipe"] != "opaque" or row["aml_label"] is None:
            continue
        row["scenario_id"] = f"{w.id}-schedule-2-opaque-{row['aml_label']}"
        row["variant_recipe"] = "schedule-2-opaque"
        row["population_role"] = "ancestry_linked_diagnostic"
        row["challenge_set"] = "masked-context"
        row["provenance"]["counterfactual_pair_id"] = w.id + "-schedule-2-opaque"
        rows.append(row)
    return rows


def compile_selected(w, selection):
    validate_role_world(w)
    if (
        selection["root_id"] != w.id
        or selection["profile"] != w.profile["id"]
        or selection["activity_sha256"] != digest(w.activity)
    ):
        raise ValueError("selection does not bind the authored activity world")
    main = compile_variants(w, selection["extra_label"])
    diagnostics = compile_diagnostics(w)
    for row in main + diagnostics:
        row["provenance"]["parent_ids"] = list(selection["parent_ids"])
        row["activity_dossier"] = deepcopy(w.activity)
        row.setdefault("population_role", "main")
        row["population_policy"] = "population-v1-prefit-16pct-unavailable"
    return main, diagnostics


def validate_saved_selection(selection_dir):
    """Reconstruct the complete prefit selection from its byte-bound raw inputs."""
    directory = Path(selection_dir)
    selection_raw = (directory / "selection.json").read_bytes()
    selection = json.loads(selection_raw)
    captured = {}
    for name, expected in selection["input_hashes"].items():
        data = Path(name).read_bytes()
        if sha256(data).hexdigest() != expected:
            raise ValueError("selection input snapshot mismatch")
        captured[Path(name)] = data
    roots_path = next(p for p in captured if p.name == "roots.jsonl")
    closure_path = next(p for p in captured if p.name == "provenance.json")
    probe_audit = json.loads(captured[roots_path.parent / "audit.json"])
    if (
        sha256(captured[roots_path]).hexdigest()
        != probe_audit["artifact_hashes"]["roots.jsonl"]
    ):
        raise ValueError("selection raw root binding mismatch")
    external = json.loads(captured[closure_path.parent / "audit.json"])
    if external["demo_crossing_components"]:
        raise ValueError("selection includes demo-connected inputs")
    closure = json.loads(captured[closure_path])
    raw_worlds = {
        v["id"]: world_from_dict(v)
        for v in map(json.loads, captured[roots_path].splitlines())
    }
    artifact_bytes = {
        name: (directory / name).read_bytes()
        for name in ("activity-candidates.jsonl", "selected-worlds.jsonl")
    }
    for name, data in artifact_bytes.items():
        if sha256(data).hexdigest() != selection["artifact_hashes"][name]:
            raise ValueError("selection candidate/world artifact mismatch")
    actual_candidates = [
        json.loads(line)
        for line in artifact_bytes["activity-candidates.jsonl"].splitlines()
    ]
    options = defaultdict(lambda: defaultdict(list))
    expected_candidates = []
    excluded = {}
    for root, w in sorted(raw_worlds.items()):
        gid = closure["scenario_groups"][root + "-opaque-0"]
        if gid in external["crossing_components"]:
            excluded[root] = "existing-development connection"
            continue
        for role, sources in ROLE_SOURCES.items():
            if w.source in sources:
                authored = author_role_world(w, role)
                options[gid][role].append(root)
                expected_candidates.append(
                    dict(
                        root_id=root,
                        raw_component=gid,
                        category=role,
                        raw_world_sha256=digest(asdict(w)),
                        activity=authored.activity,
                    )
                )
    if actual_candidates != expected_candidates:
        raise ValueError("selection candidate roster or activity proof mismatch")
    assignments = assign_roles(
        {gid: set(roles) for gid, roles in options.items()}, selection["quotas"]
    )
    expected_selections = []
    worlds = {}
    for index, (gid, role) in enumerate(sorted(assignments.items())):
        root = min(
            options[gid][role],
            key=lambda rid: (ROLE_SOURCES[role].index(raw_worlds[rid].source), rid),
        )
        w = author_role_world(raw_worlds[root], role)
        worlds[root] = w
        expected_selections.append(
            dict(
                raw_component=gid,
                root_id=root,
                profile=role,
                extra_label=index % 2,
                parent_ids=closure["groups"][gid],
                activity_sha256=digest(w.activity),
            )
        )
    if selection["selections"] != expected_selections:
        raise ValueError(
            "selection ancestry, assignment, representative or alternating label mismatch"
        )
    for root in raw_worlds:
        if root not in worlds and root not in excluded:
            gid = closure["scenario_groups"][root + "-opaque-0"]
            excluded[root] = (
                "same closed ancestry representative"
                if gid in assignments
                else "reserved excess capacity"
            )
    if (
        selection["exclusions"] != excluded
        or selection["exclusion_counts"] != dict(Counter(excluded.values()))
        or selection["selected_components"] != len(assignments)
        or selection["selected_roots"] != len(worlds)
        or selection["role_candidates"] != len(expected_candidates)
        or selection["raw_roots"] != len(raw_worlds)
    ):
        raise ValueError("selection counts or exclusions mismatch")
    actual_worlds = [
        json.loads(line)
        for line in artifact_bytes["selected-worlds.jsonl"].splitlines()
    ]
    expected_worlds = [
        json.loads(json.dumps(asdict(worlds[s["root_id"]])))
        for s in expected_selections
    ]
    if actual_worlds != expected_worlds:
        raise ValueError("selection world does not match its original role candidate")
    return selection, worlds, selection_raw, artifact_bytes["selected-worlds.jsonl"]


def build_population(selection_dir, output):
    """Write and validate every actual chain; no review or training is performed."""
    output, selection_dir = Path(output), Path(selection_dir)
    if output.exists():
        raise FileExistsError(output)
    start_sources = compiler_hashes()
    selection, worlds, selection_raw, worlds_raw = validate_saved_selection(
        selection_dir
    )
    features, closure_rows, main_rows = {}, [], []
    row_hashes = {"main.jsonl": sha256(), "diagnostics.jsonl": sha256()}
    counts = Counter()
    output.mkdir(parents=True)
    with (
        (output / "main.jsonl").open("wb") as main_file,
        (output / "diagnostics.jsonl").open("wb") as diagnostic_file,
    ):
        for index, item in enumerate(selection["selections"]):
            main, diagnostics = compile_selected(worlds[item["root_id"]], item)
            group_features = validate_sources(main + diagnostics, protocol())
            if set(features) & set(group_features):
                raise ValueError("duplicate selected scenario identity")
            features.update(group_features)
            for name, handle, rows in (
                ("main.jsonl", main_file, main),
                ("diagnostics.jsonl", diagnostic_file, diagnostics),
            ):
                data = jsonl_bytes(rows)
                handle.write(data)
                row_hashes[name].update(data)
                counts[name] += len(rows)
                closure_rows.extend(closure_row(row) for row in rows)
            main_rows.extend(
                {
                    "scenario_id": row["scenario_id"],
                    "aml_label": row["aml_label"],
                    "family_id": row["family_id"],
                    "public_snapshot": row["public_snapshot"],
                }
                for row in main
            )
            if (index + 1) % 50 == 0:
                print(
                    f"Validated {index + 1}/{len(selection['selections'])} component representatives; {counts['main.jsonl']} main rows",
                    flush=True,
                )
    closure = connected_groups(closure_rows, features)
    main_ids = {r["scenario_id"] for r in main_rows}
    main_sizes = [len(main_ids.intersection(ids)) for ids in closure["groups"].values()]
    feature_labels = defaultdict(set)
    for row in main_rows:
        feature_labels[digest(features[row["scenario_id"]])].add(row["aml_label"])
    conflicting_rows = sum(
        len(feature_labels[digest(features[row["scenario_id"]])]) > 1
        for row in main_rows
    )
    report = dict(
        scope="authored-unreviewed-population-not-release",
        counts=dict(counts),
        components=len(closure["groups"]),
        main_component_sizes=sorted(main_sizes),
        uniform_25=all(n == 25 for n in main_sizes),
        classes=dict(Counter(str(r["aml_label"]) for r in main_rows)),
        coverage=coverage_report(main_rows, protocol()),
        conflicting_x_clusters=sum(len(v) > 1 for v in feature_labels.values()),
        conflicting_x_rows=conflicting_rows,
        source_hashes=start_sources,
        source_changed_during_build=compiler_hashes() != start_sources,
        input_hashes={
            "selection.json": sha256(selection_raw).hexdigest(),
            "selected-worlds.jsonl": sha256(worlds_raw).hexdigest(),
        },
        artifact_hashes={name: h.hexdigest() for name, h in row_hashes.items()},
        reviewed_rows=0,
        release_ready=False,
    )
    for name, value in (("features.json", features), ("provenance.json", closure)):
        data = json_bytes(value)
        (output / name).write_bytes(data)
        report["artifact_hashes"][name] = sha256(data).hexdigest()
    (output / "audit.json").write_bytes(json_bytes(report))
    return report


def closure_row(row):
    """Lossless for the unchanged connected_groups field contract, without truth blobs."""
    keys = (
        "scenario_id",
        "provenance_group_id",
        "public_snapshot",
        "provenance",
        "root_id",
        "authored_root_id",
        "counterfactual_pair_id",
        "near_duplicate_id",
        "history_origin_id",
        "parent_ids",
        "history_origin_ids",
        "near_duplicate_ids",
    )
    return {k: row[k] for k in keys if k in row}


def audit_external_closure(probe, development, demo, output):
    """Parse/hash each input snapshot once; raw probe remains in authoritative closure."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    probe = Path(probe)
    audit = json.loads((probe / "audit.json").read_bytes())
    raw = (probe / "casebook.jsonl").read_bytes()
    feature_raw = (probe / "features.json").read_bytes()
    for name, data in (("casebook.jsonl", raw), ("features.json", feature_raw)):
        if sha256(data).hexdigest() != audit["artifact_hashes"][name]:
            raise ValueError("probe artifact digest mismatch")
    inputs = {
        str(probe / "casebook.jsonl"): sha256(raw).hexdigest(),
        str(probe / "features.json"): sha256(feature_raw).hexdigest(),
    }
    rows = [closure_row(json.loads(line)) for line in raw.splitlines()]
    features = json.loads(feature_raw)
    del raw, feature_raw
    partitions = {"raw_probe": {r["scenario_id"] for r in rows}}
    for name, path in (("development", development), ("demo", demo)):
        data = Path(path).read_bytes()
        inputs[str(path)] = sha256(data).hexdigest()
        additions = [json.loads(line) for line in data.splitlines()]
        ids = {r["scenario_id"] for r in additions}
        if ids & set(features):
            raise ValueError("duplicate input scenario IDs")
        features.update(validate_sources(additions, protocol()))
        partitions[name] = ids
        rows.extend(closure_row(r) for r in additions)
        del data, additions
    result = connected_groups(rows, features)
    touched = {}
    for gid, ids in result["groups"].items():
        members = set(ids)
        touched[gid] = [name for name, values in partitions.items() if members & values]
    report = dict(
        input_hashes=inputs,
        rows=len(rows),
        components=len(result["groups"]),
        partition_rows={k: len(v) for k, v in partitions.items()},
        crossing_components={k: v for k, v in touched.items() if len(v) > 1},
        demo_crossing_components=[
            k for k, v in touched.items() if "demo" in v and len(v) > 1
        ],
        merging_reasons=dict(Counter(link["reason"] for link in result["links"])),
        source_hashes=compiler_hashes(),
        release_ready=False,
    )
    output.mkdir(parents=True)
    (output / "provenance.json").write_bytes(json_bytes(result))
    (output / "audit.json").write_bytes(json_bytes(report))
    return report


def audit_probe(worlds, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    worlds = list(worlds)
    rows = []
    for w in worlds:
        rows.extend(compile_probe_rows(w))
    features = validate_sources(rows, protocol())
    closure = connected_groups(rows, features)
    clusters = defaultdict(set)
    for row in rows:
        clusters[digest(features[row["scenario_id"]])].add(row["aml_label"])
    artifacts = {
        "roots.jsonl": jsonl_bytes([asdict(w) for w in worlds]),
        "casebook.jsonl": jsonl_bytes(rows),
        "features.json": json_bytes(features),
        "provenance.json": json_bytes(closure),
    }
    report = dict(
        scope="actual-causal-topology-probe-not-release",
        authored_roots=len(worlds),
        rows=len(rows),
        components=len(closure["groups"]),
        feature_conflicts=sum(len(v) > 1 for v in clusters.values()),
        merging_reasons=dict(Counter(link["reason"] for link in closure["links"])),
        component_sizes=sorted(len(v) for v in closure["groups"].values()),
        source_hashes=compiler_hashes(),
        artifact_hashes={
            name: sha256(data).hexdigest() for name, data in artifacts.items()
        },
        release_ready=False,
        reviewed_rows=0,
    )
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "audit.json").write_bytes(json_bytes(report))
    return report


def compile_probe_rows(w):
    """Two opposite actual worlds under one opaque observation, no model calls."""
    graph.validate_world(w)
    rows = []
    for label in (0, 1):
        public, records, truth = graph._project(w, label, "opaque")
        rows.append(
            dict(
                scenario_id=f"{w.id}-opaque-{label}",
                provenance_group_id=w.id,
                family_id=graph.FAMILY[w.source],
                aml_label=label,
                label_status="confirmed",
                review_status="authored_unreviewed",
                review=None,
                author_id="causal-population-author-v1",
                label_source="authored-economic-graph",
                label_protocol_version="aml-labels-v1",
                population_id="aml-game-balanced-v1",
                label_rationale="Original actual economic events and conserved routes establish the authored outcome.",
                author_truth=truth,
                economic_records=records,
                observability=dict(
                    distinguishable=False,
                    reason="Scoped evidence is masked equally in opposite actual worlds.",
                ),
                hypothesis_source=dict(root_dossier_sha256=digest(asdict(w))),
                alternative_explanation=dict(
                    lawful="Actual due sources and liabilities settle.",
                    illicit="An independently authored diversion leaves cover rights outstanding.",
                ),
                necessary_facts=[
                    "actual source ownership",
                    "actual entitlement and beneficiary",
                ],
                forbidden_information=["hidden outcome", "root and family identifiers"],
                public_snapshot=public,
                variant_recipe="opaque",
                template_ancestry=[
                    "causal-population-contract-topology-v1",
                    "typed-economic-world-v2",
                ],
                provenance=dict(
                    root_id=w.id,
                    history_origin_id=w.id + "-history",
                    counterfactual_pair_id=w.id + "-opaque",
                    parent_ids=[],
                ),
            )
        )
    return rows


def audit_complete_population(population, probe, development, demo, output):
    """Exact unchanged closure over main, diagnostics, all raw probes and externals."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    rows, features, inputs, partitions, main_metadata = [], {}, {}, {}, []

    def snapshot_json(path):
        data = Path(path).read_bytes()
        inputs[str(path)] = sha256(data).hexdigest()
        return json.loads(data)

    for directory, names in (
        (Path(population), ("main.jsonl", "diagnostics.jsonl")),
        (Path(probe), ("casebook.jsonl",)),
    ):
        audit = snapshot_json(directory / "audit.json")
        if audit.get("source_changed_during_build"):
            raise ValueError("population build source changed")
        cached = snapshot_json(directory / "features.json")
        if (
            inputs[str(directory / "features.json")]
            != audit["artifact_hashes"]["features.json"]
        ):
            raise ValueError("cached feature artifact mismatch")
        if set(features) & set(cached):
            raise ValueError("duplicate feature scenario identity")
        features.update(cached)
        for name in names:
            path = directory / name
            hasher = sha256()
            ids = set()
            with path.open("rb") as handle:
                for line in handle:
                    hasher.update(line)
                    row = json.loads(line)
                    sid = row["scenario_id"]
                    if sid in ids or sid not in cached:
                        raise ValueError("duplicate or featureless cached row")
                    ids.add(sid)
                    rows.append(closure_row(row))
                    if name == "main.jsonl":
                        main_metadata.append(
                            dict(
                                scenario_id=sid,
                                aml_label=row["aml_label"],
                                profile=row["public_snapshot"]["config"]["behavior"][
                                    "profile"
                                ]["id"],
                            )
                        )
            inputs[str(path)] = hasher.hexdigest()
            if inputs[str(path)] != audit["artifact_hashes"][name]:
                raise ValueError("cached casebook artifact mismatch")
            partitions[
                "raw_probe" if name == "casebook.jsonl" else name.removesuffix(".jsonl")
            ] = ids
    for name, path in (("development", development), ("demo", demo)):
        data = Path(path).read_bytes()
        inputs[str(path)] = sha256(data).hexdigest()
        additions = [json.loads(line) for line in data.splitlines()]
        addition_features = validate_sources(additions, protocol())
        if set(features) & set(addition_features):
            raise ValueError("duplicate external scenario identity")
        features.update(addition_features)
        partitions[name] = set(addition_features)
        rows.extend(closure_row(row) for row in additions)
    if len(rows) != len(features) or len({r["scenario_id"] for r in rows}) != len(rows):
        raise ValueError("complete closure feature/row roster mismatch")
    closure = connected_groups(rows, features)
    crossings = {}
    main_sizes = []
    for gid, ids in closure["groups"].items():
        members = set(ids)
        touched = [name for name, values in partitions.items() if members & values]
        if len(touched) > 1:
            crossings[gid] = touched
        size = len(members & partitions["main"])
        if size:
            main_sizes.append(size)
    profile_groups = defaultdict(lambda: defaultdict(set))
    for row in main_metadata:
        profile_groups[row["profile"]][str(row["aml_label"])].add(
            closure["scenario_groups"][row["scenario_id"]]
        )
    report = dict(
        scope="complete-raw-main-diagnostic-development-demo-closure",
        rows=len(rows),
        partition_rows={k: len(v) for k, v in partitions.items()},
        components=len(closure["groups"]),
        main_components=len(main_sizes),
        main_component_sizes=sorted(main_sizes),
        uniform_25=all(n == 25 for n in main_sizes),
        profile_class_groups={
            p: {label: len(ids) for label, ids in labels.items()}
            for p, labels in profile_groups.items()
        },
        crossing_components=crossings,
        demo_crossing_components=[
            gid for gid, names in crossings.items() if "demo" in names
        ],
        input_hashes=inputs,
        source_hashes=compiler_hashes(),
        release_ready=False,
    )
    output.mkdir(parents=True)
    (output / "provenance.json").write_bytes(json_bytes(closure))
    (output / "audit.json").write_bytes(json_bytes(report))
    return report


def payroll_supplement(w):
    """Separate lawful earned payroll and delivered goods in both counterfactuals."""
    employer, merchant = w.id + "-employer", w.id + "-household-merchant"
    contract = w.id + "-employment-contract"
    work = w.id + "-employment-period-completed"
    delivery = w.id + "-household-goods-delivered"
    payments = []
    obligations = []
    authorities = []
    for code, party, amount, purpose, basis in (
        ("salary", employer, 30000, "salary", work),
        ("purchase", merchant, 10000, "personal_spending", delivery),
    ):
        pid = w.id + "-" + code
        credit = code == "salary"
        obligations.append(
            dict(
                id=pid + "-due",
                debtor=party if credit else "player",
                creditor="player" if credit else party,
                principal=amount,
                basis=basis,
                purpose=purpose,
                due=graph.START,
            )
        )
        payments.append(
            dict(
                id=pid,
                operation=code,
                amount=graph.money(amount),
                obligation=pid + "-due",
                payer=party if credit else "player",
                beneficiary="player" if credit else party,
                actual_beneficiary="player" if credit else party,
                origin_event=basis,
                actual_origin_event=basis,
                settles_obligation=True,
                origin_established=True,
                source_owner=party if credit else "player",
                source_controller=party if credit else "player",
                source_custodian=party if credit else "player",
            )
        )
        authorities.append(
            dict(
                payment=pid,
                issuer=party,
                signed_by=party,
                event=basis,
                obligation=pid + "-due",
                amount=graph.money(amount),
                claimed_purpose=purpose,
                actual_purpose=purpose,
                beneficiary="player" if credit else party,
                outcome="corroborates",
                available_at=graph.START,
            )
        )
    return dict(
        parties=[
            dict(
                id=employer,
                name="Employer for separately completed part-time work",
                kind="institution",
                information_status="sufficient",
                personal_relationship="unknown",
                category="employer",
            ),
            dict(
                id=merchant,
                name="Merchant delivering household goods",
                kind="merchant",
                information_status="sufficient",
                personal_relationship="unknown",
                category=None,
            ),
        ],
        events=[
            dict(
                id=contract,
                kind="part_time_employment_agreement",
                at="2026-08-15T09:00:00+03:00",
                employer=employer,
                employee="player",
                agreed_wage=30000,
                parents=[],
            ),
            dict(
                id=work,
                kind="employment_period_completed",
                at="2026-09-12T09:00:00+03:00",
                employer=employer,
                employee="player",
                earned_wage=30000,
                parents=[contract],
            ),
            dict(
                id=delivery,
                kind="household_goods_delivered",
                at="2026-09-12T10:00:00+03:00",
                merchant=merchant,
                buyer="player",
                amount=10000,
                parents=[],
                goods="household storage supplies delivered with payment due in this round",
            ),
        ],
        payments=payments,
        obligations=obligations,
        authorities=authorities,
        wage_is_independent_of_transfer_sources=True,
        purchase_does_not_reduce_aml_episode=True,
    )


def author_coverage_case(w, kind):
    validate_role_world(w)
    if kind not in {"cash", "salary_purchase"}:
        raise ValueError("unsupported authored coverage construction")
    settlement = deepcopy(w)
    supplement = {}
    if kind == "cash":
        from dataclasses import replace

        settlement.payments = [
            replace(p, operation="cash_withdrawal") if p.id == "out-5" else p
            for p in settlement.payments
        ]
        for route in settlement.crime["routing"]:
            if route["payment"] == "out-5":
                route["channel"] = "cash_handover"
        settlement.evidence_worlds = graph.author_evidence_worlds(settlement)
        supplement = dict(
            cash_authorities={
                name: dict(
                    payment="out-5",
                    amount=80000,
                    actual_receiver=case["actual_payments"]["out-5"]["beneficiary"],
                    issuer=case["actual_payments"]["out-5"]["beneficiary"],
                    delivery="physical handover of withdrawn banknotes",
                    available_at=graph.END,
                )
                for name, case in settlement.evidence_worlds.items()
            }
        )
    else:
        supplement = payroll_supplement(w)
    validate_role_world(settlement)
    return dict(
        kind=kind,
        base_world=asdict(w),
        settlement_world=asdict(settlement),
        supplement=supplement,
    )


def compile_coverage_case(case):
    """Project only previously authored settlement/authority records; retain root ancestry."""
    from uuid import uuid5, NAMESPACE_URL

    base = world_from_dict(case["base_world"])
    expected = author_coverage_case(base, case["kind"])
    if digest(case) != digest(expected):
        raise ValueError("coverage world/authority/actual settlement mismatch")
    w = world_from_dict(case["settlement_world"])
    rows = [
        row
        for row in graph.compile_root(w)
        if row["variant_recipe"] == "records" and row["aml_label"] is not None
    ]
    for row in rows:
        row["scenario_id"] = f"{base.id}-coverage-{case['kind']}-{row['aml_label']}"
        row["variant_recipe"] = "coverage-" + case["kind"]
        row["family_id"] = "P05" if case["kind"] == "cash" else "P10"
        row["provenance"]["counterfactual_pair_id"] = (
            base.id + "-coverage-" + case["kind"]
        )
        row["provenance"]["parent_ids"] = [base.id + "-opaque-0", base.id + "-opaque-1"]
        row["coverage_dossier_sha256"] = digest(case)
        row["coverage_supplement"] = deepcopy(case["supplement"])
        row["activity_dossier"] = deepcopy(w.activity)
        if case["kind"] == "cash":
            continue
        public = row["public_snapshot"]
        behavior = public["config"]["behavior"]
        behavior["counterparties"].extend(deepcopy(case["supplement"]["parties"]))
        context = behavior["aml_context"]
        context["purpose_catalog"].append(dict(code="salary", title="Earned payroll"))
        context["expected_activity"]["activity_kinds"].append("salary")
        context["expected_activity"].update(
            expected_credit_min="270000.00",
            expected_credit_max="270000.00",
            expected_debit_min="410000.00",
            expected_debit_max="410000.00",
        )
        cards = {
            c["code"]: {k: c[k] for k in ("id", "code", "version")}
            for c in public["config"]["card_snapshots"]
        }
        extra_steps = []
        extra_records = []
        for payment, authority in zip(
            case["supplement"]["payments"], case["supplement"]["authorities"]
        ):
            credit = payment["operation"] == "salary"
            claim = "claim-" + payment["id"]
            purpose = authority["claimed_purpose"]
            context["facts"].append(
                dict(
                    id=claim,
                    fact_type="source_of_funds" if credit else "payment_purpose",
                    verification_status="verified"
                    if authority["outcome"] == "corroborates"
                    else "contradicted",
                    provenance="independent_record",
                    available_at=authority["available_at"],
                    valid_from=graph.START,
                    valid_to=graph.END,
                    counterparty_ids=[authority["issuer"]],
                    operation_codes=[payment["operation"]],
                    purpose_code=purpose,
                    max_credit_amount=payment["amount"] if credit else "0.00",
                    max_debit_amount="0.00" if credit else payment["amount"],
                )
            )
            step = dict(
                step_id=str(uuid5(NAMESPACE_URL, payment["id"])),
                card=cards[payment["operation"]],
                amount=payment["amount"],
                context={},
                action_details=dict(income_basis="payroll_registry") if credit else {},
                interval_minutes=None if credit else 1,
                purpose_code=purpose,
                claim_id=claim,
            )
            step["sender_id" if credit else "recipient_id"] = authority["issuer"]
            extra_steps.append(step)
            extra_records.append(
                dict(
                    id=payment["id"],
                    amount=payment["amount"],
                    origin_event_id=payment["origin_event"],
                    obligation_id=payment["obligation"],
                    operation=payment["operation"],
                    step_number=len(extra_steps),
                    record_check=deepcopy(authority),
                    actual_payment=deepcopy(payment),
                    observed_record_status="verified",
                )
            )
        public["steps"][0]["interval_minutes"] = 1
        public["steps"] = extra_steps + public["steps"]
        for record in row["economic_records"]:
            record["step_number"] += 2
        row["economic_records"] = extra_records + row["economic_records"]
        row["author_truth"]["actual_payments"] = (
            deepcopy(case["supplement"]["payments"])
            + row["author_truth"]["actual_payments"]
        )
        row["author_truth"]["actual_events"].extend(
            deepcopy(case["supplement"]["events"])
        )
        row["author_truth"]["remaining_obligations"].extend(
            dict(o, outstanding_after_round=0)
            for o in case["supplement"]["obligations"]
        )
        row["author_truth"]["actual_world_sha256"] = digest(
            dict(
                coverage=case,
                base_actual_world=row["author_truth"]["actual_world_sha256"],
            )
        )
        row["hypothesis_source"]["coverage_world_sha256"] = digest(case)
    return rows


def audit_probe_union(probes, development, demo, output):
    """Use byte-bound previously full-validated probes in one unchanged closure."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    start_sources = compiler_hashes()
    inputs, parts, features, rows = {}, {}, {}, []
    for name, directory in probes.items():
        directory = Path(directory)
        audit_raw = (directory / "audit.json").read_bytes()
        audit = json.loads(audit_raw)
        raw = (directory / "casebook.jsonl").read_bytes()
        feature_raw = (directory / "features.json").read_bytes()
        for filename, data in (
            ("audit.json", audit_raw),
            ("casebook.jsonl", raw),
            ("features.json", feature_raw),
        ):
            inputs[str(directory / filename)] = sha256(data).hexdigest()
            if (
                filename != "audit.json"
                and inputs[str(directory / filename)]
                != audit["artifact_hashes"][filename]
            ):
                raise ValueError(
                    "probe union snapshot does not match full-validation receipt"
                )
        if audit.get("source_changed_during_build"):
            raise ValueError("probe source changed during generation")
        cached = json.loads(feature_raw)
        ids = set()
        for line in raw.splitlines():
            row = json.loads(line)
            sid = row["scenario_id"]
            if sid in features or sid in ids or sid not in cached:
                raise ValueError("duplicate or featureless probe scenario")
            ids.add(sid)
            features[sid] = cached[sid]
            rows.append(closure_row(row))
        parts[name] = ids
        del raw, feature_raw, cached
    for name, path in (("development", development), ("demo", demo)):
        raw = Path(path).read_bytes()
        inputs[str(path)] = sha256(raw).hexdigest()
        additions = [json.loads(line) for line in raw.splitlines()]
        extra = validate_sources(additions, protocol())
        if set(extra) & set(features):
            raise ValueError("duplicate external scenario identity")
        features.update(extra)
        parts[name] = set(extra)
        rows.extend(closure_row(row) for row in additions)
    result = connected_groups(rows, features)
    population = set().union(*(parts[name] for name in probes))
    crossing = {
        gid: [name for name, ids in parts.items() if set(members) & ids]
        for gid, members in result["groups"].items()
    }
    report = dict(
        scope="complete retained probe universe plus current development and demo",
        rows=len(rows),
        components=len(result["groups"]),
        population_components=sum(
            bool(set(ids) & population) for ids in result["groups"].values()
        ),
        partitions={name: len(ids) for name, ids in parts.items()},
        crossing_components={
            gid: names for gid, names in crossing.items() if len(names) > 1
        },
        demo_crossing_components=[
            gid for gid, names in crossing.items() if "demo" in names and len(names) > 1
        ],
        input_hashes=inputs,
        source_hashes=start_sources,
        source_changed_during_audit=start_sources != compiler_hashes(),
        release_ready=False,
    )
    data = json_bytes(result)
    report["artifact_hashes"] = {"provenance.json": sha256(data).hexdigest()}
    output.mkdir(parents=True)
    (output / "provenance.json").write_bytes(data)
    (output / "audit.json").write_bytes(json_bytes(report))
    return report
