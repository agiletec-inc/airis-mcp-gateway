#!/bin/bash
# Multi-scenario live demo for README GIF
# Runs real Claude Code sessions, displays tool calls in real-time

C_CYAN='\033[0;36m'
C_YELLOW='\033[1;33m'
C_GREEN='\033[0;32m'
C_WHITE='\033[1;37m'
C_DIM='\033[2m'
C_BOLD='\033[1m'
C_RESET='\033[0m'

run_scenario() {
    local label="$1"
    local display_prompt="$2"
    local actual_prompt="$3"

    printf "\n${C_CYAN}━━━ %s ━━━${C_RESET}\n" "$label"
    printf "${C_DIM}\$ claude -p \"%s\"${C_RESET}\n\n" "$display_prompt"

    claude -p --dangerously-skip-permissions --model haiku --output-format stream-json "$actual_prompt" 2>/dev/null | \
    python3 -c "
import sys, json
seen = False
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: obj = json.loads(line)
    except: continue
    t = obj.get('type','')
    if t == 'assistant':
        for b in obj.get('message',{}).get('content',[]):
            if b.get('type') == 'tool_use':
                inp = b.get('input',{})
                tool = inp.get('tool','')
                args = inp.get('arguments',{})
                name = b['name'].split('__')[-1]
                if 'airis-exec' in b['name'] and tool:
                    args_s = json.dumps(args, ensure_ascii=False) if args else '{}'
                    print(f'\033[0;36m  ⚡ airis-exec\033[0m \033[1;33m{tool}\033[0m \033[2m{args_s}\033[0m')
                elif 'airis' in b['name']:
                    print(f'\033[0;36m  ⚡ {name}\033[0m')
    elif t == 'user':
        for b in obj.get('message',{}).get('content',[]):
            if b.get('type') == 'tool_result':
                c = b.get('content','')
                text = ''
                if isinstance(c, list):
                    for i in c:
                        if isinstance(i, dict) and i.get('text'): text = i['text']
                elif isinstance(c, str): text = c
                if text.strip() and 'completed with no output' not in text:
                    lines = text.strip().split('\n')[:2]
                    for l in lines:
                        print(f'\033[0;32m    ← {l[:80]}\033[0m')
    elif t == 'result':
        text = obj.get('result','')
        if text.strip() and not seen:
            seen = True
            lines = text.strip().split('\n')[:2]
            for l in lines:
                print(f'\033[1;37m  {l[:80]}\033[0m')
"
}

# Header
printf "${C_BOLD}${C_WHITE}AIRIS MCP Gateway${C_RESET} ${C_DIM}— Real Claude Code Demo${C_RESET}\n"
printf "${C_DIM}docker compose up -d && claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse${C_RESET}\n"
sleep 1

# Scenario 1: Look up library docs with context7
run_scenario \
    "Scenario 1: Library Docs Lookup (context7)" \
    "Look up Next.js docs" \
    "Use airis-exec to call context7:resolve-library-id with libraryName='nextjs'. Just call the tool and show the library ID. Be extremely brief, 1 line."

sleep 1

# Scenario 2: Knowledge graph (memory)
run_scenario \
    "Scenario 2: Knowledge Graph (memory)" \
    "Save a project note" \
    "Use airis-exec to call memory:create_entities with entities=[{\"name\":\"airis-gateway\",\"entityType\":\"project\",\"observations\":[\"MCP multiplexer with 60+ tools\"]}]. Just call the tool, show result briefly."

sleep 1

# Scenario 3: Read back
run_scenario \
    "Scenario 3: Read Knowledge Graph" \
    "What do you know?" \
    "Use airis-exec to call memory:read_graph. Show the entities you find. Be very brief."

sleep 1

# Cleanup
claude -p --dangerously-skip-permissions --model haiku --output-format stream-json "Use airis-exec to call memory:delete_entities with entityNames=[\"airis-gateway\"]. Just do it." 2>/dev/null > /dev/null

# Footer
printf "\n${C_GREEN}━━━ 60+ tools. 1 gateway. 1 call each. ━━━${C_RESET}\n"
sleep 3
