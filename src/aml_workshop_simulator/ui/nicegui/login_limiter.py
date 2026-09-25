"""Early process-wide UI limiter, shared across tabs and disconnected pages."""

import hashlib
from threading import Lock
import time

from src.aml_workshop_simulator.core.auth_limits import consume


class LoginLimiter:
    def __init__(self, pair_limit=10, ip_limit=300, burst=120, max_keys=10000):
        self.pair_limit, self.ip_limit, self.burst = pair_limit, ip_limit, burst
        self.max_keys = max_keys
        self.states = {}
        self.lock = Lock()

    def check(self, ip, email, *, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if len(self.states) >= self.max_keys:
                self.states = {key: state for key, state in self.states.items() if state['at'] > now - 120}
            for label, limit, burst in ((ip, self.ip_limit, self.burst),
                                         (ip + '\0' + email.strip().lower(), self.pair_limit, None)):
                key = hashlib.sha256(label.encode()).hexdigest()
                if key not in self.states and len(self.states) >= self.max_keys:
                    return 60
                state, retry = consume(self.states.get(key, {}), limit=limit, burst=burst, now=now)
                self.states[key] = state
                if retry:
                    return retry
            return 0
