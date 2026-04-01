"""Thin wrapper around the tmux CLI."""

import subprocess
from dataclasses import dataclass


@dataclass
class Window:
    index: int
    name: str
    active: bool


def _run(*args: str) -> str:
    result = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _check(*args: str) -> bool:
    result = subprocess.run(
        ["tmux", *args],
        capture_output=True,
    )
    return result.returncode == 0


def has_session(name: str) -> bool:
    return _check("has-session", "-t", name)


def new_session(name: str, start_dir: str) -> None:
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", start_dir],
        check=True,
    )
    _run("set-option", "-t", name, "-g", "mouse", "on")


def attach_session(name: str) -> None:
    subprocess.run(["tmux", "attach-session", "-t", name])


def new_window(session: str, name: str, start_dir: str, command: str) -> int:
    """Create a new window in the background and return its index."""
    _run("new-window", "-d", "-t", session, "-n", name, "-c", start_dir)
    output = _run(
        "list-windows", "-t", session,
        "-F", "#{window_index}:#{window_name}"
    )
    for line in output.splitlines():
        idx, wname = line.split(":", 1)
        if wname == name:
            if command:
                _run("send-keys", "-t", f"{session}:{idx}", command, "Enter")
            return int(idx)
    raise RuntimeError(f"Could not find window '{name}' in session '{session}'")


def switch_client(session: str, index: int) -> None:
    subprocess.run(
        ["tmux", "select-window", "-t", f"{session}:{index}"],
    )


def list_windows(session: str) -> list[Window]:
    output = _run(
        "list-windows", "-t", session,
        "-F", "#{window_index}:#{window_name}:#{window_active}"
    )
    if not output:
        return []
    windows = []
    for line in output.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3:
            windows.append(Window(
                index=int(parts[0]),
                name=parts[1],
                active=parts[2] == "1",
            ))
    return windows


def kill_window(session: str, index: int) -> None:
    _run("kill-window", "-t", f"{session}:{index}")


def window_alive(session: str, index: int) -> bool:
    windows = list_windows(session)
    return any(w.index == index for w in windows)


def rename_window(session: str, index: int, name: str) -> None:
    _run("rename-window", "-t", f"{session}:{index}", name)
