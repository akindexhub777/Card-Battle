# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

import typing


class CardBattle(gl.Contract):
    """
    CardBattle — GenLayer Intelligent Contract
    LLM arbitrates on-chain card duels.
    """

    wins:      TreeMap[Address, u256]
    losses:    TreeMap[Address, u256]
    points:    TreeMap[Address, u256]

    # pending challenger
    p_challenger: Address
    p_card:       str
    p_power:      u256

    # last battle result per player
    last_narrative: TreeMap[Address, str]
    last_result:    TreeMap[Address, str]
    verdicts:       TreeMap[Address, str]

    def __init__(self):
        self.p_challenger = Address("0x0000000000000000000000000000000000000000")
        self.p_card       = ""
        self.p_power      = u256(0)

    def _zero(self) -> Address:
        return Address("0x0000000000000000000000000000000000000000")

    # ── challenge ────────────────────────────────────────────────────

    @gl.public.write
    def challenge(self, card_name: str, card_power: u256) -> typing.Any:
        player = gl.message.sender_address

        if not card_name or len(card_name) < 1:
            raise gl.vm.UserError("Card name cannot be empty")

        if self.p_challenger == self._zero():
            # First player — register as challenger
            self.p_challenger = player
            self.p_card       = card_name
            self.p_power      = card_power
            return {
                "status":  "waiting",
                "message": "Card registered. Waiting for opponent...",
                "card":    card_name,
                "power":   int(card_power)
            }

        if self.p_challenger == player:
            return {"status": "error", "message": "Cannot battle yourself — wait for another player"}

        # Second player — trigger battle
        ch_card  = self.p_card
        ch_power = int(self.p_power)
        def_card  = card_name
        def_power = int(card_power)
        challenger = self.p_challenger

        # Reset pending state BEFORE LLM call
        self.p_challenger = self._zero()
        self.p_card       = ""
        self.p_power      = u256(0)

        # ── GenLayer LLM arbitration ──
        narrative = gl.eq_principle.prompt_non_comparative(
            lambda: f"{ch_card}|{ch_power}|{def_card}|{def_power}",
            task=(
                f"You are an epic battle narrator for an on-chain card game. "
                f"Two cards are dueling:\n"
                f"- CHALLENGER: '{ch_card}' (power: {ch_power})\n"
                f"- DEFENDER: '{def_card}' (power: {def_power})\n\n"
                f"Decide the winner based on card name, lore, and power. "
                f"Narrate the battle in 2 epic sentences. "
                f"Then declare the winner.\n"
                f"End with EXACTLY one of these two lines:\n"
                f"WINNER: CHALLENGER\n"
                f"WINNER: DEFENDER"
            ),
            criteria=(
                "Must end with exactly 'WINNER: CHALLENGER' or 'WINNER: DEFENDER'. "
                "Narrative must reference both card names. "
                "Power influences but does not solely decide — card lore matters too."
            )
        )

        challenger_wins = "WINNER: CHALLENGER" in narrative.upper()

        if challenger_wins:
            self.wins[challenger]   = self.wins.get(challenger, u256(0)) + u256(1)
            self.losses[player]     = self.losses.get(player, u256(0)) + u256(1)
            self.points[challenger] = self.points.get(challenger, u256(0)) + u256(10)
        else:
            self.wins[player]       = self.wins.get(player, u256(0)) + u256(1)
            self.losses[challenger] = self.losses.get(challenger, u256(0)) + u256(1)
            self.points[player]     = self.points.get(player, u256(0)) + u256(10)

        self.last_narrative[challenger] = narrative
        self.last_narrative[player]     = narrative
        self.last_result[challenger]    = "WIN" if challenger_wins else "LOSS"
        self.last_result[player]        = "LOSS" if challenger_wins else "WIN"

        return {
            "status":          "battle_complete",
            "narrative":       narrative,
            "winner":          "challenger" if challenger_wins else "defender",
            "challenger_card": ch_card,
            "defender_card":   def_card
        }

    # ── dispute ──────────────────────────────────────────────────────

    @gl.public.write
    def dispute_result(self, reason: str) -> typing.Any:
        player = gl.message.sender_address
        last   = self.last_narrative.get(player, "")

        if not last:
            raise gl.vm.UserError("No battle to dispute")

        verdict = gl.eq_principle.prompt_non_comparative(
            lambda: reason,
            task=(
                f"You are a trustless blockchain arbitrator reviewing a card battle dispute.\n"
                f"Original battle: {last[:300]}\n"
                f"Player dispute reason: {reason}\n"
                f"Is the dispute VALID or INVALID?"
            ),
            criteria=(
                "Reply with VALID or INVALID followed by one sentence. "
                "Only overturn if the narrative was clearly wrong."
            )
        )

        self.verdicts[player] = verdict

        overturned = False
        if "VALID" in verdict.upper()[:10]:
            current_l = self.losses.get(player, u256(0))
            if current_l > u256(0):
                self.losses[player] = current_l - u256(1)
                self.wins[player]   = self.wins.get(player, u256(0)) + u256(1)
                self.points[player] = self.points.get(player, u256(0)) + u256(10)
            overturned = True

        return {"verdict": verdict, "overturned": overturned}

    @gl.public.write
    def cancel_challenge(self) -> typing.Any:
        player = gl.message.sender_address
        if self.p_challenger != player:
            raise gl.vm.UserError("No pending challenge to cancel")
        self.p_challenger = self._zero()
        self.p_card       = ""
        self.p_power      = u256(0)
        return {"status": "cancelled"}

    # ── view ──────────────────────────────────────────────────────────

    @gl.public.view
    def get_player_stats(self, player_str: str) -> typing.Any:
        player = Address(player_str)
        return {
            "wins":           int(self.wins.get(player, u256(0))),
            "losses":         int(self.losses.get(player, u256(0))),
            "points":         int(self.points.get(player, u256(0))),
            "last_result":    self.last_result.get(player, "No battles yet"),
            "last_narrative": self.last_narrative.get(player, ""),
            "verdict":        self.verdicts.get(player, "No dispute filed")
        }

    @gl.public.view
    def get_pending_battle(self) -> typing.Any:
        challenger = self.p_challenger
        if challenger == self._zero():
            return {"status": "no_pending", "challenger": None, "card": None, "power": 0}
        return {
            "status":     "waiting_for_opponent",
            "challenger": challenger.as_hex,
            "card":       self.p_card,
            "power":      int(self.p_power)
        }

    @gl.public.view
    def get_last_narrative(self, player_str: str) -> str:
        return self.last_narrative.get(Address(player_str), "No battles yet")

    @gl.public.view
    def get_verdict(self, player_str: str) -> str:
        return self.verdicts.get(Address(player_str), "No dispute filed")
