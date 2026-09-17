"""Public v10 input semantics, shared by the server and the local editor.

These rules validate statements; they never assign a risk or infer legitimacy.
The frozen classifier continues to assess structural transaction patterns.
"""

PURPOSE_POLICY_VERSION = "operation-purposes-v1"
TRANSFER_PURPOSES = (
    "unknown",
    "loan",
    "refund",
    "asset_sale",
    "shared_expense",
    "service_payment",
)
OPERATION_PURPOSES = {
    "salary": ("salary",),
    "incoming_transfer": TRANSFER_PURPOSES,
    "card_transfer": (*TRANSFER_PURPOSES, "personal_spending"),
    "purchase": ("unknown", "personal_spending", "service_payment"),
    "cash_withdrawal": ("unknown", "personal_spending", "shared_expense"),
}
INCOMING_PURPOSES = {
    "crypto_p2p": ("unknown", "asset_sale"),
    "exchange_withdrawal": ("unknown", "asset_sale"),
}


def allowed_purposes(step):
    code = step["card"]["code"]
    if code == "incoming_transfer":
        kind = step.get("action_details", {}).get("incoming_kind")
        return INCOMING_PURPOSES.get(kind, TRANSFER_PURPOSES)
    return OPERATION_PURPOSES.get(code, ())


def default_purpose(step):
    choices = allowed_purposes(step)
    return choices[0] if len(choices) == 1 else "unknown"


def validate_purpose(step):
    if step.get("purpose_code") not in allowed_purposes(step):
        raise ValueError(
            "Назначение не соответствует типу операции или способу поступления. "
            "Выберите подходящее назначение."
        )


def purpose_field_label(step):
    return (
        "Планируемое использование наличных"
        if step["card"]["code"] == "cash_withdrawal"
        else "Назначение операции"
    )
