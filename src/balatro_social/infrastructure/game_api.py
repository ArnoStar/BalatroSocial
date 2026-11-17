"""The game API (BalatroWebAPI): a run the player shares, and the match they
invite friends to, read with their own access token (so it can only be one of
theirs: the API says 404 otherwise)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from balatro_social.application.dto import Player
from balatro_social.application.errors import GameApiUnavailable, NoOpenMatch, RunNotFound
from balatro_social.domain import MatchCard, RunCard

log = logging.getLogger(__name__)


class GameApi:
    """``base``: the API's address (http://api:8000 in the stack), without /api/v1."""

    def __init__(self, base: str, timeout: float = 10) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, token: str | None) -> Any:
        req = urllib.request.Request(f"{self.base}/api/v1{path}", headers={"Accept": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = r.read()
            return json.loads(body) if body else None

    def open_match(self, player: Player) -> MatchCard:
        path = "/matches/current"
        try:
            m = self._get(path, player.token)
        except urllib.error.HTTPError as exc:
            log.warning("the game API answered %s to %s", exc.code, path)
            raise GameApiUnavailable("the game's server can't tell about your match now, try again") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("the game API didn't answer %s: %s", path, exc)
            raise GameApiUnavailable("the game's server can't be reached, try again") from exc
        if not m or m.get("status") != "lobby":
            raise NoOpenMatch()
        return MatchCard(id=str(m["id"]), code=str(m["code"]), mode=str(m.get("mode") or "pvp"))

    def run(self, player: Player, run_id: str) -> RunCard:
        path = f"/games/{urllib.parse.quote(run_id, safe='')}/summary"
        try:
            r = self._get(path, player.token)
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 422):
                raise RunNotFound(run_id) from exc
            log.warning("the game API answered %s to %s", exc.code, path)
            raise GameApiUnavailable("the game's server can't tell about this run now, try again") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("the game API didn't answer %s: %s", path, exc)
            raise GameApiUnavailable("the game's server can't be reached, try again") from exc
        s = r.get("settings") or {}
        return RunCard(id=str(r["id"]), deck=str(s.get("deck") or "b_red"), stake=int(s.get("stake") or 1),
                       seed=str(s.get("seed") or ""), seeded=bool(s.get("seeded")), challenge=s.get("challenge"),
                       ante=int(r.get("ante") or 0), round=int(r.get("round") or 0), won=bool(r.get("won")),
                       finished=r.get("phase") == "game_over" or bool(r.get("won")),
                       best_hand=float(r.get("best_hand") or 0), counted=bool(r.get("counted", True)),
                       played_at=datetime.fromisoformat(r["updated_at"]))
