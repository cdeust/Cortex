"""Disposable process for shared-store tests; no embeddings or model calls.

source: docs/shared-host-memory.md, exact storage visibility contract.
"""

import json
import os
import sys

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store, reset_shared_store


def main():
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    print(json.dumps({"pid": os.getpid(), "backend": type(store).__name__}), flush=True)
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request["operation"] == "write":
                result = store.insert_memory(
                    {
                        "content": request["content"],
                        "domain": "shared-host-test",
                        "source": request["source"],
                    }
                )
            else:
                result = store.get_memory(request["id"])
                if result:
                    result = {k: result.get(k) for k in ("id", "content", "source")}
            print(json.dumps(result), flush=True)
    finally:
        reset_shared_store()


if __name__ == "__main__":
    main()
