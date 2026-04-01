"""Persistent state stored in <repo_root>/.garrison/state.json."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Worker:
    id: int
    branch: str
    worktree: str        # absolute path to the worktree
    window: int          # tmux window index
    status: str          # "waiting" | "idle" | "error"
    created_at: str
    watch_window: int | None = None  # tmux window index for yarn run watch, if active
    session_started: bool = False    # whether a claude session has been started


@dataclass
class State:
    session: str
    repo: str
    next_id: int = 1
    workers: list[Worker] = field(default_factory=list)


def _state_path(repo_root: str) -> Path:
    return Path(repo_root) / ".garrison" / "state.json"


def load(repo_root: str) -> State | None:
    path = _state_path(repo_root)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    workers = [Worker(**w) for w in data.get("workers", [])]
    return State(
        session=data["session"],
        repo=data["repo"],
        next_id=data.get("next_id", len(workers) + 1),
        workers=workers,
    )


def save(state: State) -> None:
    path = _state_path(state.repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "session": state.session,
        "repo": state.repo,
        "next_id": state.next_id,
        "workers": [asdict(w) for w in state.workers],
    }
    path.write_text(json.dumps(data, indent=2))


def find_repo_root() -> str | None:
    """Walk up from cwd looking for a .git directory."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return str(parent)
    return None


def make_session_name(repo_root: str) -> str:
    slug = Path(repo_root).name.replace(".", "-").replace(" ", "-")
    return f"garrison-{slug}"


def add_worker(state: State, branch: str, worktree: str, window: int, created_at: str) -> Worker:
    worker = Worker(
        id=state.next_id,
        branch=branch,
        worktree=worktree,
        window=window,
        status="waiting",
        created_at=created_at,
    )
    state.next_id += 1
    state.workers.append(worker)
    return worker


def remove_worker(state: State, worker_id: int) -> None:
    state.workers = [w for w in state.workers if w.id != worker_id]


def update_worker_status(state: State, worker_id: int, status: str) -> None:
    for worker in state.workers:
        if worker.id == worker_id:
            worker.status = status
            return
