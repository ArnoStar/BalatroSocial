# The event stream

`GET /v1/events` (at `/social/v1/events` on the site) is a stream of
[server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html):
what changes for the caller, as it happens. Open it with `fetch` and the
`Authorization: Bearer <access token>` header (an `EventSource` can't send
headers) and read the body as it arrives:

```
event: hello
data: {"id":"5a68...","name":"Arno","friend_code":"K7QM-29XD", ...}

event: message
data: {"id":"...","conversation":"...","seq":12,"sender":{"id":"...","name":"Bob"},"kind":"text","text":"gg", ...}

: ping
```

Each event is an `event:` line (its type) and a `data:` line (JSON), then a
blank line. A line starting with `:` is a comment, sent every 20 seconds
(`BALATRO_SOCIAL_HEARTBEAT`) so that proxies keep the connection open.

## The stream's life

- It starts with `hello`: the caller's `MeView` (`GET /v1/me`).
- While it is open, the player is online for their friends (and a few seconds
  after it closes: reopening it doesn't make them flicker).
- It ends with `expired` when the access token expires: open a new one with a
  fresh token. It ends with `reset` when the client fell behind (256 events
  not read): open a new one.
- Events aren't kept: after a reconnection, reload what is shown
  (`/v1/friends`, `/v1/conversations`, the open conversation's messages after
  the last `seq` the client has).

The site's nginx passes it on unbuffered (`X-Accel-Buffering: no`, which the
portal's nginx passes to a proxy in front of it).

## Events

| `event` | `data` | To | When |
|---|---|---|---|
| `hello` | `MeView` | the caller | the stream opens |
| `me` | `MeView` | the player | their settings changed (another tab) |
| `message` | `MessageView` | every member | a message was sent (the sender's tabs too: match it by `id`) |
| `message_deleted` | `MessageView` (`deleted: true`) | every member | its sender deleted it |
| `read` | `{conversation, player, seq}` | every member | a player read up to `seq` (read receipts; one's own: the other tabs' unread count) |
| `typing` | `{conversation, player: {id, name}}` | the other members | someone is writing: show it for about 5 seconds |
| `conversation` | `ConversationView` (the receiver's own) | the members | a conversation was made, renamed, muted, players joined or left, or a direct conversation can be written to again (or not) |
| `conversation_left` | `{id}` | the player | they left a group, or were removed: drop it |
| `friend_request` | `RequestView` | its two players | a request was sent, accepted, declined or taken back |
| `friend` | `PlayerView` (the friend, with presence) | each of the two; the player's friends | a friendship started; a friend's profile picture changed (replace the friend) |
| `friend_removed` | `{id}` (the other player) | each of the two | a friendship ended (removed, or blocked) |
| `presence` | `{player, presence: PresenceView}` | the player's friends | they came online, went offline, or do something else in the game |

The views are the same as the HTTP API's (`/docs` has their schemas).
