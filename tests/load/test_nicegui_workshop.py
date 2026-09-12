"""50 independent UI controllers against the real API and disposable PostgreSQL.

Run explicitly: python -m pytest tests/load -q -s
This is not a browser-rendering or reverse-proxy benchmark.
"""

import asyncio
import statistics
import time
from copy import deepcopy
from uuid import uuid4

import httpx

from src.aml_workshop_simulator.ui.nicegui.client import APIClient
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor


def test_fifty_participants_poll_save_submit_score(api, active_round, admin, chain):
    async def run():
        client = APIClient("http://test/api/v1", transport=httpx.ASGITransport(api.app))
        admission = asyncio.Semaphore(5)

        async def participant(index):
            async with admission:
                email = f"load-{uuid4().hex}@example.com"
                await client.request(
                    "POST",
                    "auth/register",
                    body={
                        "email": email,
                        "display_name": f"Нагрузка {index}",
                        "password": "load-test-password",
                    },
                )
                session = await client.request(
                    "POST",
                    "auth/login",
                    body={
                        "email": email,
                        "password": "load-test-password",
                        "audience": "play",
                    },
                )
            return GameEditor(client, session["session_id"], {}, lambda: None)

        try:
            editors = await asyncio.gather(*(participant(i) for i in range(50)))
            latencies = []

            async def poll(editor):
                started = time.monotonic()
                await editor.poll()
                latencies.append(time.monotonic() - started)

            for _ in range(3):
                await asyncio.gather(*(poll(e) for e in editors))
            sample = chain()

            async def play(editor):
                editor.record["steps"] = deepcopy(sample)
                editor.changed()
                await editor.evaluate()
                assert editor.can_submit
                await editor.write()
                await editor.write(submit=True)

            await asyncio.gather(*(play(e) for e in editors))
            summary = await client.request(
                "POST",
                f"admin/rounds/{active_round}/score",
                session_id=admin["X-Session-ID"],
                timeout=120,
            )
            assert summary["scored_count"] == 50
            await asyncio.gather(*(poll(e) for e in editors))
            assert all(
                e.state["result"] is not None and not e.editable for e in editors
            )
            print(
                f"50 controllers: {len(latencies)} state reads, median={statistics.median(latencies) * 1000:.0f}ms, p95={sorted(latencies)[int(len(latencies) * 0.95) - 1] * 1000:.0f}ms; scoring={summary['duration_ms']}ms"
            )
        finally:
            await client.close()

    asyncio.run(run())
