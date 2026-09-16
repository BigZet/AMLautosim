"""Isolated v9 preview/autosave; no production start or model fallback."""
import json
from copy import deepcopy

from scripts.aml_dataset.semantic import review_cases
from src.aml_workshop_simulator.services.round_configuration import config_version


def test_v9_http_matrix_and_saved_observations(request_api, admin, player, active_round, sql, command):
    case = review_cases()[1][0]
    config = deepcopy(case['config'])
    config['config_version'] = config_version(config)
    # Test-only fixture: normal creation remains explicitly gated.
    sql('UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id',
        {'config':json.dumps(config), 'id':active_round})
    path = f'/rounds/{active_round}/scenario'
    for kind in ('bank_transfer','payment_service','exchange_withdrawal','crypto_p2p'):
        for party in ('A','B','C','D','exchange','employer','shop','missing'):
            steps = deepcopy(case['steps'])
            steps[0]['sender_id'] = party
            steps[0]['action_details'] = {'incoming_kind':kind}
            if kind == 'bank_transfer':
                steps[0]['action_details']['bank_country'] = 'RU'
            valid = party == 'exchange' if kind == 'exchange_withdrawal' else party in ('A','B','C','D')
            result = request_api('POST',path+'/preview',player['headers'],{'steps':steps},200 if valid else 422)
            if valid:
                assert result['can_submit']
                assert 'risk_score' not in result
    steps = deepcopy(case['steps'])
    steps[0]['action_details'] = {'incoming_kind':'crypto_p2p'}
    saved = request_api('PUT',path,player['headers'],command(steps))
    loaded = request_api('GET',path,player['headers'])
    assert loaded['steps'] == saved['steps']
    assert loaded['steps'][0]['action_details'] == {'incoming_kind':'crypto_p2p'}
    cards = request_api('GET',f'/rounds/{active_round}/cards')
    assert {f['key'] for c in cards if c['code']=='incoming_transfer' for f in c['fields']} == {'incoming_kind','bank_country'}
    sql("UPDATE rounds SET status='draft' WHERE id=:id",{'id':active_round})
    request_api('POST',f'/admin/rounds/{active_round}/start',admin,status=409)
