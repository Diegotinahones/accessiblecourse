from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    destination = Path("openapi.json")
    destination.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main()
