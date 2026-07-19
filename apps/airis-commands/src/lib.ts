import * as fs from "fs/promises";
import * as path from "path";

// ── Types ──

export interface McpServerConfig {
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
}

export interface McpConfig {
  mcpServers: Record<string, McpServerConfig>;
  log?: { level: string };
}

export interface DetectedMcp {
  name: string;
  reason: string;
  mcp: string;
  description: string;
  envRequired: string[];
  alreadyExists: boolean;
}

export interface McpMapping {
  packages: string[];
  detect?: string[];
  mcp: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  envRequired: string[];
  description: string;
}

// ── MCP Mapping Database ──

export const MCP_MAPPINGS: Record<string, McpMapping> = {
  stripe: {
    packages: ["stripe", "@stripe/stripe-js"],
    mcp: "@stripe/mcp",
    command: "npx",
    args: ["-y", "@stripe/mcp", "--tools=all", "--api-key", "${STRIPE_SECRET_KEY}"],
    env: {},
    envRequired: ["STRIPE_SECRET_KEY"],
    description: "Stripe payments API",
  },
  twilio: {
    packages: ["twilio"],
    mcp: "@twilio-alpha/mcp",
    command: "npx",
    args: ["-y", "@twilio-alpha/mcp"],
    env: {
      TWILIO_ACCOUNT_SID: "${TWILIO_ACCOUNT_SID}",
      TWILIO_API_KEY: "${TWILIO_API_KEY}",
      TWILIO_API_SECRET: "${TWILIO_API_SECRET}",
    },
    envRequired: ["TWILIO_ACCOUNT_SID", "TWILIO_API_KEY", "TWILIO_API_SECRET"],
    description: "Twilio voice/SMS API",
  },
  supabase: {
    packages: ["@supabase/supabase-js", "@supabase/ssr"],
    mcp: "@supabase/mcp-server-supabase",
    command: "npx",
    args: ["-y", "@supabase/mcp-server-supabase@latest", "--access-token", "${SUPABASE_ACCESS_TOKEN}"],
    env: {},
    envRequired: ["SUPABASE_ACCESS_TOKEN"],
    description: "Supabase database management",
  },
  postgres: {
    packages: ["pg", "postgres", "@prisma/client", "drizzle-orm"],
    mcp: "@modelcontextprotocol/server-postgres",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-postgres", "${DATABASE_URL}"],
    env: {},
    envRequired: ["DATABASE_URL"],
    description: "Direct PostgreSQL access",
  },
  github: {
    packages: ["@octokit/rest", "octokit"],
    detect: [".git"],
    mcp: "@modelcontextprotocol/server-github",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-github"],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}" },
    envRequired: ["GITHUB_TOKEN"],
    description: "GitHub API",
  },
  cloudflare: {
    packages: ["@cloudflare/workers-types", "wrangler"],
    mcp: "@cloudflare/mcp-server-cloudflare",
    command: "npx",
    args: ["-y", "@cloudflare/mcp-server-cloudflare@latest"],
    env: {
      CLOUDFLARE_ACCOUNT_ID: "${CLOUDFLARE_ACCOUNT_ID}",
      CLOUDFLARE_API_TOKEN: "${CLOUDFLARE_API_TOKEN}",
    },
    envRequired: ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"],
    description: "Cloudflare Workers, KV, R2",
  },
  playwright: {
    packages: ["playwright", "@playwright/test"],
    mcp: "@playwright/mcp",
    command: "npx",
    args: ["-y", "@playwright/mcp@latest"],
    env: {},
    envRequired: [],
    description: "Browser automation",
  },
};

// ── Pure Functions ──

export function validateProfileName(name: string): boolean {
  return /^[a-zA-Z0-9_-]+$/.test(name);
}

export function detectFromPackageJson(
  pkgContent: string,
  existingServers: Record<string, McpServerConfig>,
): DetectedMcp[] {
  const pkg = JSON.parse(pkgContent);
  const allDeps: Record<string, string> = {
    ...pkg.dependencies,
    ...pkg.devDependencies,
  };

  const detected: DetectedMcp[] = [];
  for (const [mcpName, mapping] of Object.entries(MCP_MAPPINGS)) {
    for (const pkgName of mapping.packages) {
      if (allDeps[pkgName]) {
        detected.push({
          name: mcpName,
          reason: `Found "${pkgName}" in package.json`,
          mcp: mapping.mcp,
          description: mapping.description,
          envRequired: mapping.envRequired,
          alreadyExists: !!existingServers[mcpName],
        });
        break;
      }
    }
  }
  return detected;
}

export function detectFromRequirementsTxt(
  content: string,
  existingServers: Record<string, McpServerConfig>,
  alreadyDetected: string[] = [],
): DetectedMcp[] {
  const lines = content.split("\n");
  const detected: DetectedMcp[] = [];

  for (const [mcpName, mapping] of Object.entries(MCP_MAPPINGS)) {
    if (alreadyDetected.includes(mcpName)) continue;
    for (const pkgName of mapping.packages) {
      if (lines.some(line => line.toLowerCase().startsWith(pkgName.toLowerCase()))) {
        detected.push({
          name: mcpName,
          reason: `Found "${pkgName}" in requirements.txt`,
          mcp: mapping.mcp,
          description: mapping.description,
          envRequired: mapping.envRequired,
          alreadyExists: !!existingServers[mcpName],
        });
        break;
      }
    }
  }
  return detected;
}

export function formatDetectionOutput(
  detected: DetectedMcp[],
  repoPath: string,
  autoAdded: boolean,
): string {
  const newMcps = detected.filter(d => !d.alreadyExists);
  const existingMcps = detected.filter(d => d.alreadyExists);

  let output = `## Detected Tech Stack in ${repoPath}\n\n`;

  if (newMcps.length > 0) {
    output += `### ${autoAdded ? "Added" : "Suggested"} MCPs\n\n`;
    for (const mcp of newMcps) {
      output += `- **${mcp.name}**: ${mcp.description}\n`;
      output += `  - Reason: ${mcp.reason}\n`;
      output += `  - Package: \`${mcp.mcp}\`\n`;
      if (mcp.envRequired.length > 0) {
        output += `  - Required env: ${mcp.envRequired.map(e => `\`${e}\``).join(", ")}\n`;
      }
      output += "\n";
    }
    if (autoAdded) {
      output += `\n> ${newMcps.length} MCPs added (disabled). Set required env vars and restart to use.\n`;
    } else {
      output += `\n> Run with \`autoAdd: true\` to add these MCPs to config.\n`;
    }
  }

  if (existingMcps.length > 0) {
    output += `### Already Configured\n\n`;
    for (const mcp of existingMcps) {
      output += `- **${mcp.name}**: ${mcp.reason}\n`;
    }
  }

  return output;
}

// ── File I/O Functions ──

export async function readConfig(configPath: string): Promise<McpConfig> {
  const content = await fs.readFile(configPath, "utf-8");
  return JSON.parse(content);
}

export async function writeConfig(configPath: string, config: McpConfig): Promise<void> {
  await fs.writeFile(configPath, JSON.stringify(config, null, 2));
}

export async function addServer(
  configPath: string,
  name: string,
  server: McpServerConfig,
): Promise<void> {
  const config = await readConfig(configPath);
  if (config.mcpServers[name]) {
    throw new Error(`Server already exists: ${name}`);
  }
  config.mcpServers[name] = server;
  await writeConfig(configPath, config);
}

export async function removeServer(configPath: string, name: string): Promise<void> {
  const config = await readConfig(configPath);
  if (!config.mcpServers[name]) {
    throw new Error(`Server not found: ${name}`);
  }
  delete config.mcpServers[name];
  await writeConfig(configPath, config);
}

export async function saveProfile(
  configPath: string,
  profilesDir: string,
  profileName: string,
): Promise<void> {
  if (!validateProfileName(profileName)) {
    throw new Error(`Invalid profile name: "${profileName}". Only alphanumeric, hyphens, and underscores are allowed.`);
  }
  await fs.mkdir(profilesDir, { recursive: true });
  const config = await readConfig(configPath);
  const profilePath = path.join(profilesDir, `${profileName}.json`);
  await fs.writeFile(profilePath, JSON.stringify(config, null, 2));
}

export async function loadProfile(
  configPath: string,
  profilesDir: string,
  profileName: string,
): Promise<void> {
  if (!validateProfileName(profileName)) {
    throw new Error(`Invalid profile name: "${profileName}". Only alphanumeric, hyphens, and underscores are allowed.`);
  }
  const profilePath = path.join(profilesDir, `${profileName}.json`);
  const content = await fs.readFile(profilePath, "utf-8");
  const config = JSON.parse(content);
  await writeConfig(configPath, config);
}

export async function listProfiles(profilesDir: string): Promise<string[]> {
  await fs.mkdir(profilesDir, { recursive: true });
  const files = await fs.readdir(profilesDir);
  return files
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.replace(".json", ""));
}
