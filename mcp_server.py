#!/usr/bin/env python3
"""Entry point for the AI Dungeon Master MCP server."""

import os
import sys

# Ensure we're running from the project root
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.mcp.server import mcp, ensure_db

# Initialize database and SRD data on startup
ensure_db()

if __name__ == "__main__":
    mcp.run()
