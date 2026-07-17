#!/usr/bin/env python3
"""
Checks whether Apple's "Default roles and permissions in Apple Business" support
page has changed since the last recorded snapshot.

Used by .github/workflows/check-apple-roles.yml

Behavior:
  - Fetches the Apple support page and extracts the main content text.
  - Compares it (via hash) against a snapshot stored in the repo
    (data/apple-roles-snapshot.txt).
  - If it's the first run ever: just records the baseline, no diff.
  - If nothing changed: exits quietly.
  - If something changed: writes a unified diff to diff_output.txt (used as
    the body of a GitHub Issue by the workflow), updates the snapshot file,
    and sets GITHUB_OUTPUT `changed=true` so the workflow knows to open an
    issue and commit the new snapshot.

This script does NOT touch index.html. It only flags that something changed
on Apple's page so a human can review and manually update the DATA array +
LAST_VERIFIED_DATE constant in index.html if the permissions matrix itself
changed (Apple sometimes only tweaks unrelated text on the page).
"""

import difflib
import hashlib
import os
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://support.apple.com/guide/business/default-roles-and-permissions-axm27678acfb/1/web/1"
SNAPSHOT_PATH = Path("data/apple-roles-snapshot.txt")
DIFF_OUTPUT_PATH = Path("diff_output.txt")

HEADERS = {
    # A normal browser UA; Apple's support site can be picky about default
    # python/requests user agents and return a stripped-down page otherwise.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_page(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_relevant_text(html: str) -> str:
    """
    Extract the main article content, stripping nav/header/footer chrome so
    unrelated site changes (e.g. a footer link) don't trigger false positives.
    Falls back to the full page text if none of the expected containers exist,
    so the check still runs (just more sensitive to unrelated changes) rather
    than silently failing.
    """
    soup = BeautifulSoup(html, "html.parser")

    candidates = [
        soup.find("main"),
        soup.find(attrs={"role": "main"}),
        soup.find("article"),
        soup.find(id="content"),
    ]
    container = next((c for c in candidates if c is not None), soup)

    for tag in container.find_all(["script", "style", "nav", "svg", "img"]):
        tag.decompose()

    text = container.get_text(separator="\n")

    # Normalize whitespace so re-flowed/re-indented HTML doesn't count as a change
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def write_output(changed: bool) -> None:
    github_output_path = os.environ.get("GITHUB_OUTPUT")
    if not github_output_path:
        return
    with open(github_output_path, "a", encoding="utf-8") as fh:
        fh.write(f"changed={'true' if changed else 'false'}\n")


def main() -> int:
    try:
        html = fetch_page(URL)
    except requests.RequestException as exc:
        print(f"::error::Failed to fetch Apple support page: {exc}")
        # A network hiccup isn't a "content changed" event - fail the step so
        # it's visible in the Actions log, without opening a false-positive issue.
        return 1

    current_text = extract_relevant_text(html)
    current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text(current_text, encoding="utf-8")
        print("No previous snapshot found, recorded initial baseline.")
        write_output(changed=False)
        return 0

    previous_text = SNAPSHOT_PATH.read_text(encoding="utf-8")
    previous_hash = hashlib.sha256(previous_text.encode("utf-8")).hexdigest()

    if current_hash == previous_hash:
        print("No changes detected on Apple's roles & permissions page.")
        write_output(changed=False)
        return 0

    print("Change detected on Apple's roles & permissions page.")

    diff = difflib.unified_diff(
        previous_text.splitlines(),
        current_text.splitlines(),
        fromfile="previous (last verified)",
        tofile="current (just fetched)",
        lineterm="",
    )
    diff_text = "\n".join(diff)

    DIFF_OUTPUT_PATH.write_text(
        f"Source: {URL}\n\n"
        "The text content of Apple's roles & permissions guide has changed "
        "since the last check. Review the diff below, then manually update "
        "the `DATA` array and `LAST_VERIFIED_DATE` constant in `index.html` "
        "if the permissions matrix itself changed (not every text change on "
        "the page affects the matrix, Apple sometimes only tweaks a caption "
        "or unrelated paragraph).\n\n"
        "```diff\n"
        f"{diff_text}\n"
        "```\n",
        encoding="utf-8",
    )

    # Overwrite the snapshot so the next run diffs against this new version,
    # and this same change isn't reported again on the next scheduled run.
    SNAPSHOT_PATH.write_text(current_text, encoding="utf-8")

    write_output(changed=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
