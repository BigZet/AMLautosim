"""Explicit proxy trust and short-lived signed UI authentication context."""

import hashlib
import hmac
from ipaddress import ip_address, ip_network
import time


def trusted_peer(peer, networks):
    try:
        return any(ip_address(peer) in ip_network(network) for network in networks)
    except ValueError:
        return False


def forwarded_client(peer, forwarded, networks):
    if not trusted_peer(peer, networks):
        return peer
    # Walk from the immediate proxy toward the first untrusted address.
    chain = [part.strip() for part in (forwarded or '').split(',') if part.strip()]
    current = peer
    try:
        for item in reversed(chain):
            if not trusted_peer(current, networks):
                break
            current = str(ip_address(item))
        return current
    except ValueError:
        return peer


def _signature(ip, stamp, operation, email, secret):
    body = '\n'.join((ip, stamp, operation, email.strip().lower()))
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def sign_context(ip, operation, email, secret, *, now=None):
    if not secret:
        return {}
    ip = str(ip_address(ip))
    stamp = str(int(time.time() if now is None else now))
    return {'x-aml-client-ip': ip, 'x-aml-client-time': stamp,
            'x-aml-client-signature': _signature(ip, stamp, operation, email, secret)}


def verify_context(headers, operation, email, secret, *, now=None):
    if not secret:
        return None
    try:
        ip = str(ip_address(headers.get('x-aml-client-ip', '')))
        stamp = headers.get('x-aml-client-time', '')
        if abs((time.time() if now is None else now) - int(stamp)) > 30:
            return None
        expected = _signature(ip, stamp, operation, email, secret)
        return ip if hmac.compare_digest(expected, headers.get('x-aml-client-signature', '')) else None
    except (ValueError, TypeError):
        return None
