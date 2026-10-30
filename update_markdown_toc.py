#!/usr/bin/env python3
"""Regenerate a Markdown TOC between <!-- TOC --> and <!-- /TOC -->.

Usage: python3 update_markdown_toc.py profiling_report_guide.md [--check]
Only level-two and level-three headings are included in the TOC.
"""

import argparse
from pathlib import Path
import re


START = "<!-- TOC -->"
END = "<!-- /TOC -->"


def update_toc(content):
    if content.count(START) != 1 or content.count(END) != 1:
        raise ValueError("Expected exactly one TOC marker pair")
    before, rest = content.split(START, 1)
    _, after = rest.split(END, 1)
    counts = {}
    entries = []
    fence = None
    in_comment = False
    for line in (before + after).splitlines():
        if fence is not None:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}\s*", line):
                fence = None
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if opening:
            marker = opening[1]
            fence = (marker[0], len(marker))
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        level, title = len(match[1]), match[2]
        slug = re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-")
        base = slug
        suffix = 0
        while slug in counts:
            suffix += 1
            slug = f"{base}-{suffix}"
        counts[slug] = True
        if 2 <= level <= 3 and title != "Contents":
            entries.append("  " * (level - 2) + f"- [{title}](#{slug})")
    return before + START + "\n\n" + "\n".join(entries) + "\n\n" + END + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--check", action="store_true", help="Check without editing")
    args = parser.parse_args()
    content = args.document.read_text(encoding="utf-8")
    try:
        updated = update_toc(content)
    except ValueError as error:
        parser.error(str(error))
    if args.check:
        if updated != content:
            parser.exit(1, "TOC is out of date\n")
        print("TOC is up to date")
    else:
        if updated != content:
            args.document.write_text(updated, encoding="utf-8")
        print(f"Updated TOC: {args.document}")


if __name__ == "__main__":
    main()
