# AGENTS.md

Rules for anyone (human or agent) changing this repository. `README.md`
describes the service; `docs/events.md` its event stream.

## What this project is

The social side of Balatro in the browser: friends (requests by name or by
friend code and invite link, blocking), direct and group conversations in real
time, runs and seeds shared in them, and presence (who is online, and what
they play). The portal (BalatroPortal) shows it; the game (BalatroFrontEnd)
sends its presence.

## Rules

1. **Both players want a friendship.** It starts only when a request is
   accepted, or two requests cross. Never make one any other way.
2. **Players reach those who want them.** Direct messages go between friends
   only; a group's new members are friends of whoever adds them. A block ends
   the friendship and any request between the two, and the blocked player
   can't ask again, write, or find the blocker by name. A player who takes
   requests only with their code isn't listed by name. Don't add a way around
   these.
3. **Presence is for friends.** Online, the game's activity and last seen go
   to friends only, and to nobody when the player hides them
   (`show_presence`). Others see everyone offline.
4. **Others' conversations don't exist.** A player who isn't in a
   conversation gets `conversation_not_found` (404), never 403. A group's new
   member reads it from when they joined.
5. **Events go out after the transaction.** Use cases collect them in an
   `Outbox` and send them once the store's `Unit` is done: a failed change
   tells nobody. Each player's view goes to that player (unread counts
   differ).
6. **The game API decides what a run is.** A shared run is read from the game
   API with the sharer's own token (`GET /api/v1/games/{id}/summary`): it can
   only be one of theirs. The service never writes to the game API and never
   trusts a run a client describes.
7. **A picture is an image, checked from its bytes.** PNG, JPEG or WebP
   only (never SVG), small (`domain/images.py`), served with `nosniff` and a
   sandboxing CSP: it is public (an `<img>` sends no token) and on the site's
   origin, so it must never be anything a browser could run.
8. **One process.** The hub (open streams) and the presence board live in
   memory. Running two processes needs a shared hub and board first (for
   example PostgreSQL LISTEN/NOTIFY): don't just add workers.

## Architecture

```
domain  <-  application  <-  infrastructure, presentation  <-  bootstrap, main
```

`tests/test_architecture.py` enforces it. DTOs are
`@dataclass(frozen=True, kw_only=True)` (the API contract: field names are the
JSON names, changes are additive); requests are pydantic models in
`presentation/http/schemas.py`; errors are domain exceptions with a `code`,
mapped in `presentation/http/errors.py`.

## Changes

- **A rule or limit:** `domain/rules.py`, with tests in
  `tests/unit/test_rules.py` and the README's "Limits".
- **A new event:** publish it through the `Outbox`, document it in
  `docs/events.md`, and handle it in the portal (`entities/social`).
- **A new kind of shared thing:** a `MessageKind`, its card in `domain/model.py`
  (with `to_json`/`from_json`), its view in `dto.py`, and the portal's chat.
- **The schema:** add a migration at the end of `MIGRATIONS`; never edit a
  released one. Run the store tests on both stores
  (`tests/integration/test_stores.py`).

## Commands

```
make install   make db   make run   make run-auth   make check
```

Before committing, `make check` must pass. ruff (line length 120), mypy --strict.
Don't commit or push unless asked.
