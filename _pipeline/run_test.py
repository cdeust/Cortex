#!/usr/bin/env python3
"""Standalone runner for the Cortex run_pipeline handler — test with real LLM calls."""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server.handlers.run_pipeline import handler

os.environ["PIPELINE_COMPOUND_THRESHOLD"] = "0.2"
os.environ["PIPELINE_JACCARD_MIN"] = "0.01"


async def main():
    result = await handler(
        {
            "codebase_path": "/Users/cdeust/Developments/ai-architect-prd-builder",
            "task_path": "/Users/cdeust/Downloads/TechnicalVeil/2026-03-20/findings_parsed.json",
            "github_repo": "cdeust/ai-architect-prd-builder",
            "max_findings": 1,
        }
    )
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result.get("status") == "delivered" else 1)
