#!/usr/bin/env node
/**
 * AIRIS Commands MCP Server
 *
 * Config management tools that require file-system writes to mcp-config.json:
 * - airis_config_add_server / airis_config_remove_server
 * - airis_profile_save / airis_profile_load / airis_profile_list
 * - airis_mcp_detect (repo scan → auto-suggest servers)
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import * as fs from "fs/promises";
import * as path from "path";
import { z, ZodError, ZodSchema } from "zod";

import {
  MCP_MAPPINGS,
  readConfig,
  writeConfig,
  addServer,
  removeServer,
  saveProfile,
  loadProfile,
  listProfiles,
  detectFromPackageJson,
  detectFromRequirementsTxt,
  formatDetectionOutput,
  type McpServerConfig,
} from "./lib.js";

const CONFIG_PATH = process.env.MCP_CONFIG_PATH || "/app/mcp-config.json";
const PROFILES_DIR = process.env.PROFILES_DIR || "/app/profiles";
const WORKSPACE_DIR = process.env.HOST_WORKSPACE_DIR || "/workspace/host";

// ── Tool argument schemas (issue #106) ───────────────────────────────────
// Using Zod instead of `as unknown as T` so that invalid inputs surface as a
// clear validation error instead of undefined-access crashes at runtime.

const AddServerArgsSchema = z.object({
  name: z.string().min(1, "name must be a non-empty string"),
  command: z.string().min(1, "command must be a non-empty string"),
  args: z.array(z.string()).optional(),
  env: z.record(z.string(), z.string()).optional(),
  enabled: z.boolean().optional(),
});

const ServerNameArgsSchema = z.object({
  server_name: z.string().min(1, "server_name must be a non-empty string"),
});

const ProfileNameArgsSchema = z.object({
  profile_name: z.string().min(1, "profile_name must be a non-empty string"),
});

const DetectArgsSchema = z.object({
  path: z.string().optional(),
  autoAdd: z.boolean().optional(),
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

const server = new Server(
  {
    name: "airis-commands",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      // ── MCP Gateway Config Management ──
      {
        name: "airis_config_add_server",
        description: "Add a new MCP server to the gateway configuration. Specify the command (npx, uvx, node), args, and optional env vars. The server is enabled by default. Requires gateway restart. Use airis_mcp_detect first to auto-discover servers for your tech stack.",
        inputSchema: {
          type: "object",
          properties: {
            name: {
              type: "string",
              description: "Unique server name (e.g., 'my-server'). Must not already exist.",
            },
            command: {
              type: "string",
              description: "Command to launch the server (e.g., 'npx', 'uvx', 'node')",
            },
            args: {
              type: "array",
              items: { type: "string" },
              description: "Command arguments (e.g., ['-y', '@stripe/mcp', '--tools=all'])",
            },
            env: {
              type: "object",
              description: "Environment variables as key-value pairs. Use ${VAR_NAME} for values from host env.",
            },
            enabled: {
              type: "boolean",
              description: "Whether to enable immediately (default: true). Set false if env vars aren't configured yet.",
            },
          },
          required: ["name", "command", "args"],
        },
      },
      {
        name: "airis_config_remove_server",
        description: "Remove an MCP server from the gateway configuration permanently. This deletes the server entry from mcp-config.json. To disable without removing, edit mcp-config.json and set enabled=false.",
        inputSchema: {
          type: "object",
          properties: {
            server_name: {
              type: "string",
              description: "Server name to remove (must exist in config)",
            },
          },
          required: ["server_name"],
        },
      },

      // ── Profile Management ──
      {
        name: "airis_profile_save",
        description: "Save the entire current MCP configuration as a named profile. Profiles are stored in /app/profiles/ and can be loaded later to switch between different server configurations (e.g., 'minimal', 'full', 'project-x').",
        inputSchema: {
          type: "object",
          properties: {
            profile_name: {
              type: "string",
              description: "Profile name (e.g., 'minimal', 'full-stack', 'frontend-only')",
            },
          },
          required: ["profile_name"],
        },
      },
      {
        name: "airis_profile_load",
        description: "Load a saved profile, replacing the current MCP configuration entirely. Use airis_profile_list to see available profiles. Requires gateway restart to apply.",
        inputSchema: {
          type: "object",
          properties: {
            profile_name: {
              type: "string",
              description: "Profile name to load (must exist in profiles directory)",
            },
          },
          required: ["profile_name"],
        },
      },
      {
        name: "airis_profile_list",
        description: "List all saved MCP configuration profiles. Returns profile names that can be loaded with airis_profile_load.",
        inputSchema: {
          type: "object",
          properties: {},
          required: [],
        },
      },

      // ── Discovery ──
      {
        name: "airis_mcp_detect",
        description: "Scan a repository's package.json/requirements.txt to detect tech stack and suggest relevant MCP servers. For example, finding '@supabase/supabase-js' suggests adding the Supabase MCP server. Set autoAdd=true to automatically add detected servers (disabled by default, so you can set env vars first).",
        inputSchema: {
          type: "object",
          properties: {
            path: {
              type: "string",
              description: "Repository path to scan (default: /workspace/host). Must contain package.json or requirements.txt.",
            },
            autoAdd: {
              type: "boolean",
              description: "true = add detected servers to config (disabled, awaiting env vars). false = just show suggestions (default).",
            },
          },
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
      case "airis_config_add_server": {
        const { name: serverName, command, args: cmdArgs, env, enabled } =
          parseArgs(AddServerArgsSchema, args, "airis_config_add_server");

        await addServer(CONFIG_PATH, serverName, {
          command,
          args: cmdArgs || [],
          env: env ?? {} as Record<string, string>,
          enabled: enabled !== false,
        });

        return {
          content: [
            {
              type: "text",
              text: `Server "${serverName}" added to config. Restart API to apply.`,
            },
          ],
        };
      }

      case "airis_config_remove_server": {
        const { server_name: serverName } = parseArgs(
          ServerNameArgsSchema,
          args,
          "airis_config_remove_server",
        );
        await removeServer(CONFIG_PATH, serverName);

        return {
          content: [
            {
              type: "text",
              text: `Server "${serverName}" removed from config.`,
            },
          ],
        };
      }

      case "airis_profile_save": {
        const { profile_name: profileName } = parseArgs(
          ProfileNameArgsSchema,
          args,
          "airis_profile_save",
        );
        await saveProfile(CONFIG_PATH, PROFILES_DIR, profileName);

        return {
          content: [
            {
              type: "text",
              text: `Profile "${profileName}" saved.`,
            },
          ],
        };
      }

      case "airis_profile_load": {
        const { profile_name: profileName } = parseArgs(
          ProfileNameArgsSchema,
          args,
          "airis_profile_load",
        );
        await loadProfile(CONFIG_PATH, PROFILES_DIR, profileName);

        return {
          content: [
            {
              type: "text",
              text: `Profile "${profileName}" loaded. Restart API to apply.`,
            },
          ],
        };
      }

      case "airis_profile_list": {
        const profiles = await listProfiles(PROFILES_DIR);

        if (profiles.length === 0) {
          return {
            content: [{ type: "text", text: "No profiles saved yet." }],
          };
        }

        return {
          content: [
            {
              type: "text",
              text: `Saved profiles:\n${profiles.map((p) => `- ${p}`).join("\n")}`,
            },
          ],
        };
      }

      case "airis_mcp_detect": {
        const parsed = parseArgs(DetectArgsSchema, args, "airis_mcp_detect");
        const repoPath = parsed.path ?? WORKSPACE_DIR;
        const autoAdd = parsed.autoAdd ?? false;
        const config = await readConfig(CONFIG_PATH);

        const detected: Array<{
          name: string;
          reason: string;
          mcp: string;
          description: string;
          envRequired: string[];
          alreadyExists: boolean;
        }> = [];

        // Scan package.json
        try {
          const pkgPath = path.join(repoPath, "package.json");
          const pkgContent = await fs.readFile(pkgPath, "utf-8");
          detected.push(...detectFromPackageJson(pkgContent, config.mcpServers));
        } catch {
          // No package.json
        }

        // Check for .git directory
        try {
          await fs.access(path.join(repoPath, ".git"));
          const githubMapping = MCP_MAPPINGS.github;
          if (!detected.find(d => d.name === "github")) {
            detected.push({
              name: "github",
              reason: "Found .git directory",
              mcp: githubMapping.mcp,
              description: githubMapping.description,
              envRequired: githubMapping.envRequired,
              alreadyExists: !!config.mcpServers.github,
            });
          }
        } catch {
          // No .git directory
        }

        // Scan requirements.txt
        try {
          const reqPath = path.join(repoPath, "requirements.txt");
          const reqContent = await fs.readFile(reqPath, "utf-8");
          const alreadyDetected = detected.map(d => d.name);
          detected.push(...detectFromRequirementsTxt(reqContent, config.mcpServers, alreadyDetected));
        } catch {
          // No requirements.txt
        }

        // Scan manifest.toml (Airis workspace)
        try {
          const manifestPath = path.join(repoPath, "manifest.toml");
          await fs.access(manifestPath);
          const airisMapping = MCP_MAPPINGS["airis-workspace"];
          if (!detected.find(d => d.name === "airis-workspace")) {
            detected.push({
              name: "airis-workspace",
              reason: "Found manifest.toml",
              mcp: airisMapping.mcp,
              description: airisMapping.description,
              envRequired: airisMapping.envRequired,
              alreadyExists: !!config.mcpServers["airis-workspace"],
            });
          }
        } catch {
          // No manifest.toml
        }

        if (detected.length === 0) {
          return {
            content: [{
              type: "text",
              text: `No known MCPs detected in ${repoPath}.\n\nAvailable MCPs: ${Object.keys(MCP_MAPPINGS).join(", ")}`,
            }],
          };
        }

        // Auto-add new MCPs if requested
        if (autoAdd) {
          const newMcps = detected.filter(d => !d.alreadyExists);
          for (const mcp of newMcps) {
            const mapping = MCP_MAPPINGS[mcp.name];
            config.mcpServers[mcp.name] = {
              command: mapping.command,
              args: mapping.args,
              env: mapping.env,
              enabled: false,
            };
          }
          if (newMcps.length > 0) {
            await writeConfig(CONFIG_PATH, config);
          }
        }

        const output = formatDetectionOutput(detected, repoPath, autoAdd);

        return {
          content: [{ type: "text", text: output }],
        };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      content: [{ type: "text", text: `Error: ${message}` }],
      isError: true,
    };
  }
});

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("AIRIS Commands MCP server running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
