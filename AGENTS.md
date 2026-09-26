# Repository Workflow Rules

This repository is being developed collaboratively during a hackathon. Avoiding merge conflicts and preserving teammates' work is a top priority.

## Before Making Changes

1. Run `git status`.
2. Do not overwrite, discard, reset, or revert existing uncommitted changes unless explicitly instructed.
3. Pull the newest remote changes before starting work.
4. Prefer: `git pull --rebase`
5. If pulling/rebasing would conflict with existing uncommitted work, stop and report the situation instead of discarding anything.
6. Review the latest changes before editing files.

## While Working

1. Make changes only relevant to the requested task.
2. Avoid unnecessary formatting or refactoring of unrelated files.
3. Do not rename, move, or delete files unless required.
4. Preserve APIs/interfaces being used by other parts of the project whenever possible.
5. Keep modules separated by responsibility:
   - frontend
   - backend/API
   - vision/localization
   - navigation/control
   - agent orchestration
   - ESP32/robot communication
6. If changing a shared API, endpoint, WebSocket event, data structure, or environment variable, update any documentation/types/examples that depend on it.

## Before Committing

1. Run `git status`.
2. Review the diff.
3. Run relevant tests, linters, or build commands when available.
4. Do not commit secrets, API keys, `.env` files, credentials, build artifacts, or temporary files.
5. Make sure the project still builds/runs for the portion being changed.

## Git Workflow

Before pushing:

1. Fetch/pull the newest remote changes.
2. Prefer rebasing local work onto the latest remote branch: `git pull --rebase`
3. Resolve conflicts carefully without deleting teammates' work.
4. If a conflict is ambiguous, stop and report it instead of guessing.
5. Commit changes with a short descriptive commit message.
6. Push the completed work to the remote repository.

Never:

- force push unless explicitly instructed
- use `git reset --hard` on shared work
- delete another contributor's changes
- rewrite shared history
- commit secrets

## Commit Messages

Use concise descriptive commits, for example:

- `feat: add robot position websocket events`
- `feat: add aruco localization`
- `fix: correct robot steering direction`
- `feat: add task dashboard`
- `chore: update backend dependencies`

## Integration Rules

Treat these interfaces as contracts between teammates.

When possible, coordinate through stable structures such as:

- `GET /world`
- `GET /robots`
- `POST /goal`
- `POST /robots/{id}/motors`
- WebSocket `/events`

Do not silently change request/response formats used by another subsystem.

## Hackathon Priorities

Prioritize in this order:

1. Working end-to-end demo
2. Reliability
3. Integration with teammates' components
4. Required sponsor integrations
5. UI polish
6. Refactoring/optimization

Prefer a simple working implementation over a complex unfinished implementation.

## End of Every Task

Before considering a coding task complete:

1. Verify the change.
2. Check `git status`.
3. Pull/rebase against the latest remote changes.
4. Resolve safe conflicts if necessary.
5. Commit the completed work.
6. Push it.
7. Report:
   - what changed
   - files changed
   - tests/checks run
   - commit hash
   - whether the push succeeded

If committing or pushing is unsafe because of conflicting or unrelated local changes, do not discard them. Explain the issue instead.
