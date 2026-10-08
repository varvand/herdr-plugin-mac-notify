#!/usr/bin/env python3
"""Show a macOS banner when a Herdr agent finishes or needs input.

The in-app toast stays on. This only adds Notification Center, and it stays
quiet when that pane is the one you are already looking at.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WATCHED = {"blocked": "needs you", "done": "finished"}
FRONTMOST_TERMINALS = {
    "wezterm",
    "wezterm-gui",
    "terminal",
    "iterm2",
    "ghostty",
    "alacritty",
    "kitty",
}
RECHECK_SECONDS = 1
DEDUPE_SECONDS = 8


def herdr(*args: str) -> dict:
    binary = os.environ.get("HERDR_BIN_PATH") or "herdr"
    raw = subprocess.check_output([binary, *args], text=True, stderr=subprocess.DEVNULL)
    return json.loads(raw)


def snapshot() -> dict:
    return herdr("api", "snapshot")["result"]["snapshot"]


def pane_status(snap: dict, pane_id: str) -> str | None:
    for pane in snap.get("panes", []):
        if pane.get("pane_id") == pane_id:
            return str(pane.get("agent_status") or "").lower()
    return None


def workspace_label(snap: dict, workspace_id: str) -> str:
    for workspace in snap.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return str(workspace.get("label") or "")
    return ""


def terminal_is_frontmost() -> bool:
    script = (
        'tell application "System Events" to get name of first '
        "application process whose frontmost is true"
    )
    try:
        name = subprocess.check_output(
            ["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return name.casefold() in FRONTMOST_TERMINALS


def recently_sent(pane_id: str, status: str) -> bool:
    stamp = Path(f"/tmp/herdr-mac-notify-{pane_id}-{status}")
    now = time.time()
    if stamp.exists() and now - stamp.stat().st_mtime < DEDUPE_SECONDS:
        return True
    stamp.write_text(status)
    return False


def notify(title: str, body: str) -> None:
    subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "-e",
            "end run",
            title,
            body,
        ],
        check=False,
    )


def event_payload() -> dict:
    raw = os.environ.get("HERDR_PLUGIN_EVENT_JSON") or ""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    data = parsed.get("data")
    return data if isinstance(data, dict) else {}


def main() -> int:
    if os.environ.get("HERDR_MAC_NOTIFY_TEST") == "1":
        notify("Herdr", "Mac banners are on. An agent will ping you when it finishes or needs you.")
        return 0

    data = event_payload()
    status = str(data.get("agent_status") or "").lower()
    verb = WATCHED.get(status)
    pane_id = str(data.get("pane_id") or "")
    if not verb or not pane_id:
        return 0

    time.sleep(RECHECK_SECONDS)
    try:
        snap = snapshot()
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        snap = {}
    if pane_status(snap, pane_id) != status:
        return 0
    if pane_id == snap.get("focused_pane_id") and terminal_is_frontmost():
        return 0
    if recently_sent(pane_id, status):
        return 0

    agent = str(data.get("display_agent") or data.get("agent") or "Agent")
    detail = str(data.get("title") or "").strip()
    where = workspace_label(snap, str(data.get("workspace_id") or ""))
    body = " · ".join(part for part in (where, detail) if part) or "Herdr"
    notify(f"{agent} {verb}", body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
