"""Deterministic, disjoint observed flow episodes, not tracing ownership of money."""

from decimal import Decimal


def flow_episodes(steps, timeline):
    episodes = []
    active = None
    for step, moment in zip(steps, timeline):
        now = moment["elapsed_minutes"]
        if active and now - active["start"] >= 1440:
            active = None
        code = step["card"]["code"]
        amount = Decimal(str(step["amount"]))
        if code in ("incoming_transfer", "salary"):
            if active is None:
                active = dict(start=now, last_credit=now, incoming=Decimal(0),
                              outgoing=Decimal(0), senders=set(), recipients=set(), cash=False)
            active["incoming"] += amount
            active["last_credit"] = now
            active["senders"].add(step.get("sender_id"))
        elif code in ("card_transfer", "cash_withdrawal") and active:
            active["outgoing"] += amount
            if code == "cash_withdrawal":
                active["cash"] = True
            else:
                active["recipients"].add(step.get("recipient_id"))
            # Strict five-percent tolerance, computed in decimal money.
            if abs(active["incoming"] - active["outgoing"]) < active["incoming"] * Decimal(".05"):
                episodes.append(dict(
                    start=active["start"], end=now,
                    amount=float(active["incoming"]),
                    gap=now - active["last_credit"],
                    returned=bool(active["recipients"]) and not active["cash"]
                    and active["recipients"].issubset(active["senders"]),
                ))
                active = None
            elif active["outgoing"] >= active["incoming"] * Decimal("1.05"):
                active = None
    return episodes


def episode_features(episodes):
    small_run = longest = large = returns = 0
    tempo_sum = 0.0
    previous_end = None
    for episode in episodes:
        if previous_end is None or episode["start"] - previous_end >= 1440:
            small_run = 0
        if episode["amount"] < 10000:
            small_run += 1
            longest = max(longest, small_run)
        else:
            small_run = 0
            large += 1
            returns += int(episode["returned"])
            tempo_sum += min(1, max(0, (60 - episode["gap"]) / 50))
        previous_end = episode["end"]
    return dict(matched_large_episode_count=large,
                matched_large_tempo_mean=tempo_sum / max(large, 1),
                matched_small_max_run=longest,
                observed_return_cycle_count=returns)
