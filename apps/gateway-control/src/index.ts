#!/usr/bin/env node
/**
 * Gateway Control MCP Server
 *
 * Provides tools for controlling the AIRIS MCP Gateway:
 * - list_servers: List all MCP servers and their status
 * - enable_server: Enable a server
 * - disable_server: Disable a server
 * - get_server_status: Get detailed status of a server
 * - restart_server: Restart a server
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ListPromptsRequestSchema,
  GetPromptRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z, ZodSchema } from "zod";

const API_URL = process.env.API_URL || "http://localhost:9400";

// Tool argument schemas (issue #106). See airis-commands/src/index.ts for
// the rationale: runtime-validated inputs instead of unchecked type casts.

const ServerNameRequiredSchema = z.object({
  server_name: z.string().min(1, "server_name must be a non-empty string"),
});

const ServerNameOptionalSchema = z.object({
  server_name: z.string().min(1).optional(),
});

function parseArgs<T>(schema: ZodSchema<T>, raw: unknown, toolName: string): T {
  const result = schema.safeParse(raw ?? {});
  if (!result.success) {
    const issue = result.error.issues[0];
    const path = issue.path.join(".") || "<root>";
    throw new Error(`Invalid arguments for ${toolName}: ${path}: ${issue.message}`);
  }
  return result.data;
}

interface ServerStatus {
  name: string;
  type: string;
  command?: string;
  enabled: boolean;
  state: string;
  status?: string;
  tools_count: number;
}

interface ToolInfo {
  name: string;
  description?: string;
}

interface HealthResponse {
  status: string;
}

interface ReadyResponse {
  ready: boolean;
  gateway: string;
}

interface ToolsStatusResponse {
  servers: ServerStatus[];
  sse?: {
    active_clients?: number;
    total_events_sent?: number;
  };
}

async function fetchApi<T = unknown>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

const server = new Server(
  {
    name: "gateway-control",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
      prompts: {},
    },
  }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "gateway_list_servers",
        description: "List all MCP servers registered in the gateway with their current status (enabled/disabled, running/stopped, tools count)",
        inputSchema: {
          type: "object",
          properties: {},
          required: [],
        },
      },
      {
        name: "gateway_enable_server",
        description: "Enable an MCP server in the gateway. The server will start on next request.",
        inputSchema: {
          type: "object",
          properties: {
            server_name: {
              type: "string",
              description: "Name of the server to enable",
            },
          },
          required: ["server_name"],
        },
      },
      {
        name: "gateway_disable_server",
        description: "Disable an MCP server in the gateway. Running process will be stopped.",
        inputSchema: {
          type: "object",
          properties: {
            server_name: {
              type: "string",
              description: "Name of the server to disable",
            },
          },
          required: ["server_name"],
        },
      },
      {
        name: "gateway_get_server_status",
        description: "Get detailed status of a specific MCP server",
        inputSchema: {
          type: "object",
          properties: {
            server_name: {
              type: "string",
              description: "Name of the server to get status for",
            },
          },
          required: ["server_name"],
        },
      },
      {
        name: "gateway_list_tools",
        description: "List all available tools from all enabled MCP servers",
        inputSchema: {
          type: "object",
          properties: {
            server_name: {
              type: "string",
              description: "Optional: filter tools by server name",
            },
          },
          required: [],
        },
      },
      {
        name: "gateway_health",
        description: "Check gateway health and get overview of all servers",
        inputSchema: {
          type: "object",
          properties: {},
          required: [],
        },
      },
    ],
  };
});

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "gateway_list_servers": {
        const result = await fetchApi<{ servers: ServerStatus[] }>("/process/servers");
        const servers: ServerStatus[] = result.servers || [];

        const formatted = servers.map((s) =>
          `- ${s.name}: ${s.enabled ? "enabled" : "disabled"} | ${s.state} | ${s.tools_count} tools`
        ).join("\n");

        return {
          content: [
            {
              type: "text",
              text: `MCP Servers (${servers.length}):\n\n${formatted}`,
            },
          ],
        };
      }

      case "gateway_enable_server": {
        const { server_name: serverName } = parseArgs(
          ServerNameRequiredSchema,
          args,
          "gateway_enable_server",
        );

        const result = await fetchApi<{ state: string }>(`/process/servers/${serverName}/enable`, {
          method: "POST",
        });

        return {
          content: [
            {
              type: "text",
              text: `Server "${serverName}" enabled. State: ${result.state}`,
            },
          ],
        };
      }

      case "gateway_disable_server": {
        const { server_name: serverName } = parseArgs(
          ServerNameRequiredSchema,
          args,
          "gateway_disable_server",
        );

        const result = await fetchApi<{ state: string }>(`/process/servers/${serverName}/disable`, {
          method: "POST",
        });

        return {
          content: [
            {
              type: "text",
              text: `Server "${serverName}" disabled. State: ${result.state}`,
            },
          ],
        };
      }

      case "gateway_get_server_status": {
        const { server_name: serverName } = parseArgs(
          ServerNameRequiredSchema,
          args,
          "gateway_get_server_status",
        );

        const result = await fetchApi<ServerStatus>(`/process/servers/${serverName}`);

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(result, null, 2),
            },
          ],
        };
      }

      case "gateway_list_tools": {
        const { server_name: serverName } = parseArgs(
          ServerNameOptionalSchema,
          args,
          "gateway_list_tools",
        );
        const path = serverName
          ? `/process/tools?server=${serverName}`
          : "/process/tools";

        const result = await fetchApi<{ tools: ToolInfo[] }>(path);
        const tools: ToolInfo[] = result.tools || [];

        const formatted = tools.map((t) => `- ${t.name}: ${t.description || "(no description)"}`).join("\n");

        return {
          content: [
            {
              type: "text",
              text: `Available Tools (${tools.length}):\n\n${formatted}`,
            },
          ],
        };
      }

      case "gateway_health": {
        const [health, ready, status] = await Promise.all([
          fetchApi<HealthResponse>("/health"),
          fetchApi<ReadyResponse>("/ready"),
          fetchApi<ToolsStatusResponse>("/api/tools/status"),
        ]);

        const servers: ServerStatus[] = status.servers || [];
        const serverSummary = servers.map((s) =>
          `  - ${s.name}: ${s.status || s.state}`
        ).join("\n");

        return {
          content: [
            {
              type: "text",
              text: `Gateway Health:
- Status: ${health.status}
- Ready: ${ready.ready}
- Gateway: ${ready.gateway}

Servers (${servers.length}):
${serverSummary}

SSE Stats:
- Active clients: ${status.sse?.active_clients || 0}
- Total events: ${status.sse?.total_events_sent || 0}`,
            },
          ],
        };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      content: [
        {
          type: "text",
          text: `Error: ${message}`,
        },
      ],
      isError: true,
    };
  }
});

// List available prompts (become slash commands in Claude Code)
server.setRequestHandler(ListPromptsRequestSchema, async () => {
  return {
    prompts: [
      {
        name: "status",
        description: "Show gateway health and all server status",
      },
      {
        name: "tools",
        description: "List all available tools from enabled MCP servers",
      },
      {
        name: "servers",
        description: "List all MCP servers with their status",
      },
      {
        name: "enable",
        description: "Enable an MCP server",
        arguments: [
          {
            name: "server_name",
            description: "Name of the server to enable",
            required: true,
          },
        ],
      },
      {
        name: "disable",
        description: "Disable an MCP server",
        arguments: [
          {
            name: "server_name",
            description: "Name of the server to disable",
            required: true,
          },
        ],
      },
    ],
  };
});

// Handle prompt requests
server.setRequestHandler(GetPromptRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  switch (name) {
    case "status": {
      return {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: "Check the AIRIS MCP Gateway health status and show me an overview of all servers. Use the gateway_health tool.",
            },
          },
        ],
      };
    }

    case "tools": {
      return {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: "List all available tools from all enabled MCP servers. Use the gateway_list_tools tool.",
            },
          },
        ],
      };
    }

    case "servers": {
      return {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: "List all MCP servers registered in the gateway with their current status. Use the gateway_list_servers tool.",
            },
          },
        ],
      };
    }

    case "enable": {
      const serverName = args?.server_name;
      if (!serverName) {
        return {
          messages: [
            {
              role: "user",
              content: {
                type: "text",
                text: "Enable an MCP server. Which server would you like to enable? Use gateway_list_servers to show available servers first.",
              },
            },
          ],
        };
      }
      return {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `Enable the MCP server named "${serverName}". Use the gateway_enable_server tool with server_name="${serverName}".`,
            },
          },
        ],
      };
    }

    case "disable": {
      const serverName = args?.server_name;
      if (!serverName) {
        return {
          messages: [
            {
              role: "user",
              content: {
                type: "text",
                text: "Disable an MCP server. Which server would you like to disable? Use gateway_list_servers to show available servers first.",
              },
            },
          ],
        };
      }
      return {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `Disable the MCP server named "${serverName}". Use the gateway_disable_server tool with server_name="${serverName}".`,
            },
          },
        ],
      };
    }

    default:
      throw new Error(`Unknown prompt: ${name}`);
  }
});

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Gateway Control MCP server running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
