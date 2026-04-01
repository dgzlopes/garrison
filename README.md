# tulip

Run multiple Claude Code sessions in parallel on a single repo, each isolated in its own git worktree.

- Sessions survive terminal restarts and are automatically resumed.
- Jump into any project's shell, preview live changes, or commit and push from a single command.
- Fully isolated from your personal tmux — tulip runs its own tmux server.

## Requirements

- tmux
- [Claude Code](https://claude.ai/code)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/dgzlopes/tulip/main/install.sh | bash
```

## Usage

```bash
tulip          # open the TUI
tulip reset    # wipe all projects, sessions, and worktrees
```

## TUI keys

| Key | Action |
|-----|--------|
| `n` | New project |
| `d` | Delete selected project and worktree |
| `↑↓` / `j` `k` | Navigate |
| `↵` | Open project action menu |
| `q` | Quit |

## Project commands

Interact with projects by ID or branch name from any terminal:

```bash
tulip <id|branch>                # interactive picker (arrow keys)
tulip claude <id|branch>         # attach to the Claude session
tulip shell <id|branch>          # open a shell in the worktree
tulip graft <id|branch>          # start yarn watch for live preview (switches active graft)
tulip graft-debug <id|branch>    # attach to the graft watch output
tulip vscode <id|branch>         # open the worktree in VS Code
tulip publish <id|branch> <msg>  # stage all, commit (signed), and push
```

## Contributing

Personal tool — fork and adapt freely.

## License

MIT
