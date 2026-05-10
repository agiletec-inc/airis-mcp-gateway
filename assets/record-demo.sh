#!/bin/bash
# Record a real Claude Code demo and convert to GIF
# Usage: bash assets/record-demo.sh

set -e

CAST_FILE="assets/demo.cast"
GIF_FILE="assets/demo.gif"

echo "Recording Claude Code demo..."
echo "This will launch claude -p and capture the output."
echo ""

# Record with asciinema
asciinema rec "$CAST_FILE" \
  --cols 100 \
  --rows 28 \
  --overwrite \
  --command 'claude -p --dangerously-skip-permissions --model haiku "Use airis-exec to get the current time in UTC. Just call the tool and show me the result briefly."'

echo ""
echo "Recording complete. Converting to GIF..."

# Convert to GIF with agg
agg "$CAST_FILE" "$GIF_FILE" \
  --theme monokai \
  --font-size 16 \
  --speed 1.5 \
  --last-frame-duration 3

echo "Done! GIF saved to $GIF_FILE"
echo "Size: $(du -h "$GIF_FILE" | cut -f1)"
