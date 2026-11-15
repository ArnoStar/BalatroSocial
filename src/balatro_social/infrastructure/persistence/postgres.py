"""Everything kept in PostgreSQL.

A unit is a transaction; ``lock=True`` reads rows FOR UPDATE (a conversation:
its messages are numbered one after the other) or takes a transaction lock on
a pair of players (their friend request, their direct conversation), so two
requests about the same thing wait for each other. The schema comes from the
numbered ``MIGRATIONS`` (each applied once, in order, under a lock); never
change a released one: add one.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from balatro_social.domain import (
    Block,
    Conversation,
    ConversationKind,
    FriendRequest,
    Friendship,
    Member,
    Message,
    MessageKind,
    PlayerRecord,
    RequestPolicy,
    RequestStatus,
    pair_key,
)

MIGRATIONS: tuple[str, ...] = (
    # 1: players, friendships, friend requests, blocks, conversations, their members and messages
    """
    CREATE TABLE players (
        id TEXT PRIMARY KEY,
        name TEXT,
        code TEXT NOT NULL UNIQUE,
        requests TEXT NOT NULL,
        show_presence BOOLEAN NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        last_seen TIMESTAMPTZ
    );
    CREATE INDEX players_name ON players (lower(name) text_pattern_ops);
    CREATE TABLE friendships (
        player TEXT NOT NULL REFERENCES players (id),
        friend TEXT NOT NULL REFERENCES players (id),
        since TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (player, friend)
    );
    CREATE TABLE friend_requests (
        id TEXT PRIMARY KEY,
        sender TEXT NOT NULL REFERENCES players (id),
        recipient TEXT NOT NULL REFERENCES players (id),
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX friend_requests_recipient ON friend_requests (recipient, status, created_at DESC);
    CREATE INDEX friend_requests_sender ON friend_requests (sender, created_at DESC);
    CREATE UNIQUE INDEX friend_requests_one_pending
        ON friend_requests (LEAST(sender, recipient), GREATEST(sender, recipient)) WHERE status = 'pending';
    CREATE TABLE blocks (
        blocker TEXT NOT NULL REFERENCES players (id),
        blocked TEXT NOT NULL REFERENCES players (id),
        at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (blocker, blocked)
    );
    CREATE TABLE conversations (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        title TEXT,
        owner TEXT,
        pair TEXT UNIQUE,
        created_at TIMESTAMPTZ NOT NULL,
        last_seq INTEGER NOT NULL,
        last_at TIMESTAMPTZ
    );
    CREATE TABLE members (
        conversation TEXT NOT NULL REFERENCES conversations (id),
        player TEXT NOT NULL REFERENCES players (id),
        joined_at TIMESTAMPTZ NOT NULL,
        since_seq INTEGER NOT NULL,
        last_read INTEGER NOT NULL,
        muted BOOLEAN NOT NULL,
        left_at TIMESTAMPTZ,
        PRIMARY KEY (conversation, player)
    );
    CREATE INDEX members_player ON members (player) WHERE left_at IS NULL;
    CREATE TABLE messages (
        id TEXT PRIMARY KEY,
        conversation TEXT NOT NULL REFERENCES conversations (id),
        seq INTEGER NOT NULL,
        sender TEXT,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        attachment JSONB,
        created_at TIMESTAMPTZ NOT NULL,
        deleted_at TIMESTAMPTZ,
        UNIQUE (conversation, seq)
    );
    CREATE INDEX messages_sender ON messages (sender, created_at DESC);
    """,
    # 2: profile pictures
    """
    ALTER TABLE players ADD COLUMN avatar BIGINT NOT NULL DEFAULT 0;
    CREATE TABLE avatars (
        player TEXT PRIMARY KEY REFERENCES players (id),
        content_type TEXT NOT NULL,
        data BYTEA NOT NULL
    );
    """,
)


class DatabaseUnavailable(RuntimeError):
    """The database doesn't answer when the service starts."""


def where(url: str) -> str:
    """The database's address, without the password."""
    try:
        d = conninfo_to_dict(url)
    except Exception:
        return "(an unreadable URL)"
    return f"{d.get('host', 'localhost')}:{d.get('port', 5432)}/{d.get('dbname', '')}"


def _player(r: DictRow) -> PlayerRecord:
    return PlayerRecord(id=r["id"], name=r["name"], code=r["code"], created_at=r["created_at"],
                        requests=RequestPolicy(r["requests"]), show_presence=r["show_presence"],
                        last_seen=r["last_seen"], avatar=r["avatar"])


def _request(r: DictRow) -> FriendRequest:
    return FriendRequest(id=r["id"], sender=r["sender"], recipient=r["recipient"], status=RequestStatus(r["status"]),
                         created_at=r["created_at"], updated_at=r["updated_at"])


def _conversation(r: DictRow) -> Conversation:
    return Conversation(id=r["id"], kind=ConversationKind(r["kind"]), created_at=r["created_at"], title=r["title"],
                        owner=r["owner"], pair=r["pair"], last_seq=r["last_seq"], last_at=r["last_at"])


def _member(r: DictRow) -> Member:
    return Member(conversation=r["conversation"], player=r["player"], joined_at=r["joined_at"],
                  since_seq=r["since_seq"], last_read=r["last_read"], muted=r["muted"], left_at=r["left_at"])


def _message(r: DictRow) -> Message:
    return Message(id=r["id"], conversation=r["conversation"], seq=r["seq"], sender=r["sender"],
                   kind=MessageKind(r["kind"]), text=r["text"], created_at=r["created_at"],
                   attachment=r["attachment"], deleted_at=r["deleted_at"])


def _like(prefix: str) -> str:
    return prefix.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class PostgresUnit:
    def __init__(self, conn: Connection[DictRow]) -> None:
        self.c = conn

    def _pair_lock(self, kind: str, a: str, b: str) -> None:
        self.c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"balatro_social.{kind}:{pair_key(a, b)}",))

    # players
    def player(self, player_id: str, lock: bool = False) -> PlayerRecord | None:
        row = self.c.execute("SELECT * FROM players WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                             (player_id,)).fetchone()
        return _player(row) if row else None

    def players(self, ids: Iterable[str]) -> dict[str, PlayerRecord]:
        wanted = list(set(ids))
        if not wanted:
            return {}
        return {r["id"]: _player(r) for r in self.c.execute("SELECT * FROM players WHERE id = ANY(%s)", (wanted,))}

    def add_player(self, p: PlayerRecord) -> bool:
        cur = self.c.execute(
            "INSERT INTO players (id, name, code, requests, show_presence, created_at, last_seen, avatar) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (p.id, p.name, p.code, p.requests.value, p.show_presence, p.created_at, p.last_seen, p.avatar))
        return cur.rowcount == 1

    def save_player(self, p: PlayerRecord) -> None:
        self.c.execute("UPDATE players SET name = %s, code = %s, requests = %s, show_presence = %s, last_seen = %s, "
                       "avatar = %s WHERE id = %s",
                       (p.name, p.code, p.requests.value, p.show_presence, p.last_seen, p.avatar, p.id))

    def avatar(self, player: str) -> tuple[str, bytes] | None:
        row = self.c.execute("SELECT content_type, data FROM avatars WHERE player = %s", (player,)).fetchone()
        return (row["content_type"], bytes(row["data"])) if row else None

    def save_avatar(self, player: str, content_type: str, data: bytes) -> None:
        self.c.execute("INSERT INTO avatars (player, content_type, data) VALUES (%s, %s, %s) ON CONFLICT (player) "
                       "DO UPDATE SET content_type = EXCLUDED.content_type, data = EXCLUDED.data",
                       (player, content_type, data))

    def remove_avatar(self, player: str) -> None:
        self.c.execute("DELETE FROM avatars WHERE player = %s", (player,))

    def player_by_code(self, code: str) -> PlayerRecord | None:
        row = self.c.execute("SELECT * FROM players WHERE code = %s", (code,)).fetchone()
        return _player(row) if row else None

    def find_players(self, query: str, limit: int) -> builtins.list[PlayerRecord]:
        rows = self.c.execute("SELECT * FROM players WHERE lower(name) LIKE %s ESCAPE '\\' "
                              "ORDER BY lower(name), id LIMIT %s", (_like(query), limit)).fetchall()
        return [_player(r) for r in rows]

    # friends
    def friendship(self, player: str, friend: str) -> Friendship | None:
        row = self.c.execute("SELECT * FROM friendships WHERE player = %s AND friend = %s",
                             (player, friend)).fetchone()
        return Friendship(player=row["player"], friend=row["friend"], since=row["since"]) if row else None

    def friends_of(self, player: str) -> builtins.list[Friendship]:
        rows = self.c.execute("SELECT * FROM friendships WHERE player = %s ORDER BY since", (player,)).fetchall()
        return [Friendship(player=r["player"], friend=r["friend"], since=r["since"]) for r in rows]

    def count_friends(self, player: str) -> int:
        row = self.c.execute("SELECT count(*) AS n FROM friendships WHERE player = %s", (player,)).fetchone()
        return int(row["n"]) if row else 0

    def add_friendship(self, a: str, b: str, since: datetime) -> None:
        self.c.execute("INSERT INTO friendships (player, friend, since) VALUES (%s, %s, %s), (%s, %s, %s) "
                       "ON CONFLICT DO NOTHING", (a, b, since, b, a, since))

    def remove_friendship(self, a: str, b: str) -> bool:
        cur = self.c.execute("DELETE FROM friendships WHERE (player = %s AND friend = %s) OR "
                             "(player = %s AND friend = %s)", (a, b, b, a))
        return cur.rowcount > 0

    # friend requests
    def request(self, request_id: str, lock: bool = False) -> FriendRequest | None:
        row = self.c.execute("SELECT * FROM friend_requests WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                             (request_id,)).fetchone()
        return _request(row) if row else None

    def pending_between(self, a: str, b: str, lock: bool = False) -> FriendRequest | None:
        if lock:
            self._pair_lock("request", a, b)
        row = self.c.execute(
            "SELECT * FROM friend_requests WHERE status = 'pending' AND ((sender = %s AND recipient = %s) OR "
            "(sender = %s AND recipient = %s))" + (" FOR UPDATE" if lock else ""), (a, b, b, a)).fetchone()
        return _request(row) if row else None

    def requests_of(self, player: str, box: str) -> builtins.list[FriendRequest]:
        cond = {"incoming": "recipient = %(p)s", "outgoing": "sender = %(p)s"}.get(
            box, "(sender = %(p)s OR recipient = %(p)s)")
        rows = self.c.execute(f"SELECT * FROM friend_requests WHERE status = 'pending' AND {cond} "
                              "ORDER BY created_at DESC, id DESC", {"p": player}).fetchall()
        return [_request(r) for r in rows]

    def count_pending_from(self, sender: str) -> int:
        row = self.c.execute("SELECT count(*) AS n FROM friend_requests WHERE sender = %s AND status = 'pending'",
                             (sender,)).fetchone()
        return int(row["n"]) if row else 0

    def count_requests_since(self, sender: str, since: datetime) -> int:
        row = self.c.execute("SELECT count(*) AS n FROM friend_requests WHERE sender = %s AND created_at > %s",
                             (sender, since)).fetchone()
        return int(row["n"]) if row else 0

    def add_request(self, r: FriendRequest) -> None:
        self.c.execute("INSERT INTO friend_requests (id, sender, recipient, status, created_at, updated_at) "
                       "VALUES (%s, %s, %s, %s, %s, %s)",
                       (r.id, r.sender, r.recipient, r.status.value, r.created_at, r.updated_at))

    def save_request(self, r: FriendRequest) -> None:
        self.c.execute("UPDATE friend_requests SET status = %s, updated_at = %s WHERE id = %s",
                       (r.status.value, r.updated_at, r.id))

    # blocks
    def block(self, blocker: str, blocked: str) -> Block | None:
        row = self.c.execute("SELECT * FROM blocks WHERE blocker = %s AND blocked = %s", (blocker, blocked)).fetchone()
        return Block(blocker=row["blocker"], blocked=row["blocked"], at=row["at"]) if row else None

    def blocks_of(self, blocker: str) -> builtins.list[Block]:
        rows = self.c.execute("SELECT * FROM blocks WHERE blocker = %s ORDER BY at DESC", (blocker,)).fetchall()
        return [Block(blocker=r["blocker"], blocked=r["blocked"], at=r["at"]) for r in rows]

    def add_block(self, b: Block) -> None:
        self.c.execute("INSERT INTO blocks (blocker, blocked, at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                       (b.blocker, b.blocked, b.at))

    def remove_block(self, blocker: str, blocked: str) -> bool:
        return self.c.execute("DELETE FROM blocks WHERE blocker = %s AND blocked = %s",
                              (blocker, blocked)).rowcount > 0

    # conversations and their members
    def conversation(self, conversation_id: str, lock: bool = False) -> Conversation | None:
        row = self.c.execute("SELECT * FROM conversations WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                             (conversation_id,)).fetchone()
        return _conversation(row) if row else None

    def conversations(self, ids: Iterable[str]) -> dict[str, Conversation]:
        wanted = list(set(ids))
        if not wanted:
            return {}
        rows = self.c.execute("SELECT * FROM conversations WHERE id = ANY(%s)", (wanted,)).fetchall()
        return {r["id"]: _conversation(r) for r in rows}

    def direct_between(self, a: str, b: str, lock: bool = False) -> Conversation | None:
        if lock:
            self._pair_lock("direct", a, b)
        row = self.c.execute("SELECT * FROM conversations WHERE pair = %s" + (" FOR UPDATE" if lock else ""),
                             (pair_key(a, b),)).fetchone()
        return _conversation(row) if row else None

    def directs_of(self, player: str) -> dict[str, str]:
        rows = self.c.execute(
            "SELECT c.id, o.player AS other FROM conversations c "
            "JOIN members m ON m.conversation = c.id AND m.player = %(p)s "
            "JOIN members o ON o.conversation = c.id AND o.player <> %(p)s "
            "WHERE c.kind = 'direct'", {"p": player}).fetchall()
        return {r["other"]: r["id"] for r in rows}

    def add_conversation(self, c: Conversation) -> None:
        self.c.execute("INSERT INTO conversations (id, kind, title, owner, pair, created_at, last_seq, last_at) "
                       "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                       (c.id, c.kind.value, c.title, c.owner, c.pair, c.created_at, c.last_seq, c.last_at))

    def save_conversation(self, c: Conversation) -> None:
        self.c.execute("UPDATE conversations SET title = %s, owner = %s, last_seq = %s, last_at = %s WHERE id = %s",
                       (c.title, c.owner, c.last_seq, c.last_at, c.id))

    def member(self, conversation_id: str, player: str) -> Member | None:
        row = self.c.execute("SELECT * FROM members WHERE conversation = %s AND player = %s",
                             (conversation_id, player)).fetchone()
        return _member(row) if row else None

    def members(self, conversation_ids: Sequence[str]) -> dict[str, builtins.list[Member]]:
        if not conversation_ids:
            return {}
        rows = self.c.execute("SELECT * FROM members WHERE conversation = ANY(%s) AND left_at IS NULL "
                              "ORDER BY joined_at, player", (list(conversation_ids),)).fetchall()
        out: dict[str, list[Member]] = {}
        for r in rows:
            out.setdefault(r["conversation"], []).append(_member(r))
        return out

    def memberships(self, player: str) -> builtins.list[Member]:
        rows = self.c.execute("SELECT * FROM members WHERE player = %s AND left_at IS NULL", (player,)).fetchall()
        return [_member(r) for r in rows]

    def save_member(self, m: Member) -> None:
        self.c.execute(
            "INSERT INTO members (conversation, player, joined_at, since_seq, last_read, muted, left_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (conversation, player) DO UPDATE SET "
            "joined_at = EXCLUDED.joined_at, since_seq = EXCLUDED.since_seq, last_read = EXCLUDED.last_read, "
            "muted = EXCLUDED.muted, left_at = EXCLUDED.left_at",
            (m.conversation, m.player, m.joined_at, m.since_seq, m.last_read, m.muted, m.left_at))

    def count_groups(self, player: str) -> int:
        row = self.c.execute("SELECT count(*) AS n FROM members m JOIN conversations c ON c.id = m.conversation "
                             "WHERE m.player = %s AND m.left_at IS NULL AND c.kind = 'group'", (player,)).fetchone()
        return int(row["n"]) if row else 0

    # messages
    def add_message(self, m: Message) -> None:
        self.c.execute(
            "INSERT INTO messages (id, conversation, seq, sender, kind, text, attachment, created_at, deleted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (m.id, m.conversation, m.seq, m.sender, m.kind.value, m.text,
             Jsonb(m.attachment) if m.attachment is not None else None, m.created_at, m.deleted_at))

    def save_message(self, m: Message) -> None:
        self.c.execute("UPDATE messages SET text = %s, attachment = %s, deleted_at = %s WHERE id = %s",
                       (m.text, Jsonb(m.attachment) if m.attachment is not None else None, m.deleted_at, m.id))

    def message(self, message_id: str) -> Message | None:
        row = self.c.execute("SELECT * FROM messages WHERE id = %s", (message_id,)).fetchone()
        return _message(row) if row else None

    def messages(self, conversation_id: str, floor: int, before: int | None, after: int | None,
                 limit: int) -> builtins.list[Message]:
        if after is not None:
            rows = self.c.execute("SELECT * FROM messages WHERE conversation = %s AND seq > %s ORDER BY seq LIMIT %s",
                                  (conversation_id, max(floor, after), limit)).fetchall()
            return [_message(r) for r in rows]
        params: dict[str, Any] = {"c": conversation_id, "floor": floor, "before": before, "n": limit}
        rows = self.c.execute(
            "SELECT * FROM messages WHERE conversation = %(c)s AND seq > %(floor)s "
            + ("AND seq < %(before)s " if before is not None else "") + "ORDER BY seq DESC LIMIT %(n)s",
            params).fetchall()
        return [_message(r) for r in reversed(rows)]

    def last_messages(self, conversation_ids: Sequence[str]) -> dict[str, Message]:
        if not conversation_ids:
            return {}
        rows = self.c.execute("SELECT m.* FROM messages m JOIN conversations c ON c.id = m.conversation "
                              "AND m.seq = c.last_seq WHERE c.id = ANY(%s)", (list(conversation_ids),)).fetchall()
        return {r["conversation"]: _message(r) for r in rows}

    def unread(self, player: str, members: Sequence[Member]) -> dict[str, int]:
        if not members:
            return {}
        rows = self.c.execute(
            "SELECT m.conversation, count(*) AS n FROM messages m "
            "JOIN unnest(%s::text[], %s::int[]) AS w(c, after) ON m.conversation = w.c "
            "WHERE m.seq > w.after AND m.sender IS NOT NULL AND m.sender <> %s AND m.deleted_at IS NULL "
            "GROUP BY m.conversation",
            ([x.conversation for x in members], [max(x.last_read, x.since_seq) for x in members], player)).fetchall()
        return {r["conversation"]: int(r["n"]) for r in rows}

    def count_messages_since(self, sender: str, since: datetime) -> int:
        row = self.c.execute("SELECT count(*) AS n FROM messages WHERE sender = %s AND created_at > %s",
                             (sender, since)).fetchone()
        return int(row["n"]) if row else 0


class PostgresStore:
    """``url``: postgresql://user:password@host/db.  ``schema``: keep the tables in this
    schema (made if needed).  ``connect_timeout``: how long to wait for the database at
    start (seconds) before raising DatabaseUnavailable."""

    def __init__(self, url: str, schema: str | None = None, max_connections: int = 10,
                 connect_timeout: float = 30) -> None:
        def configure(conn: Connection[Any]) -> None:
            conn.execute("SET TIME ZONE 'UTC'")
            if schema:
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.commit()

        if schema:
            with Connection.connect(url, autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        self._pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
            url, min_size=1, max_size=max_connections, configure=configure, open=False,
            kwargs={"row_factory": dict_row}, connection_class=Connection[DictRow])
        try:
            self._pool.open(wait=True, timeout=connect_timeout)
        except PoolTimeout:
            self._pool.close()
            raise DatabaseUnavailable(
                f"PostgreSQL at {where(url)} doesn't answer (BALATRO_SOCIAL_DATABASE_URL). In Docker, the "
                "social-db service of BalatroFrontEnd's docker-compose.yml is this service's database") from None
        self.migrate()

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def unit(self) -> Iterator[PostgresUnit]:
        with self._pool.connection() as conn, conn.transaction():
            yield PostgresUnit(conn)

    def migrate(self) -> None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('balatro_social.migrations'))")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, "
                         "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
            done = row["v"] if row else 0
            for version, script in enumerate(MIGRATIONS, 1):
                if version > done:
                    conn.execute(script.encode())
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
