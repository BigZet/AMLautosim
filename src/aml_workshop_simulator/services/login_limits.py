"""Durable API admission gate: no account-global lockout and no raw PII keys."""

from datetime import UTC, datetime, timedelta
import hashlib
import time

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from src.aml_workshop_simulator.core.auth_limits import consume
from src.aml_workshop_simulator.core.client_context import trusted_peer, verify_context
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.errors import RateLimited
from src.aml_workshop_simulator.db.models.auth_rate_limits import AuthRateLimit


async def admit(request, email, operation, db):
    peer = request.client.host if request.client else 'unknown'
    ip = peer
    if trusted_peer(peer, settings.AUTH_TRUSTED_UI_CIDRS):
        secret = settings.AUTH_CONTEXT_SECRET.get_secret_value() if settings.AUTH_CONTEXT_SECRET else ''
        ip = verify_context(request.headers, operation, email, secret) or peer
    now = time.time()
    stamp = datetime.now(UTC)
    retry = 0
    for label, limit, burst in ((ip, settings.AUTH_IP_PER_MINUTE, settings.AUTH_IP_BURST),
                                (ip + '\0' + email.strip().lower(), settings.AUTH_PAIR_PER_MINUTE, None)):
        key = hashlib.sha256(label.encode()).hexdigest()
        await db.execute(insert(AuthRateLimit).values(key=key, state={}, updated_at=stamp).on_conflict_do_nothing())
        row = (await db.execute(select(AuthRateLimit).where(AuthRateLimit.key == key).with_for_update())).scalar_one()
        row.state, retry = consume(row.state, limit=limit, burst=burst, now=now)
        row.updated_at = stamp
        if retry:
            break
    # Bounded opportunistic cleanup; old rows carry only hashed keys and timestamps.
    stale = select(AuthRateLimit.key).where(AuthRateLimit.updated_at < stamp - timedelta(hours=1)).limit(100).with_for_update(skip_locked=True)
    await db.execute(delete(AuthRateLimit).where(AuthRateLimit.key.in_(stale)))
    await db.commit()
    if retry:
        raise RateLimited('Слишком много попыток входа. Повторите позже.',
                          code='login_temporarily_locked', headers={'Retry-After': str(retry)})
