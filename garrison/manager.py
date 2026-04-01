"""Textual TUI — the garrison commander running in tmux window 0."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, ListView, ListItem, RichLog, Static

from garrison import state as st
from garrison import tmux

STATUS_LABELS = {
    "waiting": "[green]waiting for input[/green]",
    "idle":    "[dim]idle[/dim]",
    "error":   "[red]error[/red]",
}


class BranchExistsScreen(ModalScreen[str | None]):
    """Ask whether to continue on existing branch or create a new one."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    def __init__(self, branch: str) -> None:
        super().__init__()
        self._branch = branch

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Branch [bold]{self._branch}[/bold] already exists", id="dialog-title")
            with Horizontal(id="dialog-buttons"):
                yield Button("Continue on it", variant="primary", id="continue")
                yield Button("New branch", id="new")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#continue")
    def do_continue(self) -> None:
        self.dismiss(self._branch)

    @on(Button.Pressed, "#new")
    def do_new(self) -> None:
        self.dismiss(f"__new__:{self._branch}")

    @on(Button.Pressed, "#cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class CommitMessageScreen(ModalScreen[str | None]):
    """Modal that asks for a commit message."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Commit message", id="dialog-title")
            yield Input(placeholder="fix: do the thing", id="commit-input")
            with Horizontal(id="dialog-buttons"):
                yield Button("Publish", variant="primary", id="publish")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#commit-input", Input).focus()

    @on(Button.Pressed, "#publish")
    def do_publish(self) -> None:
        value = self.query_one("#commit-input", Input).value.strip()
        if value:
            self.dismiss(value)

    @on(Button.Pressed, "#cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def on_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class _ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "dismiss_false", show=False)]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._message, id="dialog-title")
            with Horizontal(id="dialog-buttons"):
                yield Button("Yes", variant="primary", id="yes")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#yes")
    def do_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def do_cancel(self) -> None:
        self.dismiss(False)

    def action_dismiss_false(self) -> None:
        self.dismiss(False)


def _fetch_remote_branches(repo_root: str) -> list[str]:
    """List remote branches sorted by most recent activity. Returns [] on any failure."""
    try:
        result = subprocess.run(
            ["git", "for-each-ref", "--sort=-committerdate",
             "--format=%(refname:lstrip=3)", "refs/remotes/origin/"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        return [b for b in result.stdout.strip().splitlines() if b and b != "HEAD"]
    except Exception:
        return []


class NewWorkerScreen(ModalScreen[str | None]):
    """Modal that asks for a branch name, with optional remote branch list."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    def __init__(self, repo_root: str, base_branch: str | None = None) -> None:
        super().__init__()
        self._repo_root = repo_root
        self._base_branch = base_branch
        self._branches: list[str] = []
        self._filtered: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Branch name, commander", id="dialog-title")
            if self._base_branch:
                yield Static(f"branching off [bold]{self._base_branch}[/bold]", id="base-branch-hint")
            yield Input(placeholder="type to filter or enter a new name", id="branch-input")
            yield Static("loading recently active branches...", id="branch-loading")
            yield ListView(id="branch-list")
            with Horizontal(id="dialog-buttons"):
                yield Button("Summon", variant="primary", id="create")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#branch-input", Input).focus()
        if not self._base_branch:
            self.run_worker(self._load_branches(), exclusive=True)
        else:
            self.query_one("#branch-loading", Static).display = False

    async def _load_branches(self) -> None:
        import asyncio
        branches = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_remote_branches, self._repo_root
        )
        self.query_one("#branch-loading", Static).display = False
        if branches:
            self._branches = branches
            self._refresh_list("")

    def _refresh_list(self, query: str) -> None:
        lv = self.query_one("#branch-list", ListView)
        lv.clear()
        self._filtered = [b for b in self._branches if query.lower() in b.lower()]
        for b in self._filtered:
            lv.append(ListItem(Label(b)))
        lv.display = bool(self._filtered)

    @on(Input.Changed, "#branch-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_list(event.value.strip())

    @on(ListView.Selected)
    def on_branch_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and idx < len(self._filtered):
            self.dismiss(self._filtered[idx])

    @on(Button.Pressed, "#create")
    def do_create(self) -> None:
        value = self.query_one("#branch-input", Input).value.strip()
        if value:
            self.dismiss(value)

    @on(Button.Pressed, "#cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def on_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class GarrisonApp(App):
    CSS = """
    Screen {
        background: $surface;
    }

    #main {
        height: 1fr;
        padding: 1 2;
    }

    #worker-table {
        height: 1fr;
        border: solid $primary;
    }

    #action-bar {
        height: 1;
        display: none;
        color: $text-muted;
        content-align: left middle;
    }

    #log {
        height: 8;
        border: solid $panel;
        background: $panel;
        padding: 0 1;
    }

    #dialog {
        background: $panel;
        border: solid $primary;
        padding: 2 4;
        width: 50;
        height: auto;
        align: center middle;
    }

    #dialog-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #dialog-buttons {
        margin-top: 1;
        height: auto;
        align: right middle;
    }

    #dialog-buttons Button {
        margin-left: 1;
    }

    BranchExistsScreen, CommitMessageScreen, NewWorkerScreen, _ConfirmScreen {
        align: center middle;
    }

    #base-branch-hint {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }

    #branch-loading {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }

    #branch-list {
        height: auto;
        max-height: 10;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("n", "new", "Summon new worker"),
        Binding("i", "action_mode", "Interact with worker"),
        Binding("escape", "cancel_action_mode", show=False),
        Binding("q", "quit", "Quit App", priority=True),
    ]

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, app_state: st.State) -> None:
        super().__init__()
        self._state = app_state
        self._in_action_mode = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            yield DataTable(id="worker-table", cursor_type="row")
            yield Static("", id="action-bar")
            yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"garrison — {self._state.repo}"
        table = self.query_one("#worker-table", DataTable)
        table.add_columns("ID", "Branch", "Status", "Watch", "Created")
        self._populate_table()
        self.set_interval(2, self._poll_status)
        table.focus()

    def _log(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.query_one("#log", RichLog).write(f"[dim]{ts}[/dim]  {msg}")

    def _populate_table(self) -> None:
        table = self.query_one("#worker-table", DataTable)
        prev_cursor = table.cursor_row
        table.clear()
        for worker in self._state.workers:
            watching = "[green]watching[/green]" if worker.watch_window is not None else "[dim]—[/dim]"
            table.add_row(
                str(worker.id),
                worker.branch,
                STATUS_LABELS.get(worker.status, worker.status),
                watching,
                worker.created_at,
                key=str(worker.id),
            )
        if prev_cursor is not None and self._state.workers:
            table.move_cursor(row=min(prev_cursor, len(self._state.workers) - 1))
        self._update_hint()

    def check_action(self, action: str, parameters: tuple) -> bool:
        if action == "action_mode":
            return bool(self._selected_worker())
        return True

    def _update_hint(self) -> None:
        bar = self.query_one("#action-bar", Static)
        if self._in_action_mode:
            bar.display = True
            bar.update("[bold]t[/bold] terminal · [bold]w[/bold] watch · [bold]s[/bold] commit & push · [bold]c[/bold] vscode · [bold red]f[/bold red] [red]delete[/red]  [dim]esc to cancel[/dim]")
        else:
            bar.display = False

    def on_data_table_row_highlighted(self) -> None:
        self.refresh_bindings()

    def _exit_action_mode(self) -> None:
        self._in_action_mode = False
        self._update_hint()
        self.query_one("#worker-table", DataTable).focus()

    def action_action_mode(self) -> None:
        if not self._selected_worker():
            return
        self._in_action_mode = True
        self._update_hint()

    def action_cancel_action_mode(self) -> None:
        self._exit_action_mode()

    def on_key(self, event) -> None:
        if not self._in_action_mode:
            return
        self._exit_action_mode()
        key = event.key
        if key == "t":
            self.action_terminal()
        elif key == "w":
            self.action_watch()
        elif key == "s":
            self.action_publish()
        elif key == "c":
            self.action_vscode()
        elif key == "f":
            self.action_discard()
        event.stop()

    def _poll_status(self) -> None:
        changed = False
        for worker in self._state.workers:
            if worker.status == "waiting":
                if not tmux.window_alive(self._state.session, worker.window):
                    worker.status = "idle"
                    changed = True
            if worker.watch_window is not None:
                if not tmux.window_alive(self._state.session, worker.watch_window):
                    worker.watch_window = None
                    changed = True
                    self._log(f"[yellow]watch died for '{worker.branch}' — check the window[/yellow]")
        if changed:
            st.save(self._state)
            self._populate_table()

    def action_new(self) -> None:
        self.push_screen(NewWorkerScreen(self._state.repo), self._on_name_entered)

    def _on_name_entered(self, branch: str | None) -> None:
        if not branch:
            return
        repo = self._state.repo
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo,
        ).returncode == 0
        if branch_exists:
            self.push_screen(BranchExistsScreen(branch), self._on_branch_chosen)
        else:
            self._on_branch_chosen(branch)

    def _on_branch_chosen(self, branch: str | None, base_branch: str | None = None) -> None:
        if not branch:
            return
        if branch.startswith("__new__:"):
            base = branch[len("__new__:"):]
            self.push_screen(
                NewWorkerScreen(self._state.repo, base_branch=base),
                lambda b: self._on_branch_chosen(b, base_branch=base),
            )
            return

        # If we already have a worker for this branch, just open it
        existing = next((w for w in self._state.workers if w.branch == branch), None)
        if existing:
            self._log(f"worker [bold]{branch}[/bold] already exists — opening")
            tmux.switch_client(self._state.session, existing.window)
            return

        repo = self._state.repo
        worktree_path = f"{repo}/.garrison/worktrees/{branch}"

        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo,
        ).returncode == 0

        if branch_exists:
            cmd = ["git", "worktree", "add", worktree_path, branch]
        elif base_branch:
            cmd = ["git", "worktree", "add", "-b", branch, worktree_path, base_branch]
        else:
            cmd = ["git", "worktree", "add", "-b", branch, worktree_path]

        try:
            subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode().strip()
            if "already checked out" in err or "already used by worktree" in err:
                import os
                # Check if the registered path is actually gone (stale entry)
                stale_path = next(
                    (p for p in err.split("'") if p.startswith("/") and not os.path.exists(p)),
                    None,
                )
                if stale_path:
                    self.push_screen(
                        _ConfirmScreen(f"Stale worktree entry for '{branch}' — prune and retry?"),
                        lambda ok, _branch=branch, _base=base_branch: self._do_prune_and_retry(_branch, _base) if ok else None,
                    )
                else:
                    self._log(f"[red]'{branch}' is already checked out in another worktree[/red]")
            else:
                self._log(f"[red]git worktree failed: {err}[/red]")
            return

        try:
            window_idx = tmux.new_window(
                session=self._state.session,
                name=f"worker/{branch}",
                start_dir=worktree_path,
                command=f"claude --name {branch}",
            )
        except Exception as e:
            subprocess.run(["git", "worktree", "remove", "--force", worktree_path], cwd=repo)
            self._log(f"[red]tmux error: {e}[/red]")
            return

        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        worker = st.add_worker(self._state, branch, worktree_path, window_idx, created_at)
        worker.session_started = True
        st.save(self._state)
        self._populate_table()
        self._log(f"worker [bold]{branch}[/bold] created")
        tmux.switch_client(self._state.session, window_idx)

    def _do_prune_and_retry(self, branch: str, base_branch: str | None) -> None:
        repo = self._state.repo
        result = subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)
        if result.returncode != 0:
            self._log(f"[red]git worktree prune failed: {result.stderr.decode().strip()}[/red]")
            return
        self._log("pruned stale worktree entries — retrying...")
        self._on_branch_chosen(branch, base_branch=base_branch)

    def _selected_worker(self) -> st.Worker | None:
        table = self.query_one("#worker-table", DataTable)
        if table.cursor_row is None or not table.is_valid_row_index(table.cursor_row):
            return None
        row = table.get_row_at(table.cursor_row)
        return next((w for w in self._state.workers if str(w.id) == str(row[0])), None)

    def action_open(self) -> None:
        worker = self._selected_worker()
        if not worker:
            return
        if not tmux.window_alive(self._state.session, worker.window):
            try:
                cmd = f"claude --resume {worker.branch}" if worker.session_started else f"claude --name {worker.branch}"
                worker.window = tmux.new_window(
                    session=self._state.session,
                    name=f"worker/{worker.branch}",
                    start_dir=worker.worktree,
                    command=cmd,
                )
                worker.status = "waiting"
                st.save(self._state)
                self._populate_table()
                self._log(f"worker [bold]{worker.branch}[/bold] reopened")
            except Exception as e:
                self._log(f"[red]could not reopen worker: {e}[/red]")
                return
        tmux.switch_client(self._state.session, worker.window)

    def action_vscode(self) -> None:
        worker = self._selected_worker()
        if worker:
            subprocess.Popen(
                ["code", "--add", worker.worktree],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._log(f"opened [bold]{worker.branch}[/bold] in VS Code")

    def _cleanup_worker(self, worker: st.Worker) -> None:
        if worker.watch_window is not None and tmux.window_alive(self._state.session, worker.watch_window):
            tmux.kill_window(self._state.session, worker.watch_window)
        if tmux.window_alive(self._state.session, worker.window):
            tmux.kill_window(self._state.session, worker.window)
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", worker.worktree],
                cwd=self._state.repo,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass
        st.remove_worker(self._state, worker.id)
        st.save(self._state)
        self._populate_table()

    def action_discard(self) -> None:
        worker = self._selected_worker()
        if not worker:
            return
        self._cleanup_worker(worker)
        self._log(f"worker [bold]{worker.branch}[/bold] discarded")

    def action_publish(self) -> None:
        worker = self._selected_worker()
        if not worker:
            return
        self.push_screen(CommitMessageScreen(), lambda msg: self._do_publish(worker, msg))

    def _do_publish(self, worker: st.Worker, message: str | None) -> None:
        if not message:
            return
        try:
            subprocess.run(["git", "add", "-A"], cwd=worker.worktree, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-sm", message], cwd=worker.worktree, check=True, capture_output=True)
            subprocess.run(["git", "push", "-u", "origin", worker.branch], cwd=worker.worktree, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            self._log(f"[red]publish failed: {e.stderr.decode().strip()}[/red]")
            return
        self._log(f"[green]published [bold]{worker.branch}[/bold] — {message}[/green]")

    def action_terminal(self) -> None:
        worker = self._selected_worker()
        if not worker:
            return
        window_idx = tmux.new_window(
            session=self._state.session,
            name=f"shell/{worker.branch}",
            start_dir=worker.worktree,
            command="",
        )
        self._log(f"terminal opened for [bold]{worker.branch}[/bold]")
        tmux.switch_client(self._state.session, window_idx)

    def action_watch(self) -> None:
        worker = self._selected_worker()
        if not worker:
            return

        if worker.watch_window is not None:
            if tmux.window_alive(self._state.session, worker.watch_window):
                tmux.kill_window(self._state.session, worker.watch_window)
            worker.watch_window = None
            st.save(self._state)
            self._populate_table()
            self._log(f"watch stopped for [bold]{worker.branch}[/bold]")
            return

        for other in self._state.workers:
            if other.id != worker.id and other.watch_window is not None:
                if tmux.window_alive(self._state.session, other.watch_window):
                    tmux.kill_window(self._state.session, other.watch_window)
                other.watch_window = None
                self._log(f"watch stopped for [bold]{other.branch}[/bold]")

        window_idx = tmux.new_window(
            session=self._state.session,
            name=f"watch/{worker.branch}",
            start_dir=worker.worktree,
            command="yarn run watch",
        )
        worker.watch_window = window_idx
        st.save(self._state)
        self._populate_table()
        self._log(f"watch started for [bold]{worker.branch}[/bold]")

    def action_quit(self) -> None:
        st.save(self._state)
        self.exit()
        tmux._run("kill-session", "-t", self._state.session)
