"""iRail MCP Server for Belgian railway data."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent

from .irail_client import iRailClient
from .station_search import search_stations as offline_search_stations

logger = logging.getLogger(__name__)

# Create MCP server
app = Server("irail-mcp")


def parse_datetime(date_str: str | None, time_str: str | None) -> datetime:
    """Parse date and time strings into a datetime object.

    Supports various formats:
    - Date: "2024-02-07", "07/02/2024", "today", "tomorrow", "+2 days"
    - Time: "14:30", "2:30 PM", "14:30:00"
    """
    if date_str is None:
        target_date = datetime.now()
    elif date_str.lower() == "today":
        target_date = datetime.now()
    elif date_str.lower() == "tomorrow":
        target_date = datetime.now() + timedelta(days=1)
    elif date_str.startswith("+"):
        # "+2 days" format
        parts = date_str.split()
        days = int(parts[0][1:])
        target_date = datetime.now() + timedelta(days=days)
    else:
        # Try parsing as date
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"]:
            try:
                target_date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        else:
            target_date = datetime.now()

    if time_str is None:
        return target_date

    # Parse time
    for fmt in ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"]:
        try:
            time_obj = datetime.strptime(time_str, fmt)
            return target_date.replace(hour=time_obj.hour, minute=time_obj.minute)
        except ValueError:
            continue

    return target_date


def format_departure(dep: dict) -> str:
    """Format a departure record for display."""
    time_str = datetime.fromtimestamp(int(dep.get("time", 0))).strftime("%H:%M")
    delay = int(dep.get("delay", 0)) // 60
    delay_str = f" (+{delay}min)" if delay else ""
    platform = dep.get("platform", "?")
    canceled_str = " [CANCELED]" if dep.get("canceled") == "1" else ""
    station_info = dep.get("stationinfo", dep.get("station", {}))
    if isinstance(station_info, dict):
        destination = station_info.get("name", "Unknown")
    else:
        destination = str(station_info) if station_info else "Unknown"
    vehicle = dep.get("vehicle", "")

    return (
        f"{time_str}{delay_str} to {destination} "
        f"(Platform {platform}, {vehicle}){canceled_str}"
    )


def format_connection(conn: dict) -> str:
    """Format a connection record for display."""
    dep = conn.get("departure", {})
    arr = conn.get("arrival", {})
    dept = datetime.fromtimestamp(int(dep.get("time", 0))).strftime("%H:%M")
    arrv = datetime.fromtimestamp(int(arr.get("time", 0))).strftime("%H:%M")
    duration = int(conn.get("duration", 0)) // 60  # convert to minutes
    transfers = int(conn.get("vias", {}).get("number", 0))
    transfer_str = f"{transfers} transfer(s)" if transfers else "Direct"

    dep_platform = dep.get("platform", "?")
    dep_delay = int(dep.get("delay", 0)) // 60
    delay_str = f" (+{dep_delay}min)" if dep_delay else ""
    vehicle = dep.get("vehicle", "")

    return (
        f"{dept}{delay_str}→{arrv} ({duration}min, {transfer_str}, Platform {dep_platform}, {vehicle})"
    )


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="search_stations",
            description="Search for railway stations in Belgium by name",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Station name or partial name to search for (e.g., 'Brussels', 'Antwerp')",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language code (en, nl, fr, de, it)",
                        "default": "en",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_liveboard",
            description="Get real-time departures or arrivals from a station",
            inputSchema={
                "type": "object",
                "properties": {
                    "station": {
                        "type": "string",
                        "description": "Station name or URI (e.g., 'Brussels Central', 'Gent-Sint-Pieters')",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in format YYYY-MM-DD or relative (today, tomorrow, +2 days)",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in 24-hour format (e.g., '14:30')",
                    },
                    "arrival": {
                        "type": "boolean",
                        "description": "If true, show arrivals; if false, show departures (default: false)",
                        "default": False,
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language code (en, nl, fr, de, it)",
                        "default": "en",
                    },
                },
                "required": ["station"],
            },
        ),
        Tool(
            name="find_connections",
            description="Find routes between two stations with connection details",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_station": {
                        "type": "string",
                        "description": "Departure station name (e.g., 'Brussels')",
                    },
                    "to_station": {
                        "type": "string",
                        "description": "Destination station name (e.g., 'Antwerp')",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in format YYYY-MM-DD or relative (today, tomorrow, +2 days)",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in 24-hour format (e.g., '14:30')",
                    },
                    "arrival_time": {
                        "type": "boolean",
                        "description": "If true, time is arrival time; if false, time is departure time (default: false)",
                        "default": False,
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language code (en, nl, fr, de, it)",
                        "default": "en",
                    },
                },
                "required": ["from_station", "to_station"],
            },
        ),
        Tool(
            name="get_train_info",
            description="Get detailed information about a specific train including all stops and current delays",
            inputSchema={
                "type": "object",
                "properties": {
                    "train_id": {
                        "type": "string",
                        "description": "Train ID from liveboard results (e.g., 'IC1234' or 'BE.NMBS.IC1234')",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in format YYYY-MM-DD (default: today)",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language code (en, nl, fr, de, it)",
                        "default": "en",
                    },
                },
                "required": ["train_id"],
            },
        ),
        Tool(
            name="get_disturbances",
            description="Get current network disruptions and planned maintenance works",
            inputSchema={
                "type": "object",
                "properties": {
                    "lang": {
                        "type": "string",
                        "description": "Language code (en, nl, fr, de, it)",
                        "default": "en",
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "search_stations":
            result = _search_stations(arguments)
            return [TextContent(type="text", text=result)]

        async with iRailClient() as client:
            if name == "get_liveboard":
                result = await _get_liveboard(client, arguments)
            elif name == "find_connections":
                result = await _find_connections(client, arguments)
            elif name == "get_train_info":
                result = await _get_train_info(client, arguments)
            elif name == "get_disturbances":
                result = await _get_disturbances(client, arguments)
            else:
                result = f"Unknown tool: {name}"

        return [TextContent(type="text", text=result)]
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=error_msg)]


def _search_stations(arguments: dict) -> str:
    """Search for stations using bundled offline data."""
    query = arguments.get("query", "")

    if not query:
        return "Error: 'query' parameter is required"

    stations = offline_search_stations(query)

    if not stations:
        return f"No stations found matching '{query}'"

    lines = [f"Found {len(stations)} station(s) matching '{query}':\n"]
    for station in stations[:10]:  # Limit to 10 results
        name = station.get("name", "Unknown")
        alt_names = [
            station.get(f"alternative_{lang}", "")
            for lang in ("fr", "nl", "de", "en")
        ]
        alt_str = ", ".join(n for n in alt_names if n)
        lat = station.get("latitude", "?")
        lon = station.get("longitude", "?")
        display_alt = f" ({alt_str})" if alt_str else ""
        lines.append(
            f"• {name}{display_alt} - Coordinates: {lat}, {lon}"
        )

    if len(stations) > 10:
        lines.append(f"\n... and {len(stations) - 10} more")

    return "\n".join(lines)


async def _get_liveboard(client: iRailClient, arguments: dict) -> str:
    """Get liveboard data."""
    station = arguments.get("station", "")
    date_str = arguments.get("date")
    time_str = arguments.get("time")
    arrival = arguments.get("arrival", False)
    lang = arguments.get("lang", "en")

    if not station:
        return "Error: 'station' parameter is required"

    try:
        dt = parse_datetime(date_str, time_str)
        result = await client.get_liveboard(station, dt, arrival=arrival, lang=lang)
    except ValueError as e:
        return f"Error fetching liveboard: {str(e)}"

    board_type = "Arrivals" if arrival else "Departures"
    station_name = result.get("stationinfo", {}).get("name", result.get("station", station))
    dt_str = dt.strftime("%Y-%m-%d %H:%M")

    lines = [f"{board_type} at {station_name} on {dt_str}:\n"]

    if arrival:
        departures = result.get("arrivals", {}).get("arrival", [])
    else:
        departures = result.get("departures", {}).get("departure", [])
    if not isinstance(departures, list):
        departures = [departures] if departures else []

    if not departures:
        lines.append(f"No {board_type.lower()} found.")
    else:
        for dep in departures[:15]:  # Limit to 15
            lines.append(f"  {format_departure(dep)}")

        if len(departures) > 15:
            lines.append(f"\n  ... and {len(departures) - 15} more")

    return "\n".join(lines)


async def _find_connections(client: iRailClient, arguments: dict) -> str:
    """Find connections between stations."""
    from_station = arguments.get("from_station", "")
    to_station = arguments.get("to_station", "")
    date_str = arguments.get("date")
    time_str = arguments.get("time")
    arrival_time = arguments.get("arrival_time", False)
    lang = arguments.get("lang", "en")

    if not from_station or not to_station:
        return "Error: 'from_station' and 'to_station' parameters are required"

    try:
        dt = parse_datetime(date_str, time_str)
        result = await client.find_connections(
            from_station, to_station, dt, arrival_mode=arrival_time, lang=lang
        )
    except ValueError as e:
        return f"Error finding connections: {str(e)}"

    dt_str = dt.strftime("%Y-%m-%d %H:%M")
    time_mode = "arriving at" if arrival_time else "departing from"

    lines = [
        f"Connections from {from_station} to {to_station} "
        f"{time_mode} {dt_str}:\n"
    ]

    connections = result.get("connection", [])
    if not isinstance(connections, list):
        connections = [connections] if connections else []

    if not connections:
        lines.append("No connections found.")
    else:
        for conn in connections[:10]:  # Limit to 10 connections
            lines.append(f"  {format_connection(conn)}")

        if len(connections) > 10:
            lines.append(f"\n  ... and {len(connections) - 10} more")

    return "\n".join(lines)


async def _get_train_info(client: iRailClient, arguments: dict) -> str:
    """Get train information."""
    train_id = arguments.get("train_id", "")
    date_str = arguments.get("date")
    lang = arguments.get("lang", "en")

    if not train_id:
        return "Error: 'train_id' parameter is required"

    try:
        dt = parse_datetime(date_str, None)
        result = await client.get_vehicle(train_id, dt, lang=lang)
    except ValueError as e:
        return f"Error fetching train info: {str(e)}"

    # vehicle is a string (train ID), vehicleinfo is the object
    vehicle_name = result.get("vehicle", train_id)
    vehicle_info = result.get("vehicleinfo", {})

    dt_str = dt.strftime("%Y-%m-%d")
    lines = [f"Train {vehicle_name} on {dt_str}"]

    stops = result.get("stops", {}).get("stop", [])
    if not isinstance(stops, list):
        stops = [stops] if stops else []

    if stops:
        lines.append(f"\n  Stops ({len(stops)} total):")
        for stop in stops[:20]:  # Limit to 20 stops
            station_name = stop.get("stationinfo", {}).get("name", stop.get("station", "Unknown"))
            scheduled_dep = stop.get("scheduledDepartureTime", stop.get("time", "0"))
            scheduled_arr = stop.get("scheduledArrivalTime", stop.get("time", "0"))
            delay = int(stop.get("departureDelay", stop.get("arrivalDelay", "0"))) // 60
            delay_str = f" (+{delay}min)" if delay else ""
            canceled = " [CANCELED]" if stop.get("departureCanceled") == "1" or stop.get("arrivalCanceled") == "1" else ""
            platform = stop.get("platform", "?")

            arr_time = datetime.fromtimestamp(
                int(scheduled_arr)
            ).strftime("%H:%M") if scheduled_arr != "0" else "--:--"
            dep_time = datetime.fromtimestamp(
                int(scheduled_dep)
            ).strftime("%H:%M") if scheduled_dep != "0" else "--:--"

            lines.append(f"    • {station_name}: {arr_time}→{dep_time}{delay_str} (Pl. {platform}){canceled}")

        if len(stops) > 20:
            lines.append(f"    ... and {len(stops) - 20} more")

    return "\n".join(lines)


async def _get_disturbances(client: iRailClient, arguments: dict) -> str:
    """Get network disturbances."""
    lang = arguments.get("lang", "en")

    try:
        result = await client.get_disturbances(lang=lang)
    except ValueError as e:
        return f"Error fetching disturbances: {str(e)}"

    lines = ["Current network status:\n"]

    disturbances = result.get("disturbance", [])
    if not isinstance(disturbances, list):
        disturbances = [disturbances] if disturbances else []

    works = result.get("planned", [])
    if not isinstance(works, list):
        works = [works] if works else []

    if disturbances:
        lines.append("⚠️ Disturbances:")
        for dist in disturbances[:5]:
            title = dist.get("title", "Unknown")
            desc = dist.get("description", "")
            lines.append(f"  • {title}")
            if desc:
                lines.append(f"    {desc}")
    else:
        lines.append("✅ No current disturbances")

    if works:
        lines.append("\n🔧 Planned works:")
        for work in works[:5]:
            title = work.get("title", "Unknown")
            desc = work.get("description", "")
            lines.append(f"  • {title}")
            if desc:
                lines.append(f"    {desc}")
    else:
        if not disturbances:
            lines.append("✅ No planned works")

    return "\n".join(lines)


async def run_stdio() -> None:
    """Run the MCP server over stdio (default, used by Claude Code and similar)."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        init_options = app.create_initialization_options()
        await app.run(read_stream, write_stream, init_options)


def build_http_app(
    path: str = "/mcp",
    stateless: bool = False,
    json_response: bool = False,
    allowed_hosts: list[str] | None = None,
):
    """Build a Starlette ASGI app exposing the server via Streamable HTTP.

    The returned app can be served by any ASGI server (uvicorn, hypercorn, ...)
    and mounted next to other apps. Suitable for clients such as Open WebUI.
    """
    import contextlib

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    if not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/") or "/"

    # Only enable DNS-rebinding protection when the operator lists hosts;
    # otherwise the server is reachable behind arbitrary hostnames/proxies.
    security = None
    if allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        )

    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=json_response,
        stateless=stateless,
        security_settings=security,
    )

    class _MCPEndpoint:
        """Raw ASGI endpoint so the exact path matches without slash redirects."""

        async def __call__(self, scope, receive, send):
            await session_manager.handle_request(scope, receive, send)

    async def health(_request):
        return JSONResponse({"status": "ok", "server": "irail-mcp", "mcp_path": path})

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with session_manager.run():
            logger.info("iRail MCP Streamable HTTP endpoint ready at %s", path)
            yield

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route(path, _MCPEndpoint(), methods=["GET", "POST", "DELETE"]),
            Route(path + "/", _MCPEndpoint(), methods=["GET", "POST", "DELETE"]),
        ],
        lifespan=lifespan,
    )


def run_http(
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
    stateless: bool = False,
    json_response: bool = False,
    allowed_hosts: list[str] | None = None,
) -> None:
    """Serve the MCP server over Streamable HTTP with uvicorn."""
    import uvicorn

    http_app = build_http_app(
        path=path,
        stateless=stateless,
        json_response=json_response,
        allowed_hosts=allowed_hosts,
    )
    logger.info("Starting iRail MCP over Streamable HTTP on http://%s:%d%s", host, port, path)
    uvicorn.run(http_app, host=host, port=port, log_level="info")


async def main():
    """Run the MCP server over stdio (kept for backwards compatibility)."""
    logging.basicConfig(level=logging.INFO)
    await run_stdio()


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="irail-mcp",
        description="MCP server for Belgian railway data via the iRail API.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport to use: 'stdio' (default) or 'http' (Streamable HTTP, e.g. for Open WebUI).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000).")
    parser.add_argument("--path", default="/mcp", help="HTTP path of the MCP endpoint (default: /mcp).")
    parser.add_argument(
        "--stateless",
        action="store_true",
        help="Run HTTP transport without server-side sessions (each request is independent).",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        help="Return plain JSON responses instead of SSE streams over HTTP.",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        dest="allowed_hosts",
        metavar="HOST",
        help="Enable DNS-rebinding protection and allow this Host header value (repeatable).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser


def cli(argv: list[str] | None = None):
    """Entry point for console script."""
    import asyncio

    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    if args.transport == "http":
        run_http(
            host=args.host,
            port=args.port,
            path=args.path,
            stateless=args.stateless,
            json_response=args.json_response,
            allowed_hosts=args.allowed_hosts,
        )
    else:
        asyncio.run(run_stdio())


if __name__ == "__main__":
    cli()
