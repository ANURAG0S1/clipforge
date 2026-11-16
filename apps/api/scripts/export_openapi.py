"""Write the FastAPI OpenAPI schema to a file without needing live dependencies."""

import json
import sys
from pathlib import Path

from app.main import create_app


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: export_openapi.py <output.json>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
