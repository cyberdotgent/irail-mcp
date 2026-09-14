# iRail MCP Server

> **Disclaimer:** This project was vibe coded and is **not affiliated with or supported by [iRail vzw](https://hello.irail.be)**. Train data may be inaccurate or outdated. Always verify with official sources ([belgiantrain.be](https://www.belgiantrain.be) or the NMBS/SNCB app) before making travel decisions.

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that provides Belgian railway travel information via the [iRail API](https://api.irail.be).

## Features

- **Search Stations** - Find Belgian railway stations by name
- **Live Departures/Arrivals** - Real-time departure and arrival boards
- **Find Connections** - Route planning between stations with transfers
- **Train Information** - Detailed stops, delays, and platforms for a specific train
- **Network Disturbances** - Current disruptions and planned maintenance

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/HansF/irail-mcp.git
cd irail-mcp
uv venv && source .venv/bin/activate
uv pip install -e .
```

## Usage with Claude Code

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "irail": {
      "command": "uvx",
      "args": ["irail-mcp"]
    }
  }
}
```

Then ask Claude things like:
- "What trains leave Brussels Central in the next hour?"
- "Find a route from Antwerp to Bruges at 2:30 PM tomorrow"
- "Are there any disruptions on the Belgian rail network?"
- "Show me details for train IC2240"

## Usage over Streamable HTTP (Open WebUI, remote clients)

The server can also be exposed over the MCP [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) transport, which is what Open WebUI and most web-based MCP clients expect:

```bash
uvx irail-mcp --transport http --host 0.0.0.0 --port 8000
```

The MCP endpoint is then available at `http://<host>:8000/mcp` and a simple health check at `http://<host>:8000/health`.

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--transport` | `stdio` | `stdio` or `http` |
| `--host` | `127.0.0.1` | Bind address (use `0.0.0.0` inside Docker) |
| `--port` | `8000` | Listen port |
| `--path` | `/mcp` | Path of the MCP endpoint |
| `--stateless` | off | No server-side sessions; each request is independent |
| `--json-response` | off | Return plain JSON instead of SSE streams |
| `--allowed-host HOST` | unset | Enable DNS-rebinding protection for the given `Host` values (repeatable) |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Open WebUI

In Open WebUI go to **Admin Panel → Settings → External Tools** (or **Settings → Tools** for a user-level connection), add a new connection with:

- **Type:** MCP (Streamable HTTP)
- **URL:** `http://<host>:8000/mcp`

Open WebUI running in Docker cannot reach `127.0.0.1` on the host, so start the server with `--host 0.0.0.0` and use the host's LAN address, or `host.docker.internal` where supported. When exposing the server beyond localhost, put it behind a reverse proxy with authentication; the server itself does not authenticate requests.

### Docker

A prebuilt multi-arch image (amd64/arm64) is published to GitHub Container Registry on every push to `main` (`latest`) and on version tags:

```bash
docker run -d --name irail-mcp -p 8000:8000 ghcr.io/cyberdotgent/irail-mcp:latest
```

Or build it yourself from the included multi-stage `Dockerfile`. The image runs as a non-root user, exposes the HTTP transport on port 8000 and has a built-in health check.

```bash
docker build -t irail-mcp .
docker run -d --name irail-mcp -p 8000:8000 irail-mcp
```

Or with Compose:

```bash
docker compose up -d
```

The MCP endpoint is `http://localhost:8000/mcp`. Extra arguments are passed straight to the server, so the transport can be changed at run time:

```bash
# stdio mode (e.g. for a desktop MCP client that launches Docker)
docker run -i --rm irail-mcp --transport stdio

# HTTP on a custom path with DNS-rebinding protection
docker run -p 8000:8000 irail-mcp --transport http --host 0.0.0.0 --path /irail --allowed-host irail.example.com
```

When Open WebUI runs in another container, put both on the same Docker network and use `http://irail-mcp:8000/mcp` as the URL.

### Embedding in your own ASGI app

```python
from irail_mcp.server import build_http_app

app = build_http_app(path="/mcp")  # a Starlette app; serve with uvicorn/hypercorn
```

## Tools

### search_stations
Search for stations by name.
- `query` (required) - Station name or partial name
- `lang` (optional) - Language: en, nl, fr, de, it

### get_liveboard
Real-time departures or arrivals from a station.
- `station` (required) - Station name
- `date` (optional) - YYYY-MM-DD, "today", "tomorrow", "+2 days"
- `time` (optional) - HH:MM (24h)
- `arrival` (optional) - Show arrivals instead of departures
- `lang` (optional)

### find_connections
Find routes between two stations.
- `from_station` (required) - Departure station
- `to_station` (required) - Destination station
- `date`, `time`, `lang` (optional)
- `arrival_time` (optional) - If true, time is desired arrival time

### get_train_info
Detailed information about a specific train.
- `train_id` (required) - e.g. "IC1234" or "BE.NMBS.IC1234"
- `date`, `lang` (optional)

### get_disturbances
Current network disruptions and planned works.
- `lang` (optional)

## Running Tests

```bash
uv pip install -e ".[dev]"
python -m pytest tests/ -v
```

## API Compliance

- Rate limited to 3 requests/second per iRail guidelines
- Proper User-Agent header set
- 30-second timeout for slow responses

## License

MIT

## References

- [iRail API](https://api.irail.be) - [Documentation](https://docs.irail.be)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [NMBS/SNCB](https://www.belgiantrain.be)
