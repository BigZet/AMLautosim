"""HTTP/cookie/WebSocket smoke check of a running NiceGUI UI."""

import argparse
import asyncio
import re
from uuid import uuid4

import httpx
import socketio


async def main(origin):
    origin = origin.rstrip("/")
    async with httpx.AsyncClient() as client:
        response = await client.get(origin + "/play/login")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert (await client.get(origin + "/api/v1/auth/session")).status_code == 404
        client_id = re.search(r"'client_id': '([0-9a-f-]+)'", response.text).group(1)
        socket = socketio.AsyncClient()
        try:
            await socket.connect(
                origin,
                socketio_path="_nicegui_ws/socket.io",
                transports=["websocket"],
                headers={
                    "Cookie": "; ".join(f"{k}={v}" for k, v in client.cookies.items())
                },
            )
            accepted = await socket.call(
                "handshake",
                {
                    "client_id": client_id,
                    "tab_id": str(uuid4()),
                    "document_id": str(uuid4()),
                },
                timeout=10,
            )
            assert accepted is True
            print(
                "NiceGUI: HTTP page 200, API unavailable on UI port (404), HttpOnly/SameSite cookie, WebSocket handshake accepted."
            )
        finally:
            if socket.connected:
                await socket.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    asyncio.run(main(parser.parse_args().url))
