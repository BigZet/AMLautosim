"""Serializable sliding-window state shared by UI and PostgreSQL API gates."""

import math


def consume(state, *, limit, now, burst=None):
    hits = [stamp for stamp in state.get('hits', []) if stamp > now - 60]
    tokens = min(burst, state.get('tokens', burst) + max(0, now - state.get('at', now)) * limit / 60) if burst else None
    retry = max(1, math.ceil(hits[0] + 60 - now)) if len(hits) >= limit else 0
    if tokens is not None and tokens < 1:
        retry = max(retry, math.ceil((1 - tokens) * 60 / limit))
    if not retry:
        hits.append(now)
        if tokens is not None:
            tokens -= 1
    return {'hits': hits, 'tokens': tokens, 'at': now}, retry
