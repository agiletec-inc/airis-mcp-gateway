import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as fs from "fs/promises";
import * as path from "path";
import * as os from "os";

import {
  validateProfileName,
  detectFromPackageJson,
  detectFromRequirementsTxt,
  formatDetectionOutput,
  readConfig,
  writeConfig,
  addServer,
  removeServer,
  saveProfile,
  loadProfile,
  listProfiles,
  type McpConfig,
  type DetectedMcp,
} from "./lib.js";

// ── Helpers ──

let tmpDir: string;

beforeEach(async () => {
  tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "airis-test-"));
});

afterEach(async () => {
  await fs.rm(tmpDir, { recursive: true, force: true });
});

function configPath(): string {
  return path.join(tmpDir, "mcp-config.json");
}

function profilesDir(): string {
  return path.join(tmpDir, "profiles");
}

async function writeTestConfig(config: McpConfig): Promise<string> {
  const p = configPath();
  await fs.writeFile(p, JSON.stringify(config, null, 2));
  return p;
}

const EMPTY_CONFIG: McpConfig = { mcpServers: {} };

const CONFIG_WITH_SERVERS: McpConfig = {
  mcpServers: {
    stripe: {
      command: "npx",
      args: ["-y", "@stripe/mcp"],
      env: {},
      enabled: true,
    },
    memory: {
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-memory"],
      env: {},
      enabled: true,
    },
  },
};

// ── validateProfileName ──

describe("validateProfileName", () => {
  it("accepts alphanumeric with hyphens and underscores", () => {
    expect(validateProfileName("my-profile")).toBe(true);
    expect(validateProfileName("test_123")).toBe(true);
    expect(validateProfileName("PROD")).toBe(true);
    expect(validateProfileName("a")).toBe(true);
  });

  it("rejects path traversal", () => {
    expect(validateProfileName("../escape")).toBe(false);
    expect(validateProfileName("../../etc/passwd")).toBe(false);
  });

  it("rejects special characters", () => {
    expect(validateProfileName("has space")).toBe(false);
    expect(validateProfileName("a/b")).toBe(false);
    expect(validateProfileName("a.b")).toBe(false);
    expect(validateProfileName("")).toBe(false);
  });
});

// ── detectFromPackageJson ──

describe("detectFromPackageJson", () => {
  it("detects stripe from dependencies", () => {
    const pkg = JSON.stringify({
      dependencies: { stripe: "^14.0.0" },
    });
    const result = detectFromPackageJson(pkg, {});
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("stripe");
    expect(result[0].reason).toContain("stripe");
    expect(result[0].alreadyExists).toBe(false);
  });

  it("detects supabase from devDependencies", () => {
    const pkg = JSON.stringify({
      devDependencies: { "@supabase/supabase-js": "^2.0.0" },
    });
    const result = detectFromPackageJson(pkg, {});
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("supabase");
  });

  it("detects multiple MCPs", () => {
    const pkg = JSON.stringify({
      dependencies: {
        stripe: "^14.0.0",
        "@supabase/supabase-js": "^2.0.0",
        playwright: "^1.40.0",
      },
    });
    const result = detectFromPackageJson(pkg, {});
    const names = result.map(d => d.name);
    expect(names).toContain("stripe");
    expect(names).toContain("supabase");
    expect(names).toContain("playwright");
  });

  it("marks existing servers as alreadyExists", () => {
    const pkg = JSON.stringify({
      dependencies: { stripe: "^14.0.0" },
    });
    const existing = {
      stripe: { command: "npx", args: [], env: {}, enabled: true },
    };
    const result = detectFromPackageJson(pkg, existing);
    expect(result[0].alreadyExists).toBe(true);
  });

  it("returns empty for unrelated packages", () => {
    const pkg = JSON.stringify({
      dependencies: { lodash: "^4.0.0", express: "^4.18.0" },
    });
    const result = detectFromPackageJson(pkg, {});
    expect(result).toHaveLength(0);
  });

  it("returns empty for package.json with no dependencies", () => {
    const pkg = JSON.stringify({ name: "my-app" });
    const result = detectFromPackageJson(pkg, {});
    expect(result).toHaveLength(0);
  });
});

// ── detectFromRequirementsTxt ──

describe("detectFromRequirementsTxt", () => {
  it("detects postgres from pg package", () => {
    const content = "flask==3.0.0\npg==0.8.0\nrequests==2.31.0";
    const result = detectFromRequirementsTxt(content, {});
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("postgres");
  });

  it("handles case-insensitive matching", () => {
    const content = "Pg==0.8.0";
    const result = detectFromRequirementsTxt(content, {});
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("postgres");
  });

  it("skips already-detected MCPs", () => {
    const content = "pg==0.8.0";
    const result = detectFromRequirementsTxt(content, {}, ["postgres"]);
    expect(result).toHaveLength(0);
  });

  it("returns empty for unrelated packages", () => {
    const content = "flask==3.0.0\nrequests==2.31.0";
    const result = detectFromRequirementsTxt(content, {});
    expect(result).toHaveLength(0);
  });
});

// ── formatDetectionOutput ──

describe("formatDetectionOutput", () => {
  const newMcp: DetectedMcp = {
    name: "stripe",
    reason: 'Found "stripe" in package.json',
    mcp: "@stripe/mcp",
    description: "Stripe payments API",
    envRequired: ["STRIPE_SECRET_KEY"],
    alreadyExists: false,
  };

  const existingMcp: DetectedMcp = {
    name: "supabase",
    reason: 'Found "@supabase/supabase-js" in package.json',
    mcp: "@supabase/mcp-server-supabase",
    description: "Supabase database management",
    envRequired: ["SUPABASE_ACCESS_TOKEN"],
    alreadyExists: true,
  };

  it("shows Suggested section for new MCPs", () => {
    const output = formatDetectionOutput([newMcp], "/repo", false);
    expect(output).toContain("### Suggested MCPs");
    expect(output).toContain("**stripe**");
    expect(output).toContain("`STRIPE_SECRET_KEY`");
    expect(output).toContain("autoAdd: true");
  });

  it("shows Added section when autoAdded", () => {
    const output = formatDetectionOutput([newMcp], "/repo", true);
    expect(output).toContain("### Added MCPs");
    expect(output).toContain("1 MCPs added (disabled)");
  });

  it("shows Already Configured section", () => {
    const output = formatDetectionOutput([existingMcp], "/repo", false);
    expect(output).toContain("### Already Configured");
    expect(output).toContain("**supabase**");
  });

  it("shows both sections for mixed results", () => {
    const output = formatDetectionOutput([newMcp, existingMcp], "/repo", false);
    expect(output).toContain("### Suggested MCPs");
    expect(output).toContain("### Already Configured");
  });
});

// ── Config File Operations ──

describe("readConfig / writeConfig", () => {
  it("round-trips config through file system", async () => {
    const p = await writeTestConfig(CONFIG_WITH_SERVERS);
    const loaded = await readConfig(p);
    expect(loaded.mcpServers.stripe.command).toBe("npx");
    expect(loaded.mcpServers.memory.enabled).toBe(true);
  });

  it("writeConfig creates valid JSON", async () => {
    const p = configPath();
    await writeConfig(p, CONFIG_WITH_SERVERS);
    const raw = await fs.readFile(p, "utf-8");
    const parsed = JSON.parse(raw);
    expect(parsed.mcpServers.stripe).toBeDefined();
  });
});

describe("addServer", () => {
  it("adds a server to config file", async () => {
    const p = await writeTestConfig(EMPTY_CONFIG);
    await addServer(p, "test-server", {
      command: "npx",
      args: ["-y", "test-pkg"],
      env: {},
      enabled: true,
    });

    const config = await readConfig(p);
    expect(config.mcpServers["test-server"]).toBeDefined();
    expect(config.mcpServers["test-server"].command).toBe("npx");
  });

  it("throws on duplicate server name", async () => {
    const p = await writeTestConfig(CONFIG_WITH_SERVERS);
    await expect(
      addServer(p, "stripe", { command: "npx", args: [], env: {}, enabled: true })
    ).rejects.toThrow("Server already exists: stripe");
  });
});

describe("removeServer", () => {
  it("removes a server from config file", async () => {
    const p = await writeTestConfig(CONFIG_WITH_SERVERS);
    await removeServer(p, "stripe");

    const config = await readConfig(p);
    expect(config.mcpServers.stripe).toBeUndefined();
    expect(config.mcpServers.memory).toBeDefined();
  });

  it("throws on non-existent server", async () => {
    const p = await writeTestConfig(EMPTY_CONFIG);
    await expect(removeServer(p, "ghost")).rejects.toThrow("Server not found: ghost");
  });
});

// ── Profile Operations ──

describe("saveProfile", () => {
  it("saves config as a profile file", async () => {
    const p = await writeTestConfig(CONFIG_WITH_SERVERS);
    const dir = profilesDir();

    await saveProfile(p, dir, "my-profile");

    const profilePath = path.join(dir, "my-profile.json");
    const content = JSON.parse(await fs.readFile(profilePath, "utf-8"));
    expect(content.mcpServers.stripe).toBeDefined();
  });

  it("rejects invalid profile names", async () => {
    const p = await writeTestConfig(EMPTY_CONFIG);
    await expect(saveProfile(p, profilesDir(), "../escape")).rejects.toThrow("Invalid profile name");
    await expect(saveProfile(p, profilesDir(), "has space")).rejects.toThrow("Invalid profile name");
  });
});

describe("loadProfile", () => {
  it("overwrites config with profile content", async () => {
    const p = await writeTestConfig(EMPTY_CONFIG);
    const dir = profilesDir();
    await fs.mkdir(dir, { recursive: true });

    // Save a profile with servers
    await fs.writeFile(
      path.join(dir, "full.json"),
      JSON.stringify(CONFIG_WITH_SERVERS, null, 2),
    );

    await loadProfile(p, dir, "full");

    const config = await readConfig(p);
    expect(config.mcpServers.stripe).toBeDefined();
    expect(config.mcpServers.memory).toBeDefined();
  });

  it("throws on non-existent profile", async () => {
    const p = await writeTestConfig(EMPTY_CONFIG);
    await expect(loadProfile(p, profilesDir(), "ghost")).rejects.toThrow();
  });

  it("rejects invalid profile names", async () => {
    const p = await writeTestConfig(EMPTY_CONFIG);
    await expect(loadProfile(p, profilesDir(), "a/b")).rejects.toThrow("Invalid profile name");
  });
});

describe("listProfiles", () => {
  it("returns empty array for empty directory", async () => {
    const profiles = await listProfiles(profilesDir());
    expect(profiles).toEqual([]);
  });

  it("lists profile names without .json extension", async () => {
    const dir = profilesDir();
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, "minimal.json"), "{}");
    await fs.writeFile(path.join(dir, "full.json"), "{}");
    await fs.writeFile(path.join(dir, "README.md"), "ignore me");

    const profiles = await listProfiles(dir);
    expect(profiles).toContain("minimal");
    expect(profiles).toContain("full");
    expect(profiles).not.toContain("README");
    expect(profiles).toHaveLength(2);
  });
});
