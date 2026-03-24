#!/usr/bin/env python3
"""Verify that module/service READMEs have required sections in order.

Required sections (vision/documentation.md):
  1. Title (#)
  2. Overview (## Overview)
  3. Quick Start (## Quick Start)
  4. Architecture (## Architecture)
  5. Configuration Reference (## Configuration Reference)
  6. Testing (## Testing)
  7. Going Further (## Going Further)

Exits non-zero if any README under modules/ or services/ is non-compliant.
"""

import pathlib
import re
import sys

REQUIRED_SECTIONS = [
    "Overview",
    "Quick Start",
    "Architecture",
    "Configuration Reference",
    "Testing",
    "Going Further",
]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def check_readme(path: pathlib.Path) -> list[str]:
    """Return a list of compliance errors for the given README."""
    errors = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not lines:
        errors.append(f"{path}: file is empty")
        return errors

    first_heading = HEADING_RE.match(lines[0])
    if not first_heading or first_heading.group(1) != "#":
        errors.append(f"{path}: first line must be a single # title heading")

    h2_sections = []
    for line in lines:
        m = HEADING_RE.match(line)
        if m and m.group(1) == "##":
            h2_sections.append(m.group(2).strip())

    last_idx = -1
    for required in REQUIRED_SECTIONS:
        try:
            idx = h2_sections.index(required)
        except ValueError:
            errors.append(f"{path}: missing required section '## {required}'")
            continue
        if idx <= last_idx:
            errors.append(f"{path}: section '## {required}' is out of order")
        last_idx = idx

    return errors


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[2]
    readme_paths = sorted(
        list(root.glob("modules/*/README.md")) + list(root.glob("services/*/README.md"))
    )

    if not readme_paths:
        print("No module/service READMEs found — skipping section check.")
        return 0

    all_errors = []
    for p in readme_paths:
        all_errors.extend(check_readme(p))

    if all_errors:
        for e in all_errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    print(f"OK: {len(readme_paths)} README(s) passed section order check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
