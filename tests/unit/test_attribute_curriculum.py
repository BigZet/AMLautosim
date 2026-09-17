from collections import defaultdict
from decimal import Decimal
import pytest

from scripts.aml_game_curriculum_v8 import candidate as previous
from scripts.aml_game_curriculum_v9 import candidate, catalog
from scripts.audit_aml_attribute_coverage import expected
from src.aml_workshop_simulator.domain.operation_purposes import validate_purpose
from src.aml_workshop_simulator.services.semantic_contract import allowed_party, fields_for


def test_attribute_sampling_preserves_money_context_and_conditional_semantics():
    config, _ = catalog()
    parties = {p['id']: p for p in config['behavior']['counterparties']}
    observed = defaultdict(set)
    for seed in range(2051900000, 2051901000):
        old_config, old_steps, *_ = previous(seed)
        actual, steps, *_ = candidate(seed)
        assert actual == old_config == config
        assert [Decimal(s['amount']) for s in steps] == [Decimal(s['amount']) for s in old_steps]
        assert [s['step_id'] for s in steps] == [s['step_id'] for s in old_steps]
        for step in steps:
            validate_purpose(step)
            code = step['card']['code']
            details = step['action_details']
            for key, value in details.items():
                observed[code, key].add(value)
            if code == 'incoming_transfer':
                assert ('bank_country' in details) == (details['incoming_kind'] == 'bank_transfer')
            party = step.get('sender_id') or step.get('recipient_id')
            if party:
                assert allowed_party(code, parties[party], details)
    for code in ('incoming_transfer', 'salary'):
        for field in fields_for(code):
            assert observed[code, field['key']] == {o['value'] for o in field['options']}


def test_coverage_contract_includes_conditional_values_and_channels():
    required = expected(catalog()[0])
    assert 'incoming_transfer:bank_transfer|bank_country|KG' in required
    assert 'incoming_transfer:exchange_withdrawal|party|exchange' in required
    assert 'incoming_transfer:exchange_withdrawal|party|A' not in required
    assert 'incoming_transfer:crypto_p2p|purpose|loan' not in required
    assert 'card_transfer|channel|web' in required
    assert 'cash_withdrawal|channel|branch' in required
    assert 'purchase|purpose|service_payment' in required
    assert 'salary|wait|1440' in required


def test_new_editor_fields_cannot_silently_escape_audit(monkeypatch):
    from scripts import audit_aml_attribute_coverage as coverage
    monkeypatch.setattr(coverage, 'fields_for', lambda code: [{'key':'new_attribute'}])
    with pytest.raises(ValueError, match='Uncovered editor field'):
        coverage.expected(catalog()[0])
