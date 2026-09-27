"""Autosave deadlines and in-flight edits against the real editor controller."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.aml_workshop_simulator.ui.nicegui import participant
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor

pytestmark = pytest.mark.runtime


def setup_screen(monkeypatch):
    clock = SimpleNamespace(now=10.0)
    monkeypatch.setattr(participant, "time", SimpleNamespace(monotonic=lambda: clock.now))
    calls = []
    hooks = {}

    class API:
        async def request(self, method, path, **kwargs):
            body = deepcopy(kwargs['body'])
            kind = 'preview' if path.endswith('/preview') else 'save'
            calls.append((kind, body))
            if kind in hooks:
                await hooks[kind]()
            if kind == 'preview':
                return {'can_submit': True}
            return {'status': 'editing', 'revision': body['expected_revision'] + 1,
                    'steps': body['steps']}

    screen = participant.ParticipantScreen.__new__(participant.ParticipantScreen)
    screen.editor = GameEditor(API(), 'token', {
        'key': [1, 1], 'steps': [{'amount': '100.00'}], 'revision': 0,
    }, lambda: None)
    screen.editor.state = {'can_edit': True}
    screen.last_change = 0
    screen.ticking = screen.submitting = False
    screen.update_status = lambda: None

    async def guarded(work, **kwargs):
        await work()

    screen.guarded = guarded
    screen.changed()
    return screen, clock, calls, hooks


def test_burst_is_coalesced_and_saved_before_one_second(monkeypatch):
    screen, clock, calls, _ = setup_screen(monkeypatch)

    async def run():
        for i in range(3):
            clock.now += 0.2
            screen.editor.steps[0]['amount'] = str(200 + i)
            screen.changed()
            await screen.tick()
        assert calls == []
        clock.now += 0.41
        await screen.tick()
        assert [kind for kind, _ in calls] == ['preview', 'save']
        assert calls[-1][1]['steps'][0]['amount'] == '202'
        assert not screen.editor.dirty
        await screen.tick()
        assert len(calls) == 2

    asyncio.run(run())


def test_slow_preview_saves_in_same_tick(monkeypatch):
    screen, clock, calls, hooks = setup_screen(monkeypatch)

    async def preview():
        clock.now += 0.8

    hooks['preview'] = preview
    clock.now += 0.41
    asyncio.run(screen.tick())
    assert [kind for kind, _ in calls] == ['preview', 'save']
    assert not screen.editor.dirty


def test_edit_during_preview_waits_for_new_preview_and_debounce(monkeypatch):
    screen, clock, calls, hooks = setup_screen(monkeypatch)

    async def preview():
        clock.now += 0.5
        screen.editor.steps[0]['amount'] = '300.00'
        screen.changed()
        await screen.tick()  # A concurrent timer must not start a second request.

    async def run():
        hooks['preview'] = preview
        clock.now += 0.41
        await screen.tick()
        assert [kind for kind, _ in calls] == ['preview']
        assert not screen.editor.can_submit
        hooks.clear()
        await screen.tick()
        assert len(calls) == 1
        clock.now += 0.41
        await screen.tick()
        assert [kind for kind, _ in calls] == ['preview', 'preview', 'save']
        assert calls[-1][1]['steps'][0]['amount'] == '300.00'

    asyncio.run(run())


def test_edit_during_save_is_retained_for_next_serialized_save(monkeypatch):
    screen, clock, calls, hooks = setup_screen(monkeypatch)

    async def save():
        clock.now += 0.1
        screen.editor.steps[0]['amount'] = '400.00'
        screen.changed()
        await screen.tick()

    async def run():
        hooks['save'] = save
        clock.now += 0.41
        await screen.tick()
        assert screen.editor.dirty
        assert screen.editor.steps[0]['amount'] == '400.00'
        assert screen.editor.record['revision'] == 1
        hooks.clear()
        clock.now += 0.41
        await screen.tick()
        writes = [body for kind, body in calls if kind == 'save']
        assert [body['expected_revision'] for body in writes] == [0, 1]
        assert [body['steps'][0]['amount'] for body in writes] == ['100.00', '400.00']
        assert not screen.editor.dirty

    asyncio.run(run())


@pytest.mark.parametrize('blocked', ['submitting', 'conflict', 'closed'])
def test_autosave_does_not_write_when_blocked(monkeypatch, blocked):
    screen, clock, calls, _ = setup_screen(monkeypatch)
    if blocked == 'submitting':
        screen.submitting = True
    elif blocked == 'conflict':
        screen.editor.conflict = True
    else:
        screen.editor.state['can_edit'] = False
    clock.now += 0.41
    asyncio.run(screen.tick())
    assert not any(kind == 'save' for kind, _ in calls)
