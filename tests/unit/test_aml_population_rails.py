"""Settlement coverage must retain actual ownership, money and ancestry."""

from copy import deepcopy

import pytest

from scripts.aml_dataset import aml_population_author as population
from scripts.aml_dataset.aml_population_rails import (
    author_route,
    compile_route,
    compile_inactive_history,
)


@pytest.fixture
def world():
    return population.author_role_world(
        population.author_world("asset", (1, 1, 1), (0, 0, 1, 2, 3, 4)),
        "collection_owner",
    )


@pytest.mark.parametrize(
    "rail", ["payment_service", "crypto_p2p", "exchange_withdrawal"]
)
def test_routes_pass_full_engine_keep_both_truths_and_parent_history(world, rail):
    dossier = author_route(world, rail)
    if rail == "payment_service":
        instruction = dossier["worlds"]["lawful"][0]["events"][0]
        assert (
            instruction["originating_account_jurisdiction"]
            != instruction["destination_account_jurisdiction"]
        )
    rows = compile_route(dossier)
    assert len(rows) == 6
    assert len(population.validate_sources(rows, population.protocol())) == 6
    assert {r["aml_label"] for r in rows} == {0, 1}
    assert all(
        r["provenance"]["parent_ids"]
        == [world.id + "-opaque-0", world.id + "-opaque-1"]
        for r in rows
    )
    assert all(r["review_status"] == "authored_unreviewed" for r in rows)
    for row in rows:
        assert all(
            s["action_details"] == {"incoming_kind": rail}
            for s in row["public_snapshot"]["steps"]
            if s["card"]["code"] == "incoming_transfer"
        )
        assert len(row["author_truth"]["settlement_routes"]) == 3
        for record, step in zip(
            row["economic_records"], row["public_snapshot"]["steps"], strict=True
        ):
            if step["card"]["code"] == "incoming_transfer":
                assert record["actual_payment"]["payer"] == step["sender_id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("funding_owner", "player"),
        ("funding_custodian", "victim"),
        ("amount", "1.00"),
        ("parents", []),
    ],
)
def test_changed_criminal_settlement_cannot_be_projected(world, field, value):
    dossier = author_route(world, "payment_service")
    bad = deepcopy(dossier)
    bad["worlds"]["criminal"][-1]["events"][0][field] = value
    with pytest.raises(ValueError, match="ledger mismatch"):
        compile_route(bad)


def test_digital_conversion_amount_and_exchange_owner_are_bound(world):
    dossier = author_route(world, "exchange_withdrawal")
    for index, field, value in [
        (1, "units", "999.00"),
        (2, "account_owner", "collector"),
    ]:
        bad = deepcopy(dossier)
        bad["worlds"]["lawful"][0]["events"][index][field] = value
        with pytest.raises(ValueError, match="ledger mismatch"):
            compile_route(bad)


def test_ordinary_service_cannot_be_relabelled_as_digital_asset_sale():
    world = population.author_role_world(
        population.author_world("service", (3,), (0, 0, 1, 2, 3, 4)), "artisan_owner"
    )
    with pytest.raises(ValueError, match="asset sale"):
        author_route(world, "crypto_p2p")


def test_inactive_statement_retains_older_actual_payments_and_ancestry(world):
    rows = compile_inactive_history(world)
    features = population.validate_sources(rows, population.protocol())
    assert len(rows) == len(features) == 10
    assert {r["family_id"] for r in rows} == {"P09"}
    for row in rows:
        assert features[row["scenario_id"]]["observed_inactivity"] == 1
        assert row["author_truth"]["complete_pre_round_account_history"]
        assert row["provenance"]["parent_ids"] == [
            world.id + "-opaque-0",
            world.id + "-opaque-1",
        ]
        assert (
            row["public_snapshot"]["config"]["behavior"]["history"]["operations"] == []
        )
