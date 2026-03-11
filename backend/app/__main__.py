"""Entry point: python -m app (from backend/) or python -m backend.app (from project root)."""
from pathlib import Path

import uvicorn

_backend_dir = str(Path(__file__).resolve().parent.parent)

uvicorn.run(
    "app.main:app",
    host="127.0.0.1",
    port=8000,
    reload=True,
    app_dir=_backend_dir,
)
