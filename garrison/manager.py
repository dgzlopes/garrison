"""Textual TUI — the garrison commander running in tmux window 0."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Static

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
        self.dismiss("__new__")

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


class NewWorkerScreen(ModalScreen[str | None]):
    """Modal that asks for a branch name."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Branch name, commander", id="dialog-title")
            yield Input(placeholder="e.g. fix-auth", id="branch-input")
            with Horizontal(id="dialog-buttons"):
                yield Button("Summon", variant="primary", id="create")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#branch-input", Input).focus()

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

    #hint {
        height: 3;
        content-align: center middle;
        color: $text-muted;
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

    BranchExistsScreen, CommitMessageScreen, NewWorkerScreen {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("n", "new", "New Worker"),
        Binding("f", "discard", "Delete"),
        Binding("s", "publish", "Commit and Push"),
        Binding("t", "terminal", "Open Terminal"),
        Binding("w", "watch", "Watch Changes"),
        Binding("enter", "open", "Open"),
        Binding("c", "vscode", "Open in VSCode"),
        Binding("q", "quit", "Quit App", priority=True),
    ]

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, app_state: st.State) -> None:
        super().__init__()
        self._state = app_state

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            yield DataTable(id="worker-table", cursor_type="row")
            yield Static("", id="hint")
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
        hint = self.query_one("#hint", Static)
        if not self._state.workers:
            hint.update("No workers yet — press [bold]n[/bold] to summon one")
        else:
            hint.update("[bold]Enter[/bold] open · [bold]n[/bold] new · [bold]w[/bold] watch · [bold]t[/bold] terminal · [bold]s[/bold] commit & push · [bold]f[/bold] delete")

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
        self.push_screen(NewWorkerScreen(), self._on_name_entered)

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

    def _on_branch_chosen(self, branch: str | None) -> None:
        if not branch:
            return
        if branch == "__new__":
            self.push_screen(NewWorkerScreen(), self._on_branch_chosen)
            return

        repo = self._state.repo
        worktree_path = f"{repo}/.garrison/worktrees/{branch}"

        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo,
        ).returncode == 0

        cmd = ["git", "worktree", "add", worktree_path, branch] if branch_exists else \
              ["git", "worktree", "add", "-b", branch, worktree_path]

        try:
            subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            self._log(f"[red]git worktree failed: {e.stderr.decode().strip()}[/red]")
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

    def _selected_worker(self) -> st.Worker | None:
        table = self.query_one("#worker-table", DataTable)
        if table.cursor_row is None:
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
