"""Entry point — detect repo, start or attach to tmux session."""

import shutil
import sys

from garrison import state as st
from garrison import tmux


def _ensure_gitexclude(repo_root: str) -> None:
    import os
    exclude = os.path.join(repo_root, ".git", "info", "exclude")
    try:
        content = open(exclude).read() if os.path.exists(exclude) else ""
        for entry in (".garrison/", ".claude/"):
            if entry not in content:
                with open(exclude, "a") as f:
                    f.write(f"\n{entry}\n")
    except OSError:
        pass


def main() -> None:
    repo_root = st.find_repo_root()
    if not repo_root:
        print("garrison: not inside a git repository", file=sys.stderr)
        sys.exit(1)

    session_name = st.make_session_name(repo_root)
    existing = st.load(repo_root)

    if tmux.has_session(session_name):
        tmux.attach_session(session_name)
        return

    tmux.new_session(session_name, repo_root)
    _ensure_gitexclude(repo_root)

    app_state = existing or st.State(session=session_name, repo=repo_root)
    app_state.session = session_name

    tmux.rename_window(session_name, 0, "garrison")
    st.save(app_state)

    garrison_bin = shutil.which("garrison") or sys.argv[0]
    tmux._run(
        "send-keys", "-t", f"{session_name}:0",
        f"{garrison_bin} --commander-internal {repo_root}", "Enter"
    )

    tmux.attach_session(session_name)


def commander_internal(repo_root: str) -> None:
    """Run the Textual garrison app directly (called inside tmux window 0)."""
    app_state = st.load(repo_root)
    if not app_state:
        print("garrison: no state found", file=sys.stderr)
        sys.exit(1)

    # Restore worker windows that no longer exist in tmux
    for worker in app_state.workers:
        if not tmux.window_alive(app_state.session, worker.window):
            try:
                cmd = f"claude --resume {worker.branch}" if worker.session_started else f"claude --name {worker.branch}"
                new_idx = tmux.new_window(
                    session=app_state.session,
                    name=f"worker/{worker.branch}",
                    start_dir=worker.worktree,
                    command=cmd,
                )
                worker.window = new_idx
            except Exception:
                worker.status = "error"
        # Watch windows are never auto-restored
        worker.watch_window = None

    st.save(app_state)

    from garrison.manager import GarrisonApp
    GarrisonApp(app_state).run()


def reset(repo_root: str) -> None:
    """Kill the tmux session and wipe state."""
    session_name = st.make_session_name(repo_root)
    if tmux.has_session(session_name):
        tmux._run("kill-session", "-t", session_name)
        print(f"garrison: killed session '{session_name}'")

    import os
    garrison_dir = f"{repo_root}/.garrison"
    if os.path.exists(garrison_dir):
        shutil.rmtree(garrison_dir)
        print(f"garrison: removed {garrison_dir}")

    print("garrison: reset complete")


def entry() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--commander-internal":
        commander_internal(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "reset":
        repo_root = st.find_repo_root()
        if not repo_root:
            print("garrison: not inside a git repository", file=sys.stderr)
            sys.exit(1)
        reset(repo_root)
    else:
        main()
