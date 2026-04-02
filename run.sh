#!/bin/bash
# AI Dungeon Master - Startup Script
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"

# Uncomment and set your API key for AI narration:
# export ANTHROPIC_API_KEY=sk-ant-...

echo "Starting AI Dungeon Master..."
echo "Open http://localhost:8000 in your browser"
echo ""

python3 src/api/main.py
