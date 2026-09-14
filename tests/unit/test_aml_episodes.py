"""Boundary tests for observed flow matching, independent of game resource limits."""

import pytest

from src.aml_workshop_simulator.services.aml_episodes import flow_episodes, episode_features


def match(events):
    steps = [dict(card=dict(code=code), amount=str(amount), sender_id="A",
                  recipient_id=party) for _, code, amount, party in events]
    return flow_episodes(steps, [dict(elapsed_minutes=t) for t, *_ in events])


@pytest.mark.parametrize("amount,matched", [(9500, False), (9500.01, True),
    (9999, True), (10000, True), (10499.99, True), (10500, False)])
def test_strict_five_percent(amount, matched):
    assert bool(match([(0, "incoming_transfer", 10000, None),
                       (1, "card_transfer", amount, "B")])) == matched


def test_aggregation_cash_purchase_and_disjoint_consumption():
    episodes = match([(0, "incoming_transfer", 30000, None),
                      (1, "incoming_transfer", 30000, None),
                      (2, "card_transfer", 30000, "B"),
                      (3, "purchase", 1000, "shop"),
                      (4, "cash_withdrawal", 30000, None),
                      (5, "card_transfer", 60000, "A")])
    assert len(episodes) == 1
    assert episodes[0]["amount"] == 60000
    assert not episodes[0]["returned"]
    assert episodes[0]["gap"] == 3


@pytest.mark.parametrize("gap,matched", [(1439, True), (1440, False), (1441, False)])
def test_window_is_strictly_less_than_day(gap, matched):
    assert bool(match([(0, "incoming_transfer", 60000, None),
                       (gap, "card_transfer", 60000, "A")])) == matched


def test_small_boundary_series_and_daily_reset():
    events = []
    for index in range(9):
        events.extend([(index * 3, "incoming_transfer", 9999, None),
                       (index * 3 + 1, "card_transfer", 9999, "B"),
                       (index * 3 + 2, "purchase", 1, "shop")])
    result = episode_features(match(events))
    assert result["matched_small_max_run"] == 9
    assert result["matched_large_episode_count"] == 0
    assert episode_features(match([(0, "incoming_transfer", 10000, None),
                                  (1, "card_transfer", 10000, "A")]))["matched_large_episode_count"] == 1
    events.extend([(1465, "incoming_transfer", 9999, None),
                   (1466, "card_transfer", 9999, "B")])
    assert episode_features(match(events))["matched_small_max_run"] == 9


def test_tiny_partial_returns_do_not_create_cycles():
    assert not match([(0, "incoming_transfer", 60000, None),
                      (1, "card_transfer", 1000, "A"),
                      (2, "incoming_transfer", 60000, None),
                      (3, "card_transfer", 1000, "A")])


def test_split_return_is_one_cycle():
    episodes = match([(0, "incoming_transfer", 60000, None),
                      (1, "card_transfer", 30000, "A"),
                      (2, "card_transfer", 30000, "A")])
    assert episode_features(episodes)["observed_return_cycle_count"] == 1


def test_rubric_episode_levels_context_and_small_series():
    from scripts.check_expanded_balance import demo_config, demo_steps
    from scripts.aml_dataset.expanded import label, rubric, extract_features

    config = demo_config()
    features = extract_features(demo_steps(config), config)
    features.update(history_known=1, history_stable_background=0,
                    observed_return_cycle_count=0, matched_large_tempo_mean=1,
                    matched_small_max_run=0)

    def component(changed):
        return next(t["contribution"] for t in label(changed, rubric())[1]
                    if t["name"] == "Matched flow and returns")

    for count, expected in ((0, 0), (1, 3), (2, 6), (3, 10), (8, 10)):
        f = dict(features, matched_large_episode_count=count)
        assert component(f) == expected
        assert component(dict(f, history_known=0)) == expected * .5
        assert component(dict(f, history_stable_background=1)) == expected * .5
        assert component(dict(f, history_known=0, history_stable_background=1)) == expected * .5
    for count, expected in ((1, 0), (4, 0), (5, 1), (6, 2), (9, 5), (15, 5)):
        assert component(dict(features, matched_large_episode_count=0,
                              matched_small_max_run=count)) == expected
    assert component(dict(features, matched_large_episode_count=3,
                          observed_return_cycle_count=3)) == 10
