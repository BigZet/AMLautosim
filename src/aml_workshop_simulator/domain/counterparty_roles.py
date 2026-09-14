"""Allowed identities for the expanded contract; no scoring semantics."""

# Merchant payments are reserved for stage 04 and need an enabled purchase card.
PARTY_ROLES = {
    "incoming_transfer": ("sender_id", frozenset({"person", "institution"})),
    "salary": ("sender_id", frozenset({"institution"})),
    "card_transfer": ("recipient_id", frozenset({"person", "institution"})),
    "purchase": ("recipient_id", frozenset({"merchant"})),
    "cash_withdrawal": (None, frozenset()),
}


def party_allowed(code, party, sender_policy=None):
    """Shared predicate for UI, current steps and observed history."""

    def value(key):
        return party.get(key) if isinstance(party, dict) else getattr(party, key)

    if value("kind") not in PARTY_ROLES[code][1]:
        return False
    if sender_policy == "separate-employer-v1":
        if code == "incoming_transfer" and value("category") == "employer":
            return False
        if code == "salary" and value("category") != "employer":
            return False
    return True
