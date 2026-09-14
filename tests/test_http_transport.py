"""Tests for the Streamable HTTP transport."""

import pytest

from irail_mcp.server import _build_parser, build_http_app


def test_cli_defaults_to_stdio():
    args = _build_parser().parse_args([])
    assert args.transport == "stdio"


def test_cli_http_flags():
    args = _build_parser().parse_args(
        ["--transport", "http", "--host", "0.0.0.0", "--port", "9000",
         "--path", "irail", "--stateless", "--allowed-host", "localhost:9000"]
    )
    assert args.transport == "http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.path == "irail"
    assert args.stateless is True
    assert args.allowed_hosts == ["localhost:9000"]


@pytest.mark.asyncio
async def test_http_app_serves_health_and_mcp():
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    http_app = build_http_app(path="/mcp")

    # Run the app in-process on a free port with uvicorn.
    import asyncio
    import socket

    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config = uvicorn.Config(http_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)

        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient() as client:
            health = await client.get(f"{base}/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

        for url in (f"{base}/mcp", f"{base}/mcp/"):
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    assert "search_stations" in names
                    result = await session.call_tool("search_stations", {"query": "Gent"})
                    assert "Gent-Sint-Pieters" in result.content[0].text
    finally:
        server.should_exit = True
        await task
