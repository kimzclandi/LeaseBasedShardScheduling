"""Check maintained entry-point links offline; frozen research documents are excluded.

Checks file targets, not heading anchors, external URLs or rendered layout.
Run from any directory with Python 3.10+; no third-party dependencies.
"""

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
DOCS = [
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "docs/MAINTAINING.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
]


def main():
    tracked = set(subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines())
    failures = []
    checked = 0
    for name in DOCS:
        path = ROOT / name
        if not path.is_file():
            failures.append(f"Missing required document: {name}")
            continue
        content = re.sub(r"```.*?```", "", path.read_text(), flags=re.DOTALL)
        targets = re.findall(r"\]\(([^\s)]+)(?:[ ]+[^)]*)?\)", content)
        targets += re.findall(r'(?:src|href)="([^"]+)"', content)
        for target in targets:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            resolved = (path.parent / unquote(parts.path)).resolve()
            if not resolved.is_relative_to(ROOT):
                failures.append(f"{name}: target escapes repository: {target}")
                continue
            relative = resolved.relative_to(ROOT).as_posix()
            checked += 1
            present = relative in tracked or any(
                item.startswith(relative.rstrip("/") + "/") for item in tracked
            )
            if not resolved.exists() or not present:
                failures.append(f"{name}: missing or untracked target: {target}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        f"Checked {len(DOCS)} maintained documents and {checked} local file links; "
        "external URLs and heading anchors not checked."
    )


if __name__ == "__main__":
    main()
