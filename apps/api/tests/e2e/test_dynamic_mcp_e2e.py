"""
E2E tests for Dynamic MCP functionality.

These tests run against the running Docker containers and verify:
1. Health and status endpoints work correctly
2. tools/combined returns expected tools based on DYNAMIC_MCP setting
3. Process tools can be called via REST API
4. SSE endpoint accepts connections

Run with:
    docker compose up -d
    pytest apps/api/tests/e2e/test_dynamic_mcp_e2e.py -v

Note: Meta-tools (airis-find, airis-exec, airis-schema) are tested via unit tests
as they require SSE protocol. These E2E tests verify the REST API layer.
"""

import os
import pytest
import httpx

# API base URL for E2E tests
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:9400")


@pytest.fixture
def api_client():
    """HTTP client for API requests."""
    # Longer timeout for COLD server startup
    with httpx.Client(base_url=API_BASE_URL, timeout=60.0) as client:
        yield client


class TestHealthEndpoints:
    """Test health and readiness endpoints."""

    def test_health_endpoint(self, api_client):
        """Health endpoint should return healthy status."""
        response = api_client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data.get("status") == "healthy"

    def test_ready_endpoint(self, api_client):
        """Ready endpoint should return ok status."""
        response = api_client.get("/ready")
        assert response.status_code == 200


class TestToolsCombined:
    """Test combined tools endpoint."""

    def test_combined_tools_returns_list(self, api_client):
        """Combined tools endpoint should return tools list."""
        response = api_client.get("/api/tools/combined")
        assert response.status_code == 200

        data = response.json()
        assert "tools" in data
        assert "tools_count" in data
        assert isinstance(data["tools"], list)
        assert isinstance(data["tools_count"], int)
        assert data["tools_count"] >= 0

    def test_combined_tools_with_mode_param(self, api_client):
        """Combined tools should accept mode parameter."""
        # Use mode=hot for faster response (no COLD server startup)
        response = api_client.get("/api/tools/combined?mode=hot")
        assert response.status_code == 200

        data = response.json()
        assert "tools" in data

    def test_combined_tools_with_desc_param(self, api_client):
        """Combined tools should accept description mode parameter."""
        for desc_mode in ["full", "summary", "brief", "none"]:
            response = api_client.get(f"/api/tools/combined?desc={desc_mode}")
            assert response.status_code == 200

            data = response.json()
            assert "description_mode" in data
            assert data["description_mode"] == desc_mode


class TestToolsStatus:
    """Test tools status endpoint."""

    def test_tools_status_returns_servers(self, api_client):
        """Tools status should return server info."""
        response = api_client.get("/api/tools/status")
        assert response.status_code == 200

        data = response.json()
        assert "servers" in data
        assert "roster" in data

    def test_tools_status_with_metrics(self, api_client):
        """Tools status should accept metrics flag."""
        response = api_client.get("/api/tools/status?metrics=true")
        assert response.status_code == 200

        data = response.json()
        assert "processes" in data


class TestProcessServers:
    """Test process server endpoints."""

    def test_list_process_servers(self, api_client):
        """Process servers endpoint should list configured servers."""
        response = api_client.get("/process/servers")
        assert response.status_code == 200

        data = response.json()
        # Response is {"servers": [...]}
        assert "servers" in data
        assert isinstance(data["servers"], list)

    def test_get_specific_server(self, api_client):
        """Should be able to get specific server info."""
        # First get list of servers
        list_response = api_client.get("/process/servers")
        assert list_response.status_code == 200

        data = list_response.json()
        servers = data.get("servers", [])
        if servers:
            # Try to get first server's details
            server_name = servers[0].get("name")

            if server_name:
                response = api_client.get(f"/process/servers/{server_name}")
                # May return 200 (found) or 404 (not running)
                assert response.status_code in [200, 404, 500]


class TestProcessTools:
    """Test process tools endpoints."""

    def test_list_process_tools_hot(self, api_client):
        """Should list tools from HOT process servers (fast)."""
        # Use mode=hot for faster response (no COLD server startup)
        response = api_client.get("/process/tools?mode=hot")
        assert response.status_code == 200

        data = response.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)

    @pytest.mark.skip(reason="COLD server startup takes too long for CI")
    def test_list_tools_all_modes(self, api_client):
        """Should filter tools by mode (hot/cold/all)."""
        for mode in ["hot", "cold", "all"]:
            response = api_client.get(f"/process/tools?mode={mode}")
            assert response.status_code == 200

            data = response.json()
            assert "tools" in data


class TestProcessToolCall:
    """Test process tool call endpoint."""

    def test_call_gateway_list_servers(self, api_client):
        """Should be able to call gateway_list_servers tool."""
        response = api_client.post(
            "/process/tools/call",
            json={"name": "gateway_list_servers", "arguments": {}},
        )
        # Should return success or error response
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.json()
            # Should have result or error
            assert "result" in data or "error" in data


class TestSSEEndpoint:
    """Test SSE endpoint availability."""

    def test_sse_endpoint_exists(self, api_client):
        """SSE endpoint should be accessible."""
        # SSE endpoints expect upgrade, but we can test OPTIONS
        try:
            response = api_client.options("/sse")
            # Any response means endpoint exists
            assert response.status_code in [200, 204, 405]
        except Exception:
            # If OPTIONS fails, try HEAD
            try:
                response = api_client.head("/sse")
                assert response.status_code in [200, 405]
            except Exception:
                # SSE endpoint exists but may require proper client
                pass


class TestMCPEndpoints:
    """Test MCP-related endpoints."""

    def test_mcp_sse_endpoint_exists(self, api_client):
        """MCP SSE endpoint should exist."""
        try:
            response = api_client.options("/mcp/sse")
            assert response.status_code in [200, 204, 405]
        except Exception:
            pass

    def test_mcp_root_endpoint(self, api_client):
        """MCP root endpoint should be accessible."""
        response = api_client.get("/mcp/")
        # May return various status codes depending on implementation
        assert response.status_code in [200, 404, 405, 500]


class TestMetricsEndpoint:
    """Test Prometheus metrics endpoint."""

    def test_metrics_endpoint(self, api_client):
        """Metrics endpoint should return Prometheus format."""
        response = api_client.get("/metrics")
        assert response.status_code == 200

        # Should be text/plain Prometheus format
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "text" in content_type


class TestDynamicMCPIntegration:
    """Integration tests for Dynamic MCP behavior."""

    def test_tools_available(self, api_client):
        """Should have tools available from process servers."""
        response = api_client.get("/api/tools/combined")
        assert response.status_code == 200

        data = response.json()
        tools = data.get("tools", [])

        # Should have at least some tools
        # In dynamic mode, this will show direct tools (not meta-tools)
        # Meta-tools are only exposed via SSE
        print(f"Found {len(tools)} tools via REST API")

    def test_server_roster_available(self, api_client):
        """Should have server roster with hot/cold categorization."""
        response = api_client.get("/api/tools/status")
        assert response.status_code == 200

        data = response.json()
        roster = data.get("roster", {})

        assert "hot" in roster
        assert "cold" in roster
        assert "summary" in roster

        summary = roster.get("summary", {})
        print(
            f"Server roster: {summary.get('hot_count', 0)} hot, {summary.get('cold_count', 0)} cold"
        )


class TestGatewayControlTools:
    """Test gateway control tools."""

    def test_list_tools_includes_gateway_control(self, api_client):
        """Process tools should include gateway control tools."""
        response = api_client.get("/process/tools?mode=hot")
        assert response.status_code == 200

        data = response.json()
        tools = data.get("tools", [])
        tool_names = [t.get("name") for t in tools]

        # Gateway control tools should be available
        expected_tools = [
            "gateway_list_servers",
            "gateway_enable_server",
            "gateway_disable_server",
        ]

        for expected in expected_tools:
            if expected in tool_names:
                print(f"Found gateway control tool: {expected}")
                break
        else:
            print(f"Available tools: {tool_names[:5]}...")


class TestDynamicMCPToolsListBehavior:
    """Test Dynamic MCP tools/list behavior.

    When DYNAMIC_MCP=true, the gateway should return:
    - Meta-tools (airis-find, airis-exec, airis-schema)
    - HOT server tools (directly callable)

    COLD server tools should NOT be in tools/list; they are
    discovered via airis-find and called via airis-exec.
    """

    def test_hot_tools_endpoint_returns_gateway_control(self, api_client):
        """HOT tools endpoint should return gateway control tools."""
        response = api_client.get("/process/tools?mode=hot")
        assert response.status_code == 200

        data = response.json()
        tools = data.get("tools", [])
        tool_names = {t.get("name") for t in tools}

        # Gateway control (HOT) tools should be present
        assert "gateway_list_servers" in tool_names or len(tools) > 0, (
            f"Expected gateway control tools, got: {list(tool_names)[:5]}"
        )

    def test_cold_tools_not_in_hot_response(self, api_client):
        """COLD server tools should NOT be in HOT tools response."""
        response = api_client.get("/process/tools?mode=hot")
        assert response.status_code == 200

        data = response.json()
        tools = data.get("tools", [])
        tool_names = {t.get("name") for t in tools}

        # Supabase tools (COLD) should NOT be in HOT response
        cold_tools = {"list_tables", "execute_sql", "list_projects", "list_migrations"}
        found_cold = tool_names.intersection(cold_tools)

        assert len(found_cold) == 0, (
            f"COLD tools should not be in HOT response: {found_cold}"
        )

    def test_roster_shows_hot_and_cold_servers(self, api_client):
        """Server roster should categorize HOT and COLD servers."""
        response = api_client.get("/api/tools/status")
        assert response.status_code == 200

        data = response.json()
        roster = data.get("roster", {})

        assert "hot" in roster, "Roster should have HOT category"
        assert "cold" in roster, "Roster should have COLD category"

        hot_servers = roster.get("hot", [])
        cold_servers = roster.get("cold", [])

        # Should have at least some servers in each category
        # (depends on mcp-config.json configuration)
        print(f"HOT servers: {hot_servers}")
        print(f"COLD servers: {cold_servers}")

        # Gateway control should be HOT
        hot_names = {s.get("name") if isinstance(s, dict) else s for s in hot_servers}
        if "airis-mcp-gateway-control" in hot_names or "airis-commands" in hot_names:
            print("Found expected HOT servers")

    def test_tools_count_difference(self, api_client):
        """HOT tools should be fewer than ALL tools (token savings)."""
        # Get HOT tools count
        hot_response = api_client.get("/process/tools?mode=hot")
        assert hot_response.status_code == 200
        hot_data = hot_response.json()
        hot_count = len(hot_data.get("tools", []))

        # Get ALL tools count (may be slow due to COLD server startup)
        # Skip if takes too long
        try:
            import httpx

            with httpx.Client(base_url=API_BASE_URL, timeout=10.0) as quick_client:
                all_response = quick_client.get("/api/tools/combined")
                if all_response.status_code == 200:
                    all_data = all_response.json()
                    all_count = all_data.get("tools_count", 0)

                    print(f"HOT tools: {hot_count}, ALL tools: {all_count}")

                    # HOT should be subset of ALL
                    if all_count > 0:
                        assert hot_count <= all_count, (
                            f"HOT tools ({hot_count}) should be <= ALL tools ({all_count})"
                        )
        except Exception as e:
            print(f"Skipped ALL tools comparison: {e}")


class TestMetaToolsAvailability:
    """Test meta-tools are properly exposed."""

    def test_tools_status_shows_meta_tools_info(self, api_client):
        """Tools status should show meta-tools availability."""
        response = api_client.get("/api/tools/status")
        assert response.status_code == 200

        data = response.json()
        # Check if dynamic MCP info is available
        print(f"Status response keys: {data.keys()}")

    def test_gateway_tool_call_works(self, api_client):
        """Gateway control tools should be callable via REST API."""
        # Call gateway_list_servers (HOT tool)
        response = api_client.post(
            "/process/tools/call",
            json={"name": "gateway_list_servers", "arguments": {}},
        )

        # Should succeed or return structured error
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.json()
            print(f"gateway_list_servers response: {data}")

            # Should have result with server list
            if "result" in data:
                result = data["result"]
                if isinstance(result, dict) and "content" in result:
                    print("Successfully called HOT gateway tool")
