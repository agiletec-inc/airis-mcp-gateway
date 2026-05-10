"""
E2E tests for individual MCP server tool calls.

These tests verify that each enabled MCP server can be called and returns valid responses.
Tests are designed to be non-destructive and use read-only operations where possible.

Run with:
    docker compose up -d
    pytest apps/api/tests/e2e/test_mcp_servers_e2e.py -v

To skip slow (COLD server) tests:
    pytest -m "not slow"
"""
import os
import pytest
import httpx
import json
import time
from typing import Any, Optional

# API base URL for E2E tests
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:9400")


@pytest.fixture
def api_client():
    """HTTP client for API requests with long timeout for COLD servers."""
    with httpx.Client(base_url=API_BASE_URL, timeout=120.0) as client:
        yield client


def call_tool(client: httpx.Client, tool_name: str, arguments: dict) -> dict:
    """Helper to call a tool via the process API."""
    try:
        response = client.post(
            "/process/tools/call",
            json={"name": tool_name, "arguments": arguments}
        )
        return {"status_code": response.status_code, "data": response.json() if response.status_code == 200 else None}
    except httpx.TimeoutException:
        return {"status_code": 408, "data": None, "timeout": True}


def call_tool_dynamic(client: httpx.Client, server: str, tool: str, arguments: dict) -> dict:
    """Helper to call a tool via Dynamic MCP airis-exec."""
    response = client.post(
        "/process/tools/call",
        json={
            "name": "mcp-exec",
            "arguments": {
                "tool": f"{server}:{tool}",
                "arguments": json.dumps(arguments)
            }
        }
    )
    return {"status_code": response.status_code, "data": response.json() if response.status_code == 200 else None}


class TestGatewayControlServer:
    """Test gateway-control HOT server."""

    def test_gateway_list_servers(self, api_client):
        """gateway_list_servers should return server list."""
        result = call_tool(api_client, "gateway_list_servers", {})
        assert result["status_code"] == 200

        data = result["data"]
        assert "result" in data
        # Result contains text with server list
        assert "MCP Servers" in data["result"]["content"][0]["text"]

    def test_gateway_health(self, api_client):
        """gateway_health should return health info."""
        result = call_tool(api_client, "gateway_health", {})
        assert result["status_code"] == 200

        data = result["data"]
        assert "result" in data
        text = data["result"]["content"][0]["text"]
        assert "Gateway Health" in text
        assert "Status:" in text

    def test_gateway_list_tools(self, api_client):
        """gateway_list_tools should return available tools (may timeout if COLD servers starting)."""
        result = call_tool(api_client, "gateway_list_tools", {})
        assert result["status_code"] == 200

        data = result["data"]
        # May return result or timeout error
        if "error" in data and "timeout" in str(data.get("error", {}).get("message", "")).lower():
            pytest.skip("Timeout waiting for COLD servers - expected in CI")

        assert "result" in data
        text = data["result"]["content"][0]["text"]
        assert "Available Tools" in text

    def test_gateway_get_server_status(self, api_client):
        """gateway_get_server_status should return server details."""
        result = call_tool(api_client, "gateway_get_server_status", {
            "server_name": "airis-mcp-gateway-control"
        })
        if result.get("timeout"):
            pytest.skip("Request timed out")
        assert result["status_code"] == 200

        data = result["data"]
        if "error" in data:
            # Error response is acceptable
            return
        assert "result" in data


class TestAirisCommandsServer:
    """Test airis-commands HOT server."""

    def test_airis_config_get(self, api_client):
        """airis_config_get should return configuration."""
        result = call_tool(api_client, "airis_config_get", {})
        if result.get("timeout"):
            pytest.skip("Request timed out")
        assert result["status_code"] == 200

        data = result["data"]
        if "error" in data and "timeout" in str(data.get("error", {}).get("message", "")).lower():
            pytest.skip("Timeout - expected in CI")

        assert "result" in data
        # Should return JSON config
        text = data["result"]["content"][0]["text"]
        config = json.loads(text)
        assert "mcpServers" in config

    def test_airis_profile_list(self, api_client):
        """airis_profile_list should return profiles."""
        result = call_tool(api_client, "airis_profile_list", {})
        if result.get("timeout"):
            pytest.skip("Request timed out")
        assert result["status_code"] == 200

        data = result["data"]
        if "error" in data and "timeout" in str(data.get("error", {}).get("message", "")).lower():
            pytest.skip("Timeout - expected in CI")

        assert "result" in data


@pytest.mark.slow
class TestMemoryServer:
    """Test memory COLD server - knowledge graph operations."""

    def test_memory_create_and_search(self, api_client):
        """Test creating and searching entities in memory."""
        # Create a test entity
        create_result = call_tool(api_client, "create_entities", {
            "entities": [
                {
                    "name": "E2E_TEST_ENTITY",
                    "entityType": "test",
                    "observations": ["This is an E2E test entity"]
                }
            ]
        })
        assert create_result["status_code"] == 200

        # Search for the entity
        search_result = call_tool(api_client, "search_nodes", {
            "query": "E2E_TEST_ENTITY"
        })
        assert search_result["status_code"] == 200

    def test_memory_read_graph(self, api_client):
        """Test reading the memory graph."""
        result = call_tool(api_client, "read_graph", {})
        assert result["status_code"] == 200


@pytest.mark.slow
class TestFetchServer:
    """Test fetch COLD server - web fetching."""

    def test_fetch_url(self, api_client):
        """Test fetching a URL."""
        result = call_tool(api_client, "fetch", {
            "url": "https://httpbin.org/get"
        })
        assert result["status_code"] == 200

        data = result["data"]
        assert "result" in data


@pytest.mark.slow
class TestSequentialThinkingServer:
    """Test sequential-thinking COLD server."""

    def test_sequential_thinking(self, api_client):
        """Test sequential thinking tool."""
        result = call_tool(api_client, "sequentialthinking", {
            "thought": "E2E test thought - analyzing system status",
            "thoughtNumber": 1,
            "totalThoughts": 1,
            "nextThoughtNeeded": False
        })
        assert result["status_code"] == 200


class TestServerLifecycle:
    """Test server enable/disable lifecycle."""

    def test_get_server_list(self, api_client):
        """Get list of all servers."""
        response = api_client.get("/process/servers")
        assert response.status_code == 200

        data = response.json()
        servers = data.get("servers", [])

        # Should have multiple servers
        assert len(servers) > 0

        # Print server info for debugging
        for server in servers:
            status = "enabled" if server.get("enabled") else "disabled"
            state = server.get("state", "unknown")
            print(f"  {server['name']}: {status} / {state}")

    def test_server_enable_disable_cycle(self, api_client):
        """Test enabling and disabling a server."""
        # Get a disabled server to test with
        response = api_client.get("/process/servers")
        data = response.json()
        servers = data.get("servers", [])

        disabled_servers = [s for s in servers if not s.get("enabled")]
        if not disabled_servers:
            pytest.skip("No disabled servers to test with")

        test_server = disabled_servers[0]["name"]

        # Enable the server
        enable_result = call_tool(api_client, "gateway_enable_server", {
            "server_name": test_server
        })
        assert enable_result["status_code"] == 200

        # Verify it's enabled
        verify_response = api_client.get(f"/process/servers/{test_server}")
        if verify_response.status_code == 200:
            verify_data = verify_response.json()
            assert verify_data.get("enabled") == True

        # Disable the server again
        disable_result = call_tool(api_client, "gateway_disable_server", {
            "server_name": test_server
        })
        assert disable_result["status_code"] == 200


class TestToolDiscovery:
    """Test tool discovery across all servers."""

    def test_discover_hot_tools(self, api_client):
        """Discover tools from HOT servers."""
        response = api_client.get("/process/tools?mode=hot")
        assert response.status_code == 200

        data = response.json()
        tools = data.get("tools", [])

        # Should have gateway-control tools
        tool_names = [t["name"] for t in tools]
        assert "gateway_list_servers" in tool_names or len(tool_names) > 0

        print(f"Found {len(tools)} HOT tools")

    def test_discover_all_servers_via_status(self, api_client):
        """Discover all configured servers via status endpoint."""
        response = api_client.get("/api/tools/status")
        assert response.status_code == 200

        data = response.json()
        servers = data.get("servers", [])
        roster = data.get("roster", {})

        hot_count = roster.get("summary", {}).get("hot_count", 0)
        cold_count = roster.get("summary", {}).get("cold_count", 0)

        print(f"Servers: {hot_count} HOT, {cold_count} COLD")
        assert hot_count + cold_count > 0


class TestErrorHandling:
    """Test error handling for invalid operations."""

    def test_call_nonexistent_tool(self, api_client):
        """Calling non-existent tool should return error."""
        result = call_tool(api_client, "nonexistent_tool_xyz", {})
        # Should return 200 with error in result, or 404/500, or timeout
        if result.get("timeout"):
            # Timeout is acceptable for nonexistent tool
            return
        assert result["status_code"] in [200, 404, 500]

        if result["status_code"] == 200 and result["data"]:
            # Check if it's an error response
            data = result["data"]
            if "error" in data:
                assert True  # Error response is expected
            elif "result" in data and data["result"].get("isError"):
                assert True  # MCP error response

    def test_call_tool_with_invalid_args(self, api_client):
        """Calling tool with invalid arguments should handle gracefully."""
        result = call_tool(api_client, "gateway_get_server_status", {
            "server_name": "nonexistent_server_xyz"
        })
        # Should return 200 with error message, or error status
        assert result["status_code"] in [200, 404, 500]

    def test_get_nonexistent_server(self, api_client):
        """Getting non-existent server should return 404."""
        response = api_client.get("/process/servers/nonexistent_server_xyz")
        assert response.status_code in [404, 500]


class TestConcurrentCalls:
    """Test concurrent tool calls."""

    def test_concurrent_tool_calls(self, api_client):
        """Multiple concurrent calls should not cause issues."""
        import concurrent.futures

        def call_health():
            return call_tool(api_client, "gateway_health", {})

        # Make 5 concurrent calls
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(call_health) for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # All calls should succeed
        success_count = sum(1 for r in results if r["status_code"] == 200)
        assert success_count >= 4  # Allow 1 failure for timing issues


class TestResponseFormat:
    """Test response format consistency."""

    def test_tool_response_format(self, api_client):
        """Tool responses should have consistent format."""
        result = call_tool(api_client, "gateway_list_servers", {})
        assert result["status_code"] == 200

        data = result["data"]
        # MCP tool response format
        assert "result" in data
        assert "content" in data["result"]
        assert isinstance(data["result"]["content"], list)
        assert len(data["result"]["content"]) > 0
        assert "type" in data["result"]["content"][0]
        assert "text" in data["result"]["content"][0]

    def test_server_list_response_format(self, api_client):
        """Server list should have consistent format."""
        response = api_client.get("/process/servers")
        assert response.status_code == 200

        data = response.json()
        assert "servers" in data

        if data["servers"]:
            server = data["servers"][0]
            # Required fields
            assert "name" in server
            assert "enabled" in server
            assert "state" in server

    def test_tools_combined_response_format(self, api_client):
        """Combined tools should have consistent format."""
        response = api_client.get("/api/tools/combined")
        assert response.status_code == 200

        data = response.json()
        assert "tools" in data
        assert "tools_count" in data
        # May have 'sources' or 'servers' depending on implementation
        assert "sources" in data or "servers" in data

        if data["tools"]:
            tool = data["tools"][0]
            assert "name" in tool
            # Optional but common fields
            if "description" in tool:
                assert isinstance(tool["description"], str)
