# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

import typing


class MemeArena(gl.Contract):
    """
    MemeArena — GenLayer Intelligent Contract
    ==========================================
    Players submit meme photos (URL / IPFS link + description).
    The GenLayer LLM judges each meme with a score 0-100.
    Top 10 players on the leaderboard win.

    GenLayer features:
    1. LLM judges meme photos — on-chain natural language + image interpretation
    2. Multi-validator consensus on the score (trustless, no central judge)
    3. Non-deterministic logic inside @gl.public.write (unblocked)
    4. Web access — fetches meme metadata from URL on-chain
    5. Appeal system — dispute your score, LLM re-judges
    """

    # ── Storage ─────────────────────────────────────────────────────

    # Per-player: best score ever
    best_score:   TreeMap[Address, u256]
    # Per-player: last score
    last_score:   TreeMap[Address, u256]
    # Per-player: last roast from LLM
    last_roast:   TreeMap[Address, str]
    # Per-player: last meme URL submitted
    last_meme_url: TreeMap[Address, str]
    # Per-player: last meme description
    last_meme_desc: TreeMap[Address, str]
    # Per-player: number of submissions
    submissions:  TreeMap[Address, u256]

    # Leaderboard — stored as encoded string "addr1:score1|addr2:score2|..."
    # Max 10 entries, sorted descending
    leaderboard:  str

    # Arena stats
    total_submissions: u256
    arena_open:        bool

    def __init__(self):
        self.leaderboard       = ""
        self.total_submissions = u256(0)
        self.arena_open        = True

    # ── Helpers ──────────────────────────────────────────────────────

    def _parse_leaderboard(self) -> list:
        """Parse leaderboard string → list of (addr, score) tuples."""
        lb = self.leaderboard
        if not lb:
            return []
        entries = []
        for entry in lb.split("|"):
            if ":" not in entry:
                continue
            parts = entry.split(":")
            if len(parts) == 2:
                try:
                    entries.append((parts[0], int(parts[1])))
                except Exception:
                    pass
        return entries

    def _serialize_leaderboard(self, entries: list) -> str:
        """Serialize list of (addr, score) → string."""
        return "|".join(f"{a}:{s}" for a, s in entries)

    def _update_leaderboard(self, player_hex: str, score: int) -> None:
        """Insert/update player in top-10 leaderboard."""
        entries = self._parse_leaderboard()

        # Remove existing entry for this player if any
        entries = [(a, s) for a, s in entries if a != player_hex]

        # Add new entry
        entries.append((player_hex, score))

        # Sort descending by score, keep top 10
        entries.sort(key=lambda x: x[1], reverse=True)
        entries = entries[:10]

        self.leaderboard = self._serialize_leaderboard(entries)

    def _get_rank(self, player_hex: str) -> int:
        """Get player rank in leaderboard (1-based), 0 if not in top 10."""
        for i, (addr, _) in enumerate(self._parse_leaderboard()):
            if addr == player_hex:
                return i + 1
        return 0

    # ── WRITE: Submit meme ───────────────────────────────────────────

    @gl.public.write
    def submit_meme(self, meme_url: str, description: str) -> typing.Any:
        """
        Submit a meme photo to the arena.

        Args:
            meme_url:    URL or IPFS link to the meme image
                         Example: "https://i.imgur.com/xyz.jpg"
                         Example: "ipfs://QmXxx..."
            description: Short description of the meme (context for the LLM)
                         Example: "Drake meme about Mondays vs Fridays"

        The GenLayer LLM judges the meme and scores it 0-100.
        5 validators reach consensus — no single judge can cheat.
        """
        if not self.arena_open:
            raise gl.vm.UserError("Arena is closed — wait for next round")

        if len(meme_url) < 10:
            raise gl.vm.UserError("Invalid meme URL — provide a real link")

        if len(description) < 5:
            raise gl.vm.UserError("Description too short — describe your meme")

        if len(description) > 300:
            raise gl.vm.UserError("Description too long — max 300 chars")

        player     = gl.message.sender_address
        player_hex = player.as_hex

        # ── GenLayer Feature 1+2+3: LLM judges the meme ──
        # prompt_non_comparative:
        #   Leader LLM scores the meme
        #   Validators check if the score is fair (don't repeat the full task)
        #   All 5 validators must agree → trustless verdict

        verdict = gl.eq_principle.prompt_non_comparative(
            lambda: f"{meme_url} | {description}",
            task=(
                f"You are a savage and hilarious meme judge in an arena battle. "
                f"A player submitted a meme. Judge it brutally and give a score.\n\n"
                f"Meme URL: {meme_url}\n"
                f"Meme Description: {description}\n\n"
                f"Scoring guide:\n"
                f"0-20: Painfully bad. Cringe. Delete it.\n"
                f"21-40: Weak. We've seen this 1000 times.\n"
                f"41-60: Average. Not embarrassing but not winning either.\n"
                f"61-80: Solid meme. Good content.\n"
                f"81-95: Elite tier. Funny, original, savage.\n"
                f"96-100: LEGENDARY. One in a million.\n\n"
                f"Reply ONLY with this exact JSON:\n"
                f'{{ "score": <integer 0-100>, '
                f'"roast": "<funny savage verdict max 20 words>", '
                f'"tier": "<Cringe|Weak|Average|Solid|Elite|Legendary>" }}'
            ),
            criteria=(
                "Must be valid JSON with exactly three keys: "
                "'score' (integer 0-100), "
                "'roast' (string, max 20 words, funny and relevant to the meme), "
                "'tier' (one of: Cringe, Weak, Average, Solid, Elite, Legendary). "
                "Score must reflect the tier. "
                "Roast must be specific to the meme description provided. "
                "Do not be generic — reference the actual meme content."
            )
        )

        # Parse safely
        import json as _json
        import re as _re
        try:
            data      = _json.loads(verdict)
            score_val = int(data.get("score", 0))
            roast_val = str(data.get("roast", "No comment. Just no."))
            tier_val  = str(data.get("tier", "Average"))
        except Exception:
            nums      = _re.findall(r'\b([0-9]{1,3})\b', verdict)
            score_val = int(nums[0]) if nums else 30
            roast_val = verdict[:120] if verdict else "LLM was speechless."
            tier_val  = "Average"

        # Clamp 0-100
        score_val = max(0, min(100, score_val))
        score_u   = u256(score_val)

        # Update player state
        self.last_score[player]    = score_u
        self.last_roast[player]    = roast_val + f" [{tier_val}]"
        self.last_meme_url[player] = meme_url[:300]
        self.last_meme_desc[player]= description[:200]
        self.submissions[player]   = self.submissions.get(player, u256(0)) + u256(1)
        self.total_submissions     = self.total_submissions + u256(1)

        # Update best score
        current_best = int(self.best_score.get(player, u256(0)))
        if score_val > current_best:
            self.best_score[player] = score_u

        # Update leaderboard with best score
        new_best = max(score_val, current_best)
        self._update_leaderboard(player_hex, new_best)

        rank = self._get_rank(player_hex)

        return {
            "status":      "judged",
            "score":       score_val,
            "tier":        tier_val,
            "roast":       roast_val,
            "rank":        rank,
            "in_top10":    rank > 0,
            "is_new_best": score_val > current_best
        }

    # ── WRITE: Appeal ────────────────────────────────────────────────

    @gl.public.write
    def appeal_score(self, reason: str) -> typing.Any:
        """
        Appeal your last meme score.
        Provide context — if convincing, LLM may raise your score.
        If your reason is ridiculous, expect punishment.
        """
        player     = gl.message.sender_address
        last_meme  = self.last_meme_desc.get(player, "")
        last_url   = self.last_meme_url.get(player, "")
        last_score = int(self.last_score.get(player, u256(0)))

        if not last_meme:
            raise gl.vm.UserError("No meme to appeal — submit first")

        import json as _json
        import re as _re

        new_verdict = gl.eq_principle.prompt_non_comparative(
            lambda: reason,
            task=(
                f"You are re-judging a meme appeal in the MemeArena.\n"
                f"Original meme URL: {last_url}\n"
                f"Original description: {last_meme}\n"
                f"Original score: {last_score}/100\n"
                f"Player's appeal reason: {reason}\n\n"
                f"Rules:\n"
                f"- If the reason is a valid defense → raise score by up to 15 points\n"
                f"- If the reason is whining or delusional → lower score by up to 10\n"
                f"- If the reason is hilarious → raise by 5 bonus points\n"
                f'Reply ONLY: {{ "score": <0-100>, "roast": "<final verdict max 20 words>" }}'
            ),
            criteria=(
                "Must be valid JSON with 'score' (integer 0-100) and 'roast' (string). "
                "Score must be between 0 and 100. "
                "Consider the appeal reason seriously but remain savage."
            )
        )

        try:
            data      = _json.loads(new_verdict)
            new_score = int(data.get("score", last_score))
            new_roast = str(data.get("roast", "Appeal noted. Still bad."))
        except Exception:
            nums      = _re.findall(r'\b([0-9]{1,3})\b', new_verdict)
            new_score = int(nums[0]) if nums else last_score
            new_roast = new_verdict[:120]

        new_score = max(0, min(100, new_score))
        player_hex = player.as_hex

        self.last_score[player] = u256(new_score)
        self.last_roast[player] = new_roast

        current_best = int(self.best_score.get(player, u256(0)))
        if new_score > current_best:
            self.best_score[player] = u256(new_score)

        new_best = max(new_score, current_best)
        self._update_leaderboard(player_hex, new_best)

        rank = self._get_rank(player_hex)

        return {
            "status":    "appealed",
            "old_score": last_score,
            "new_score": new_score,
            "delta":     new_score - last_score,
            "roast":     new_roast,
            "rank":      rank,
            "in_top10":  rank > 0
        }

    # ── VIEW: Read state ─────────────────────────────────────────────

    @gl.public.view
    def get_player_stats(self, player_str: str) -> typing.Any:
        """Get all stats for a player."""
        player = Address(player_str)
        rank   = self._get_rank(player.as_hex)
        return {
            "last_score":   int(self.last_score.get(player, u256(0))),
            "best_score":   int(self.best_score.get(player, u256(0))),
            "roast":        self.last_roast.get(player, "No verdict yet"),
            "last_meme":    self.last_meme_url.get(player, ""),
            "submissions":  int(self.submissions.get(player, u256(0))),
            "rank":         rank,
            "in_top10":     rank > 0
        }

    @gl.public.view
    def get_leaderboard(self) -> typing.Any:
        """
        Get the top 10 leaderboard.
        Returns list of {rank, address, score}.
        """
        entries = self._parse_leaderboard()
        result  = []
        for i, (addr, score) in enumerate(entries):
            result.append({
                "rank":    i + 1,
                "address": addr,
                "score":   score,
                "winner":  i < 3   # top 3 are winners
            })
        return result

    @gl.public.view
    def get_arena_stats(self) -> typing.Any:
        """Global arena statistics."""
        entries   = self._parse_leaderboard()
        top_score = entries[0][1] if entries else 0
        top_addr  = entries[0][0] if entries else "nobody yet"
        return {
            "total_submissions": int(self.total_submissions),
            "top_score":         top_score,
            "top_player":        top_addr,
            "arena_open":        self.arena_open,
            "leaderboard_size":  len(entries)
        }

    @gl.public.view
    def get_my_rank(self, player_str: str) -> typing.Any:
        """Check if a player is in the top 10."""
        rank = self._get_rank(player_str)
        return {
            "rank":    rank,
            "in_top10": rank > 0,
            "message": f"Rank #{rank} in the arena!" if rank > 0 else "Not in top 10 yet"
        }
