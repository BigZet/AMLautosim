"""Participant editor state and serialized commands, independent of widgets."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .client import APIClient, APIError


class GameEditor:
    def __init__(self, api: APIClient, token: str, record: dict, persist):
        self.api, self.token = api, token
        self.record, self.persist = record, persist
        self.state = {}
        self.cards = []
        self.preview = None
        self.preview_version = -1
        self.version = 0
        self.lock = asyncio.Lock()
        self.conflict = False
        self.error = None
        self.generation = 0
        self.render_revision = 0
        self.poll_sequence = 0
        self.write_sequence = 0

    @property
    def steps(self):
        return self.record.setdefault("steps", [])

    @property
    def dirty(self):
        return self.record.get("dirty", False)

    @property
    def editable(self):
        return self.state.get("can_edit", False)

    @property
    def can_submit(self):
        return (
            self.editable
            and not self.conflict
            and not self.record.get("pending")
            and self.preview_version == self.version
            and bool(self.preview and self.preview["can_submit"])
        )

    def changed(self):
        config = (self.state.get("round") or {}).get("game_config", {})
        if config.get("schema_version") == 8:
            from src.aml_workshop_simulator.domain.operation_timeline import (
                canonical_intervals,
            )

            for step, interval in zip(self.steps, canonical_intervals(self.steps)):
                step["interval_minutes"] = interval
        self.version += 1
        self.record["dirty"] = True
        self.error = None
        self.persist()

    def transport_valid(self):
        try:
            return all(
                Decimal(step["amount"]).is_finite()
                and Decimal(step["amount"]) > 0
                and Decimal(step["amount"]).as_tuple().exponent >= -2
                for step in self.steps
            )
        except (InvalidOperation, KeyError, TypeError):
            return False

    async def poll(self):
        before = deepcopy(self.record)
        self.poll_sequence += 1
        sequence = self.poll_sequence
        write_sequence = self.write_sequence
        state = await self.api.request(
            "GET", "rounds/current/state", session_id=self.token
        )
        if sequence != self.poll_sequence or write_sequence != self.write_sequence:
            return self.state
        round_data = state.get("round")
        key = [round_data["id"], round_data["config_version"]] if round_data else None
        if key != self.record.get("key"):
            self.generation += 1
            self.record.clear()
            self.record.update(key=key, steps=[], revision=0, dirty=False)
            self.cards = (
                await self.api.request("GET", f"rounds/{key[0]}/cards") if key else []
            )
            self.conflict = False
            self.preview = None
            self.preview_version = -1
            self.version += 1
            self.render_revision += 1
        elif key and not self.cards:
            self.cards = await self.api.request("GET", f"rounds/{key[0]}/cards")
        self.state = state
        scenario = state.get("scenario")
        if not self.lock.locked():
            server_revision = scenario["revision"] if scenario else 0
            if self.dirty or self.record.get("pending"):
                if server_revision != self.record.get("revision", 0):
                    # Pending writes may have succeeded before their response was lost.
                    # Resolve them by replaying that exact command, never invent a UUID.
                    self.conflict = not bool(self.record.get("pending"))
            else:
                new_steps = scenario["steps"] if scenario else []
                if new_steps != self.steps:
                    self.record["steps"] = deepcopy(new_steps)
                    self.version += 1
                    self.render_revision += 1
                self.record["revision"] = server_revision
        if self.record != before:
            self.persist()
        return state

    async def evaluate(self):
        if not self.editable or not self.transport_valid():
            return
        version, generation = self.version, self.generation
        try:
            result = await self.api.request(
                "POST",
                f"rounds/{self.record['key'][0]}/scenario/preview",
                session_id=self.token,
                body={"steps": deepcopy(self.steps)},
            )
        except APIError as exc:
            if version == self.version and generation == self.generation:
                self.preview = None
                self.error = exc
            return
        if version == self.version and generation == self.generation:
            self.preview, self.preview_version = result, version
            self.error = None

    async def write(self, submit=False):
        async with self.lock:
            self.write_sequence += 1
            pending = self.record.get("pending")
            if not pending:
                if not self.editable or self.conflict or not self.transport_valid():
                    return False
                if not submit and not self.dirty:
                    return True
                pending = {
                    "method": "POST" if submit else "PUT",
                    "path": f"rounds/{self.record['key'][0]}/scenario"
                    + ("/submit" if submit else ""),
                    "body": {
                        "steps": deepcopy(self.steps),
                        "expected_revision": self.record.get("revision", 0),
                        "client_mutation_id": str(uuid4()),
                    },
                }
                self.record["pending"] = pending
                self.persist()
            generation = self.generation
            try:
                result = await self.api.request(
                    pending["method"],
                    pending["path"],
                    session_id=self.token,
                    body=pending["body"],
                )
            except APIError as exc:
                if generation != self.generation:
                    return False
                self.error = exc
                if exc.status and exc.status < 500:
                    self.record.pop("pending", None)
                    self.conflict = exc.code in {
                        "scenario_revision_conflict",
                        "mutation_id_reused",
                    }
                    self.persist()
                raise
            if generation != self.generation:
                return False
            self.write_sequence += 1
            self.record.pop("pending", None)
            self.record["revision"] = result["revision"]
            # Edits made while awaiting the request are retained for the next save.
            if self.steps == pending["body"]["steps"]:
                self.record["steps"] = deepcopy(result["steps"])
                self.record["dirty"] = False
            if result["status"] != "editing":
                self.record["steps"] = deepcopy(result["steps"])
                self.record["dirty"] = False
                self.state.update(scenario=result, can_edit=False, can_submit=False)
            self.error = None
            self.persist()
            return True

    def accept_server(self, *, keep_local=False):
        scenario = self.state.get("scenario")
        self.record.pop("pending", None)
        self.record["revision"] = scenario["revision"] if scenario else 0
        if not keep_local:
            self.record["steps"] = deepcopy(scenario["steps"]) if scenario else []
        self.conflict = False
        self.record["dirty"] = keep_local
        self.version += 1
        self.persist()
