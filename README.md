# BalatroSocial

Friends and chat for Balatro in the browser:

- **Friends**: requests by name, or by **friend code** and **invite link**
  (`<site>/friends/add/<code>`); two requests crossing make friends at once.
  Players can take requests only with their code, and **block** anyone.
- **Chat**: direct conversations between friends and **groups** of friends (up
  to 20), in real time: messages, read receipts, "… is writing", unread
  counts, muting, deleting one's messages.
- **Sharing games**: a **run** (one of yours, read from the game API: deck,
  stake, seed, ante, best hand, won or lost; friends can watch it again) or a
  **seed** to play (deck and stake), with a note.
- **Presence**: friends see who is online, and what they play (the game sends
  its deck, stake and ante). It can be hidden.
- **Profile pictures**: a PNG, JPEG or WebP of one's own (the portal's account
  page cuts it square and sends it at 256 x 256), shown next to the player's
  name to friends, in requests and in the chat.

The portal ([BalatroPortal](https://github.com/ArnoStar/BalatroPortal), pages
`/friends` and `/chat`) shows it; the game
([BalatroFrontEnd](https://github.com/ArnoStar/BalatroFrontEnd)) sends its
presence and opens shared seeds (`/play/?seed=…&deck=…&stake=…`).

## Endpoints

The site serves the service at `/social/` (the portal's nginx strips the
prefix); here are its own paths. With sign-in on, every route but `/health`
needs an access token from the identity service.

| | |
|---|---|
| `GET /health` | `{status, version, auth}` |
| `GET /v1/me` | you: `friend_code` (ABCD-2345), `requests` (`everyone`, `code`), `show_presence`, and the counts of `friends`, `incoming` requests and `unread` messages |
| `PATCH /v1/me` | `{requests?, show_presence?}` |
| `POST /v1/me/code` | a new friend code (the old one and its links stop working) |
| `PUT /v1/me/avatar` | your profile picture: the image itself as the body (PNG, JPEG or WebP, checked from its bytes; 256 KB and 1024 x 1024 at most) |
| `DELETE /v1/me/avatar` | no picture (your initials) |
| `GET /v1/avatars?ids=a,b,c` | which players have a picture: `{id: version or null}` (public; 100 ids at most), so that a page naming many players shows theirs with one look-up |
| `GET /v1/avatars/{id}?v=` | a player's picture, public (an `<img>` sends no token); `v`, the views' `avatar` version, makes it cacheable for good |
| `PUT /v1/me/presence` | the game's heartbeat: `{activity: {kind: menu\|run\|watching, deck, stake, ante, seeded, challenge}}`, every minute and on each change |
| `GET /v1/players?q=` | players by the start of their name (2 characters at least), with their `relation` to you |
| `GET /v1/players/{id}`, `GET /v1/codes/{code}` | a player (by id, or friend code: an invite link) |
| `GET /v1/friends` | your friends, online first, with their `presence` and your direct `conversation` |
| `DELETE /v1/friends/{id}` | remove a friend |
| `GET /v1/friends/requests?box=incoming\|outgoing\|all` | requests waiting |
| `POST /v1/friends/requests` | `{to}` (an id) or `{code}`; `201` with the request (`accepted` if they had asked you) |
| `POST /v1/friends/requests/{id}/accept\|decline\|cancel` | answer, or take yours back |
| `GET /v1/blocks`, `PUT /v1/blocks/{id}`, `DELETE /v1/blocks/{id}` | blocks |
| `GET /v1/conversations` | your conversations, the last written to first (last message, `unread`, `can_send`) |
| `POST /v1/conversations` | a group: `{title, members}` (friends) |
| `POST /v1/conversations/direct` | `{player}`: your conversation with a friend (made the first time) |
| `GET`, `PATCH /v1/conversations/{id}` | a conversation; `{title}` (a group's), `{muted}` |
| `POST /v1/conversations/{id}/members` | `{players}`: add friends to a group |
| `DELETE /v1/conversations/{id}/members/{player}` | leave (yourself, `204`), or the owner removes a player |
| `GET /v1/conversations/{id}/messages?before=&after=&limit=` | messages, oldest first |
| `POST /v1/conversations/{id}/messages` | `{text}`, `{run, text?}` or `{seed: {seed, deck, stake}, text?}` |
| `DELETE /v1/conversations/{id}/messages/{message}` | delete one of yours |
| `POST /v1/conversations/{id}/read` | `{seq}`: read up to there |
| `POST /v1/conversations/{id}/typing` | you are writing (every 3 seconds while you are) |
| `POST /v1/invites` | `{to}`: invite a friend to your match waiting for players (the game API's, read with your token: `409 no_open_match` without one); they join it with the invite's `code` |
| `GET /v1/invites` | your open invites (10 minutes, until answered) |
| `POST /v1/invites/{id}/accept\|decline` | answer one (then join the match in the game: `/play/?match=<code>`) |
| `GET /v1/inbox` | what waits for you, for a notification bell: friend requests to answer, conversations with unread messages (not muted), open invites, and their `count` |
| `GET /v1/events` | your live events (server-sent events): [docs/events.md](docs/events.md) |

Errors are problem details with a stable `code`: `unauthenticated`,
`player_not_found`, `code_not_found`, `request_not_found`,
`conversation_not_found`, `message_not_found`, `run_not_found`, `self`,
`cant_add`, `already_friends`, `not_friends`, `cant_message`, `not_owner`,
`not_a_group`, `request_closed`, `group_full`, `too_many_friends`,
`invalid_image`, `avatar_not_found`,
`too_many_groups`, `too_many_requests`, `slow_down`, `invalid_message`,
`invalid_title`, `invalid_seed`, `invalid_activity`, `invalid_request`,
`game_api_unavailable`, `invite_not_found`, `invite_closed`, `no_open_match`. Interactive docs at
`/docs`.

## Limits

| | |
|---|---|
| friends | 200 |
| friend requests | 40 a day, 50 waiting for an answer |
| a group | 20 players; a player is in 30 groups at most |
| a message | 2000 characters; 20 messages in 30 seconds |
| presence | the game's heartbeat counts for 90 seconds; a closed stream for 10 |
| a profile picture | 256 KB, 1024 x 1024 pixels; PNG, JPEG or WebP; 100 players in one look-up |
| an invite to a match | to friends; open 10 minutes; 60 an hour |

## Settings

| Variable | Default | |
|---|---|---|
| `BALATRO_SOCIAL_DATABASE_URL` | `postgresql://social:social@127.0.0.1:55436/social` (`make db`) | PostgreSQL, or `memory` |
| `BALATRO_SOCIAL_API_URL` | `http://127.0.0.1:8000` | the game API (shared runs, the match an invite is for) |
| `BALATRO_SOCIAL_AUTH_JWKS_URL` | unset (sign-in off) | the identity service's `/.well-known/jwks.json` |
| `BALATRO_SOCIAL_AUTH_ISSUER` | | required with the JWKS URL: the identity service's `PUBLIC_URL` |
| `BALATRO_SOCIAL_AUTH_AUDIENCE` | `balatro` | |
| `BALATRO_SOCIAL_HEARTBEAT` | `20` | seconds between an event stream's keep-alive comments |
| `BALATRO_SOCIAL_CORS_ORIGINS` | `*` | |
| `BALATRO_SOCIAL_HOST`, `BALATRO_SOCIAL_PORT` | `127.0.0.1`, `8005` | for `balatro-social` |

## Development

```
make install && make db && make run     # http://127.0.0.1:8005/docs, no sign-in (everyone is one player)
make run-auth                           # with the identity service on :8001
make check                              # tests (PostgreSQL ones on make db's database), ruff, mypy
```

`make dev` in BalatroFrontEnd runs the whole site with this service.

## Storage

PostgreSQL (`social-db` in BalatroFrontEnd's compose file): players (their
friend code and settings), friendships (one row per side), friend requests,
blocks, conversations, their members (when they joined, what they read),
messages (a shared run or seed as JSON) and profile pictures (their bytes; the
player's row has the picture's version). Migrations are numbered in
`infrastructure/persistence/postgres.py` and applied on start. Who is online
and the open streams are kept in memory: the service runs as one process.

## Deployment

Like the other services: `.github/workflows/ci-cd.yml` runs the checks (with a
PostgreSQL service) on every push to `main` and `dev`; a push to `main` copies
the code to the server and restarts the `social` service of BalatroFrontEnd's
compose file (once that file has it). The `DEPLOY_*` secrets are the same as in
the other repositories (BalatroFrontEnd's README, Deployment). On the server,
set `SOCIAL_DB_PASSWORD` in BalatroFrontEnd's `.env` before the first start.
Deploy order: BalatroWebAPI (the run summary), BalatroFrontEnd (the compose
file), BalatroPortal (the `/social/` path and the pages), then this service.

## Code

Clean architecture, as the other services (`AGENTS.md`):

```
src/balatro_social/
  domain/           players, friendships, requests, blocks, conversations, messages; rules and limits
  application/      use cases, DTOs (the API contract), ports
  infrastructure/   auth (the identity service's tokens), the game API, persistence (PostgreSQL, memory),
                    the event hub and the presence board (in memory), the clock, ids and codes
  presentation/     http (FastAPI): routes, the event stream, problem details
  bootstrap.py, config.py, main.py
```
