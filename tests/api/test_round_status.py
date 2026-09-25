
import pytest
import json


def test_light_status_changes_with_draft_revision_and_never_contains_config(request_api, player, active_round, chain, command):
    path = '/rounds/current/status'
    first = request_api('GET', path, player['headers'])
    assert first['round_id'] == active_round
    assert first['status'] == 'active'
    assert first['scenario_revision'] == 0
    assert first == request_api('GET', path, player['headers'])
    assert 'game_config' not in json.dumps(first)
    assert len(json.dumps(first)) < 600
    request_api('PUT', f'/rounds/{active_round}/scenario', player['headers'], command(chain()))
    second = request_api('GET', path, player['headers'])
    assert second['scenario_revision'] == 1
    assert second['results_version'] == first['results_version']


def test_status_without_round_and_anonymous_request(api, request_api, player, sql):
    assert api.get('/api/v1/rounds/current/status').status_code == 401
    sql('DELETE FROM rounds')
    status = request_api('GET', '/rounds/current/status', player['headers'])
    assert status['round_id'] is None
    assert status['status'] == 'none'


def test_light_poll_bytes_and_query_count(api, player, active_round):
    from src.aml_workshop_simulator.core.observability import metrics

    measured = {}
    for endpoint in ['state', 'status']:
        before = metrics.snapshot()['histograms']['sql_seconds']['count']
        sizes = []
        for _ in range(10):
            response = api.get('/api/v1/rounds/current/'+endpoint, headers=player['headers'])
            assert response.status_code == 200
            sizes.append(len(response.content))
        after = metrics.snapshot()['histograms']['sql_seconds']['count']
        measured[endpoint] = {'bytes': sum(sizes), 'queries': after-before}
    assert measured['status']['bytes'] < measured['state']['bytes'] * .1
    assert measured['status']['queries'] <= measured['state']['queries']
    print(json.dumps(measured))


def test_other_account_access_invalidates_rating_version(api, request_api, admin, player, player_factory):
    other = player_factory('Other')
    first = request_api('GET', '/rounds/current/status', player['headers'])
    for revision, blocked in [(1, True), (2, False)]:
        request_api('PUT', f"/admin/participants/{other['id']}/access", admin,
                    {'blocked': blocked, 'reason': 'Visibility check', 'expected_access_revision': revision})
        changed = request_api('GET', '/rounds/current/status', player['headers'])
        assert changed['results_version'] != first['results_version']
        first = changed
    assert api.get('/api/v1/rounds/current/status', headers=other['headers']).status_code == 401


@pytest.mark.usefixtures("scoring_worker")
def test_results_version_and_cutoff_counts(request_api, player, player_factory, admin, active_round, command, chain, sql):
    other = player_factory('Draft')
    path = f'/rounds/{active_round}/scenario'
    request_api('POST', path+'/submit', player['headers'], command(chain()))
    request_api('PUT', path, other['headers'], command(chain()))
    counts = request_api('GET', f'/admin/rounds/{active_round}/admission', admin)
    assert counts == {'registered_total': 2, 'editing': 1, 'submitted': 1, 'scored': 0}
    before = request_api('GET', '/rounds/current/status', player['headers'])
    request_api('POST', f'/admin/rounds/{active_round}/score?wait=true', admin)
    after = request_api('GET', '/rounds/current/status', player['headers'])
    assert after['status'] == 'completed'
    assert after['results_version'] != before['results_version']
    audit = sql("SELECT metadata FROM audit_events WHERE event_type='round_closed'")[0]['metadata']
    assert audit['deleted_drafts_count'] == 1
    assert audit['submitted_count'] == 1
    board = request_api('GET', f'/rounds/{active_round}/leaderboard', player['headers'])
    assert board['results_version'] == after['results_version']
    assert board['current_user_row']['is_current_user']
    sql('UPDATE users SET access_revision=access_revision+1 WHERE id=:id', {'id': player['id']})
    changed = request_api('GET', '/rounds/current/status', player['headers'])
    assert changed['access_revision'] == after['access_revision']+1
    assert changed['results_version'] != after['results_version']


@pytest.mark.usefixtures("scoring_worker")
def test_own_row_outside_top_two_hundred(request_api, player, admin, active_round, command, chain, sql):
    request_api('POST', f'/rounds/{active_round}/scenario/submit', player['headers'], command(chain()))
    request_api('POST', f'/admin/rounds/{active_round}/score?wait=true', admin)
    sql('''WITH inserted AS (
        INSERT INTO users(email, display_name, hashed_password, role, is_blocked, access_revision, failed_login_count)
        SELECT 'rank-' || n || '@example.com', 'Rank ' || n, u.hashed_password, 'participant', false, 0, 0
        FROM users u CROSS JOIN generate_series(1,200) n WHERE u.id=:id RETURNING id
    ) INSERT INTO scenarios(round_id, participant_id, status, steps, resource_snapshot, revision, updated_at, submitted_at)
      SELECT s.round_id, u.id, s.status, s.steps, s.resource_snapshot, s.revision, s.updated_at, s.submitted_at
      FROM inserted u CROSS JOIN scenarios s WHERE s.participant_id=:id''', {'id': player['id']})
    sql('''INSERT INTO scoring_results(scenario_id,risk_score,risk_label,stealth_score,resource_score,game_score,
                    explanation,scoring_version,leaderboard_version,created_at)
      SELECT s.id, r.risk_score,r.risk_label,r.stealth_score,r.resource_score,100-s.id*0.01,
             r.explanation,r.scoring_version,r.leaderboard_version,r.created_at
      FROM scenarios s CROSS JOIN scoring_results r WHERE s.participant_id != :id''', {'id': player['id']})
    sql('UPDATE scoring_results SET game_score=0 WHERE scenario_id=(SELECT id FROM scenarios WHERE participant_id=:id)', {'id': player['id']})
    board = request_api('GET', f'/rounds/{active_round}/leaderboard?limit=200', player['headers'])
    assert len(board['rows']) == 200
    assert not any(row['is_current_user'] for row in board['rows'])
    assert board['current_user_row']['rank'] == 201
    assert board['current_user_row']['is_current_user']
    assert not {'email', 'participant_id', 'scenario_id', 'risk_score'} & board['current_user_row'].keys()
    result = request_api('GET', f'/rounds/{active_round}/result', player['headers'])
    assert result['rank'] == board['current_user_row']['rank']

