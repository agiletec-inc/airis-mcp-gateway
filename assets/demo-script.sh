#!/bin/bash
# Fake demo script for VHS recording
# Simulates the setup + one-call workflow

COLOR_GREEN='\033[0;32m'
COLOR_CYAN='\033[0;36m'
COLOR_YELLOW='\033[1;33m'
COLOR_WHITE='\033[1;37m'
COLOR_DIM='\033[2m'
COLOR_RESET='\033[0m'

fake_type() {
  printf "${COLOR_WHITE}"
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.03
  done
  printf "${COLOR_RESET}\n"
  sleep 0.3
}

section() {
  printf "\n${COLOR_CYAN}$1${COLOR_RESET}\n"
  sleep 0.5
}

# Step 1
section "# 1. Start the gateway"
fake_type '$ docker compose up -d'
sleep 0.3
printf "${COLOR_DIM}[+] Running 4/4${COLOR_RESET}\n"
printf " ${COLOR_GREEN}✔${COLOR_RESET} Container mindbase-postgres-dev  ${COLOR_GREEN}Healthy${COLOR_RESET}\n"
printf " ${COLOR_GREEN}✔${COLOR_RESET} Container airis-mcp-gateway-core ${COLOR_GREEN}Healthy${COLOR_RESET}\n"
printf " ${COLOR_GREEN}✔${COLOR_RESET} Container airis-serena           ${COLOR_GREEN}Healthy${COLOR_RESET}\n"
printf " ${COLOR_GREEN}✔${COLOR_RESET} Container airis-mcp-gateway      ${COLOR_GREEN}Healthy${COLOR_RESET}\n"
sleep 1.5

# Step 2
section "# 2. Register with Claude Code"
fake_type '$ claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse'
sleep 0.3
printf "${COLOR_GREEN}✔${COLOR_RESET} Added sse MCP server airis-mcp-gateway for user\n"
sleep 1.5

# Step 3
section "# 3. That's it — 60+ tools via 7 meta-tools (97% token savings)"
sleep 1
printf "\n"
printf "${COLOR_WHITE}  Traditional MCP:  ${COLOR_YELLOW}60+ tools × ~700 tokens = ~42,000 tokens${COLOR_RESET}\n"
printf "${COLOR_WHITE}  Dynamic MCP:      ${COLOR_GREEN} 7  tools × ~200 tokens =  ~1,400 tokens${COLOR_RESET}\n"
sleep 2

# Step 4
section "# 4. One-call workflow — no discovery step needed"
sleep 0.5
printf "\n"
printf "${COLOR_DIM}  airis-exec description includes:${COLOR_RESET}\n"
printf "${COLOR_WHITE}  Available tools:${COLOR_RESET}\n"
printf "  ${COLOR_DIM}[memory]${COLOR_RESET}  create_entities, search_nodes, add_observations\n"
printf "  ${COLOR_DIM}[tavily]${COLOR_RESET}  tavily-search, tavily-extract\n"
printf "  ${COLOR_DIM}[stripe]${COLOR_RESET}  create_customer, create_payment_intent, ...\n"
printf "  ${COLOR_DIM}[context7]${COLOR_RESET} resolve-library-id, query-docs\n"
printf "  ${COLOR_DIM}[supabase]${COLOR_RESET} query, list_tables, describe_table\n"
printf "  ${COLOR_DIM}  ... 60+ tools across 20 servers${COLOR_RESET}\n"
sleep 2.5

# Step 5
section "# 5. Example: Claude calls a tool directly"
sleep 0.5
printf "\n"
printf "  ${COLOR_DIM}User:${COLOR_RESET}  ${COLOR_WHITE}\"Search the web for MCP best practices\"${COLOR_RESET}\n"
sleep 1
printf "\n"
printf "  ${COLOR_DIM}Claude:${COLOR_RESET} ${COLOR_CYAN}airis-exec${COLOR_RESET}"
printf " tool=${COLOR_YELLOW}\"tavily:tavily-search\"${COLOR_RESET}"
printf " arguments=${COLOR_YELLOW}{\"query\": \"...\"}${COLOR_RESET}\n"
sleep 0.8
printf "  ${COLOR_DIM}  → cold server auto-starts → executes → returns results${COLOR_RESET}\n"
printf "  ${COLOR_GREEN}  ✔ Done in 1 call${COLOR_RESET}\n"
sleep 3
