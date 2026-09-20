"""Validate maintained local file links and Markdown heading fragments offline.

Inline Markdown/HTML links and ATX/setext headings are supported. External URLs,
reference-style links, rendered layout and non-Markdown fragments are not checked.
"""

import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", "README.en.md"]
OPTIONAL_DOCS = []


def without_fences(content):
    lines = []
    fence = None
    for line in content.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                fence = None
            continue
        if match:
            fence = match[1]
        else:
            lines.append(line)
    return "\n".join(lines)


def heading_ids(content):
    """GitHub-style IDs for ordinary Markdown headings, including duplicates."""
    text = without_fences(content)
    anchors = set(re.findall(r'(?:id|name)=["\']([^"\']+)["\']', text))
    used = set()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        title = match[1] if match else None
        if (
            title is None
            and index + 1 < len(lines)
            and line.strip()
            and re.fullmatch(r" {0,3}(?:=+|-+)\s*", lines[index + 1])
        ):
            title = line.strip()
        if title is None:
            continue
        title = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", title)
        title = re.sub(r"<[^>]*>", "", title).lower()
        slug = "".join(
            c for c in title if c in "-_ " or unicodedata.category(c)[0] not in "PS"
        ).replace(" ", "-")
        candidate = slug
        suffix = 0
        while candidate in used:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        used.add(candidate)
        anchors.add(candidate)
    return anchors


def check_documents(root, docs, tracked):
    root = root.resolve()
    failures = []
    checked = 0
    fragments = 0
    for name in dict.fromkeys(docs):
        path = root / name
        if not path.is_file():
            failures.append(f"Missing required document: {name}")
            continue
        content = without_fences(path.read_text())
        targets = re.findall(r"\]\(([^\s)]+)(?:[ ]+[^)]*)?\)", content)
        targets += re.findall(r'(?:src|href)="([^"]+)"', content)
        for target in targets:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                continue
            resolved = (
                (path.parent / unquote(parts.path)).resolve() if parts.path else path.resolve()
            )
            if not resolved.is_relative_to(root):
                failures.append(f"{name}: target escapes repository: {target}")
                continue
            relative = resolved.relative_to(root).as_posix()
            checked += 1
            present = relative in tracked or any(
                item.startswith(relative.rstrip("/") + "/") for item in tracked
            )
            if not resolved.exists() or not present:
                failures.append(f"{name}: missing or untracked target: {target}")
                continue
            if parts.fragment and resolved.is_file() and resolved.suffix.lower() == ".md":
                fragments += 1
                if unquote(parts.fragment) not in heading_ids(resolved.read_text()):
                    failures.append(f"{name}: missing heading: {target}")
    return failures, checked, fragments


def main():
    tracked = set(
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT, text=True).split("\0")
    )
    docs = list(dict.fromkeys(DOCS + [p for p in OPTIONAL_DOCS if (ROOT / p).exists()]))
    failures, checked, fragments = check_documents(ROOT, docs, tracked)
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        f"Checked {len(docs)} maintained documents, {checked} local links and "
        f"{fragments} Markdown fragments; external URLs and rendered layout not checked."
    )


if __name__ == "__main__":
    main()
