"""Real HTTP/cookie/Socket.IO clients; only run against a disposable workshop."""

import argparse
import asyncio
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import time
from uuid import uuid4

import httpx
import psutil
import socketio


class UIClient:
    def __init__(self, origin):
        self.origin = origin.rstrip("/")
        self.http = httpx.AsyncClient(follow_redirects=True, timeout=30)
        self.socket = socketio.AsyncClient(reconnection=False)
        self.elements = {}
        self.navigation = asyncio.Queue()
        self.updates = asyncio.Event()
        self.tab = str(uuid4())
        self.received = 0
        self.sent = 0
        self.socket.eio.on("message", self.on_message)
        self.original_send = self.socket.eio.send
        self.socket.eio.send = self.send_message
        self.update_count = 0
        self.socket.on("update", self.on_update)
        self.socket.on("open", self.on_open)

    async def on_update(self, data):
        self.update_count += 1
        for key, value in data.items():
            if key == "_id":
                continue
            if value is None:
                self.elements.pop(str(key), None)
            else:
                self.elements[str(key)] = value
        self.updates.set()
        await self.socket.emit(
            "ack",
            {"client_id": self.client_id, "next_message_id": data.get("_id", 0) + 1},
        )

    async def on_message(self, data):
        self.received += len(data if isinstance(data, bytes) else data.encode()) + 1
        await self.socket._handle_eio_message(data)

    async def send_message(self, data):
        self.sent += len(data if isinstance(data, bytes) else data.encode()) + 1
        await self.original_send(data)

    async def on_open(self, data):
        await self.navigation.put(data["path"])

    async def open(self, path):
        if self.socket.connected:
            await self.socket.disconnect()
        response = await self.http.get(self.origin + path)
        response.raise_for_status()
        self.elements = json.loads(
            re.search(r"parseElements\(String.raw`(.*?)`\)", response.text, re.S).group(
                1
            )
        )
        self.client_id = re.search(r"'client_id': '([0-9a-f-]+)'", response.text).group(
            1
        )
        await self.socket.connect(
            self.origin,
            socketio_path="_nicegui_ws/socket.io",
            transports=["websocket"],
            headers={
                "Cookie": "; ".join(f"{k}={v}" for k, v in self.http.cookies.items())
            },
        )
        accepted = await self.socket.call(
            "handshake",
            {
                "client_id": self.client_id,
                "tab_id": self.tab,
                "document_id": str(uuid4()),
            },
            timeout=30,
        )
        if accepted is not True:
            raise RuntimeError("handshake_rejected")

    def find(self, *, label=None, text=None, event=None):
        for key, element in self.elements.items():
            if not isinstance(element, dict):
                continue
            if label is not None and element.get("props", {}).get("label") != label:
                continue
            if (
                text is not None
                and element.get("text", element.get("props", {}).get("label")) != text
            ):
                continue
            if event and not any(e["type"] == event for e in element.get("events", [])):
                continue
            return key, element
        return None

    async def wait(self, predicate, timeout=15):
        async with asyncio.timeout(timeout):
            while not predicate():
                self.updates.clear()
                # Recheck after clearing so an update cannot be lost.
                if not predicate():
                    await self.updates.wait()

    async def emit(self, found, event, value=None):
        key, element = found
        listener = next(e for e in element["events"] if e["type"] == event)
        await self.socket.emit(
            "event",
            {
                "id": int(key),
                "client_id": self.client_id,
                "listener_id": listener["listener_id"],
                "args": [json.dumps(value)],
            },
        )

    async def login(self, account):
        await self.open("/play/login")
        await self.emit(
            self.find(label="Email", event="update:value"),
            "update:value",
            account["email"],
        )
        await self.emit(
            self.find(label="Пароль", event="update:value"),
            "update:value",
            account["password"],
        )
        await self.emit(self.find(text="Войти", event="click"), "click")
        path = await asyncio.wait_for(self.navigation.get(), 30)
        await self.open(path)
        await self.wait(
            lambda: self.find(text="Входящий перевод", event="click"), timeout=30
        )

    async def prepare(self, count=1):
        def fields():
            return sum(
                isinstance(e, dict) and e.get("props", {}).get("label") == "Сумма"
                for e in self.elements.values()
            )

        while fields() < count:
            before = fields()
            title = ("Входящий перевод", "Перевод по карте", "Наличные", "Покупка")[
                before % 4
            ]
            opener = self.find(text="Добавить операцию", event="click")
            if opener:
                await self.emit(opener, "click")
            await self.emit(self.find(text=title, event="click"), "click")
            await self.wait(lambda: fields() > before)
            await self.wait(lambda: self.find(text="Сохранено"))
        await self.wait(lambda: self.find(text="Сохранено"))

    async def edit(self, amount):
        previous = self.update_count
        field = self.find(label="Сумма", event="update:modelValue")
        props = field[1]["props"]
        value = min(float(props["max"]), float(props["min"]) + amount % 100 + 1)
        await self.emit(field, "update:modelValue", value)
        await self.wait(
            lambda: (
                self.update_count > previous
                and (
                    self.find(text="Есть несохранённые изменения")
                    or self.find(text="Сохраняем…")
                )
            )
        )
        await self.wait(lambda: self.find(text="Сохранено"))

    async def reorder(self):
        previous = self.update_count
        found = next(
            (k, e)
            for k, e in self.elements.items()
            if isinstance(e, dict)
            and e.get("props", {}).get("icon") == "arrow_upward"
            and not e.get("props", {}).get("disable", False)
        )
        await self.emit(found, "click")
        await self.wait(
            lambda: (
                self.update_count > previous
                and (
                    self.find(text="Есть несохранённые изменения")
                    or self.find(text="Сохраняем…")
                )
            )
        )
        await self.wait(lambda: self.find(text="Сохранено"))

    async def close(self):
        if self.socket.connected:
            await self.socket.disconnect()
        await self.http.aclose()


async def run(args):
    accounts = json.loads(Path(args.accounts).read_text(encoding="utf-8"))[: args.users]
    if len(accounts) != args.users:
        raise ValueError("not_enough_precreated_accounts")
    users = [UIClient(args.url) for _ in accounts]
    results, samples = [], []
    process = psutil.Process()
    start_net = psutil.net_io_counters()
    begin = time.time()

    async def measured(kind, index, action):
        started = time.monotonic()
        previous_bytes = users[index].received + users[index].sent if index >= 0 else 0
        failure = None
        try:
            await asyncio.wait_for(action(), 40)
        except Exception as exc:
            failure = type(exc).__name__  # no credentials or server response in report
        results.append(
            {
                "kind": kind,
                "user": index,
                "at": time.time(),
                "seconds": time.monotonic() - started,
                "failure": failure,
                "ws_message_bytes": users[index].received
                + users[index].sent
                - previous_bytes
                if index >= 0
                else 0,
            }
        )
        return failure is None

    stop = asyncio.Event()

    async def sample():
        async with httpx.AsyncClient(timeout=5) as client:
            while not stop.is_set():
                data = {
                    "at": time.time(),
                    "generator_cpu_percent": process.cpu_percent(),
                    "generator_rss_bytes": process.memory_info().rss,
                }
                for name, origin in [("api", args.api), ("ui", args.ui)]:
                    try:
                        response = await client.get(
                            origin + "/internal/metrics",
                            headers={
                                "Authorization": "Bearer " + os.environ["METRICS_TOKEN"]
                            },
                        )
                        response.raise_for_status()
                        data[name] = response.json()
                    except Exception as exc:
                        data[name] = {"failure": type(exc).__name__}
                samples.append(data)
                try:
                    await asyncio.wait_for(stop.wait(), 2)
                except TimeoutError:
                    pass

    sampler = asyncio.create_task(sample())
    admission = asyncio.Semaphore(args.login_concurrency)

    async def login(index, user, account):
        async with admission:
            return await measured("login", index, lambda: user.login(account))

    try:
        ready = await asyncio.gather(
            *(login(i, u, a) for i, (u, a) in enumerate(zip(users, accounts)))
        )
        prepared = await asyncio.gather(
            *(
                measured(
                    "prepare",
                    i,
                    lambda u=u: u.prepare(
                        max(0, args.steps - 1) if args.structural else args.steps
                    ),
                )
                if ready[i]
                else asyncio.sleep(0, result=False)
                for i, u in enumerate(users)
            )
        )
        if args.structural:
            for i, user in enumerate(users):
                if prepared[i]:
                    prepared[i] = await measured(
                        "add", i, lambda u=user: u.prepare(args.steps)
                    )
                    if args.steps > 1 and prepared[i]:
                        prepared[i] = await measured("reorder", i, user.reorder)
        deadline = time.monotonic() + args.seconds

        async def exercise(i, user):
            iteration = 0
            while time.monotonic() < deadline and prepared[i]:
                iteration += 1
                await measured("edit", i, lambda: user.edit(20000 + iteration % 1000))
                if args.reconnect_every and iteration % args.reconnect_every == 0:
                    await measured("reconnect", i, lambda: user.open("/play"))
                    await measured("prepare", i, lambda: user.prepare(args.steps))
                await asyncio.sleep(args.interval)

        async def canary():
            async with httpx.AsyncClient(timeout=10) as client:
                while time.monotonic() < deadline:

                    async def probe():
                        response = await client.get(args.url + "/health/live")
                        response.raise_for_status()

                    await measured("canary", -1, probe)
                    await asyncio.sleep(1)

        await asyncio.gather(*(exercise(i, u) for i, u in enumerate(users)), canary())
    finally:
        stop.set()
        await sampler
        await asyncio.gather(*(u.close() for u in users), return_exceptions=True)
        net = psutil.net_io_counters()
        report = {
            "users": args.users,
            "started": begin,
            "finished": time.time(),
            "platform": platform.platform(),
            "cpu_count": psutil.cpu_count(),
            "ram_bytes": psutil.virtual_memory().total,
            "versions": {
                name: importlib.metadata.version(name)
                for name in ["nicegui", "python-socketio", "httpx", "psutil"]
            },
            "network_bytes_sent": net.bytes_sent - start_net.bytes_sent,
            "network_bytes_received": net.bytes_recv - start_net.bytes_recv,
            "ws_message_payload_bytes": sum(u.received + u.sent for u in users),
            "steps": args.steps,
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "actions": results,
            "samples": samples,
            "note": "Socket.IO UI events through proxy; no DOM/render-time claims. Network counters are host-wide.",
        }
        Path(args.output).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    failed = sum(r["failure"] is not None for r in results)
    print(
        json.dumps({"actions": len(results), "failed": failed, "output": args.output})
    )
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Disposable nginx UI origin")
    parser.add_argument("--api", required=True, help="Private API metrics origin")
    parser.add_argument("--ui", required=True, help="Private UI metrics origin")
    parser.add_argument(
        "--accounts", required=True, help="Private JSON file of precreated accounts"
    )
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--structural", action="store_true")
    parser.add_argument("--steps", type=int, default=1)
    parser.add_argument("--login-concurrency", type=int, default=5)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--interval", type=float, default=3)
    parser.add_argument("--reconnect-every", type=int, default=0)
    parser.add_argument("--output", required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
