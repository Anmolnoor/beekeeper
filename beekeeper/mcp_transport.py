"""MCP (Model Context Protocol) transport: connect to MCP servers via stdio or HTTP.

Provides a sync-facing client that runs the async MCP SDK in a dedicated thread,
so Queen and tool runtime stay synchronous while still using real MCP servers.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any

from .mcp_adapter import register_mcp_tools


def _mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def _tool_descriptor_from_mcp(tool: Any) -> dict[str, Any]:
    """Convert MCP SDK tool shape to adapter descriptor (name, description, inputSchema)."""
    name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else "")
    description = getattr(tool, "description", None) or (tool.get("description") if isinstance(tool, dict) else "") or ""
    input_schema = getattr(tool, "inputSchema", None) or (tool.get("inputSchema") if isinstance(tool, dict) else {})
    if input_schema is None:
        input_schema = {}
    return {
        "name": str(name).strip() or "unknown",
        "description": str(description).strip() or f"MCP tool: {name}",
        "inputSchema": input_schema if isinstance(input_schema, dict) else {},
    }


def _call_tool_result_to_output(result: Any) -> dict[str, Any] | str:
    """Convert MCP call_tool result (content list, is_error) to adapter-friendly dict or str."""
    if result is None:
        return {"text": "", "content": []}
    is_error = getattr(result, "isError", None) or (result.get("isError") if isinstance(result, dict) else False)
    content = getattr(result, "content", None) or (result.get("content") if isinstance(result, dict) else []) or []
    parts = []
    for item in content:
        if isinstance(item, dict):
            if item.get("type") == "text" and "text" in item:
                parts.append(item["text"])
            elif "text" in item:
                parts.append(item["text"])
        else:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
    text = "\n".join(parts) if parts else ""
    if is_error:
        return {"error": True, "text": text, "content": content}
    return {"text": text, "content": content} if content else text or {"text": ""}


class _MCPClientSyncBridge:
    """
    Holds an asyncio loop in a background thread and an MCP ClientSession.
    Exposes sync list_tools() and call_tool() that run coroutines on that loop.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, session: Any) -> None:
        self._loop = loop
        self._session = session

    def list_tools(self) -> list[dict[str, Any]]:
        async def _list() -> list[dict[str, Any]]:
            resp = await self._session.list_tools()
            tools = getattr(resp, "tools", None) or []
            return [_tool_descriptor_from_mcp(t) for t in tools]

        future = asyncio.run_coroutine_threadsafe(_list(), self._loop)
        return future.result()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | str:
        async def _call() -> Any:
            return await self._session.call_tool(name, arguments)

        future = asyncio.run_coroutine_threadsafe(_call(), self._loop)
        result = future.result()
        return _call_tool_result_to_output(result)


def connect_stdio_sync(
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> _MCPClientSyncBridge | None:
    """
    Connect to an MCP server over stdio (blocking). Runs the async SDK in a new thread.
    Returns a sync bridge with list_tools() and call_tool(name, arguments), or None if mcp not installed / connection fails.
    """
    if not _mcp_available():
        return None

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    loop: asyncio.AbstractEventLoop | None = None
    bridge: _MCPClientSyncBridge | None = None
    exc_holder: list[BaseException] = []

    async def _connect() -> None:
        nonlocal loop, bridge
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                bridge = _MCPClientSyncBridge(loop, session)
                # Keep connection alive until loop is stopped
                while True:
                    await asyncio.sleep(3600)

    def _run() -> None:
        try:
            asyncio.run(_connect())
        except BaseException as e:
            exc_holder.append(e)

    # Start connection in thread; wait briefly for init
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    for _ in range(50):
        if bridge is not None:
            break
        if exc_holder:
            raise exc_holder[0]
        threading.Event().wait(0.1)
    else:
        if exc_holder:
            raise exc_holder[0]
        raise RuntimeError("MCP stdio connection timed out")

    return bridge


def connect_http_sync(url: str) -> _MCPClientSyncBridge | None:
    """
    Connect to an MCP server over HTTP/SSE (blocking). Runs the async SDK in a new thread.
    Returns a sync bridge with list_tools() and call_tool(name, arguments), or None if mcp not installed / connection fails.
    """
    if not _mcp_available():
        return None
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except ImportError:
        return None

    loop: asyncio.AbstractEventLoop | None = None
    bridge: _MCPClientSyncBridge | None = None
    exc_holder: list[BaseException] = []

    async def _connect() -> None:
        nonlocal loop, bridge
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async with sse_client(url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                bridge = _MCPClientSyncBridge(loop, session)
                while True:
                    await asyncio.sleep(3600)

    def _run() -> None:
        try:
            asyncio.run(_connect())
        except BaseException as e:
            exc_holder.append(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    for _ in range(50):
        if bridge is not None:
            break
        if exc_holder:
            raise exc_holder[0]
        threading.Event().wait(0.1)
    else:
        if exc_holder:
            raise exc_holder[0]
        raise RuntimeError("MCP HTTP connection timed out")

    return bridge


def load_mcp_config() -> list[dict[str, Any]]:
    """
    Load MCP server config from environment or config file.
    Returns a list of server configs: [{"transport": "stdio", "command": "npx", "args": ["-y", "..."], ...}, {"transport": "http", "url": "..."}, ...].
    Default: empty list (no MCP servers).
    """
    # Env: BEEKEEPER_MCP_SERVERS = stdio:npx:-y:@modelcontextprotocol/server-filesystem  or  http:https://...
    # Or JSON array in BEEKEEPER_MCP_SERVERS_JSON for multiple servers
    raw = os.environ.get("BEEKEEPER_MCP_SERVERS_JSON", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    single = os.environ.get("BEEKEEPER_MCP_SERVERS", "").strip()
    if not single:
        return []
    parts = single.split(":", 1)
    if len(parts) < 2:
        return []
    transport, rest = parts[0].lower(), parts[1]
    if transport == "stdio":
        # rest = "npx:-y:@modelcontextprotocol/server-filesystem" -> command npx, args ["-y", "@modelcontextprotocol/server-filesystem"]
        all_parts = rest.split(":")
        if not all_parts:
            return []
        return [{"transport": "stdio", "command": all_parts[0], "args": all_parts[1:] or []}]
    if transport == "http" or transport == "https":
        return [{"transport": "http", "url": rest if "://" in rest else f"{transport}://{rest}"}]
    return []


def register_mcp_servers_from_config(
    tool_registry: Any,
    configs: list[dict[str, Any]] | None = None,
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    timeout_seconds: float = 30.0,
) -> list[str]:
    """
    Connect to each configured MCP server, discover tools, and register them on tool_registry.
    configs defaults to load_mcp_config().
    Returns list of server identifiers that were successfully connected (e.g. ["stdio:npx", "http:https://..."]) for logging.
    """
    if configs is None:
        configs = load_mcp_config()
    if not configs:
        return []
    from .tool_runtime import ToolRegistry

    if not isinstance(tool_registry, ToolRegistry):
        return []
    connected: list[str] = []
    for i, cfg in enumerate(configs):
        if not isinstance(cfg, dict):
            continue
        transport = (cfg.get("transport") or "stdio").lower()
        try:
            if transport == "stdio":
                command = cfg.get("command", "")
                args = cfg.get("args") or []
                if not command:
                    continue
                bridge = connect_stdio_sync(command, args, cfg.get("env"))
            elif transport in ("http", "https", "sse"):
                url = cfg.get("url", "")
                if not url:
                    continue
                bridge = connect_http_sync(url)
            else:
                continue
            if bridge is None:
                continue
            descriptors = bridge.list_tools()
            if not descriptors:
                connected.append(f"{transport}:{i}")
                continue
            def _make_caller(b: _MCPClientSyncBridge) -> Any:
                def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any] | str:
                    return b.call_tool(name, arguments)
                return _call
            register_mcp_tools(
                tool_registry,
                descriptors,
                call_tool_fn=_make_caller(bridge),
                allowlist=allowlist,
                denylist=denylist,
                timeout_seconds=timeout_seconds,
            )
            connected.append(f"{transport}:{command or url}:{i}")
        except Exception:
            continue
    return connected
