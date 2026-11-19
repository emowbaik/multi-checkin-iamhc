"""Non-interactive entry point for the Boterdrop solver.

The upstream api_server.py always blocks on interactive config prompts, which
hangs under systemd/CI. This launcher reads the environment instead.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402
from api_server import create_app  # noqa: E402

PROXY = os.environ.get("PROXY", "").strip()
if PROXY:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxies.txt"), "w") as fh:
        fh.write(PROXY + "\n")

app = create_app(
    headless=True,
    thread=2,
    page_count=2,
    proxy_support=bool(PROXY),
    proxy_file="proxies.txt",
    cleanup_interval_minutes=10,
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SOLVER_PORT", "8123")),
                log_level="warning")
