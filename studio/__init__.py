"""Local recap operator console.

Launch from the repo root:

    python -m studio
    python -m studio --host 127.0.0.1 --port 8765
"""

from studio.app import app, main

__all__ = ["app", "main"]
