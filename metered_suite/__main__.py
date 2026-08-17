from __future__ import annotations

import json
import sys
from pathlib import Path

from .run import run_suite
from .tasks import suite_lock

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"-h", "--help", "help"}:
        print(
            "metered-suite — official jobs for Metered pricing.\n"
            "\n"
            "  python3 -m metered_suite        run after editing main.py\n"
            "  python3 -m metered_suite lock   rewrite lock.json (maintainers)\n"
        )
        return
    if args and args[0] == "lock":
        lock = suite_lock()
        path = ROOT / "lock.json"
        path.write_text(json.dumps(lock, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}  {lock['suiteVersion']}  {lock['suiteHash'][:16]}…")
        return
    run_suite(ROOT)


if __name__ == "__main__":
    main()
