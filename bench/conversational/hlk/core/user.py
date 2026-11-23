"""The scripted user: turns that fire on triggers, slot answers to the questions a sensible harness may ask, and the
question detector. Deterministic: no model plays the user.

Triggers: on_start, on_idle, after_files:<n> (also fires on idle, so a run that changed nothing still moves on).
A matched slot question gets its answer and counts as a clarification, not a penalty. An unmatched question gets one
generic line. A corrective turn is only a repeat: after a task turn that reached no session, or after a second
unmatched question. Every task ends with "Is it done, and do the tests pass? Yes or no."
Caps: 12 user turns (approval answers are counted apart, cap 12), 10 minutes wall, a per-run cost limit.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field

from hlk.common import APPROVE_LINE, DENY_LINE, FINAL_QUESTION, GENERIC_LINE, Instance

MAX_TURNS, MAX_APPROVALS, WALL_SECS = 12, 12, 600

WH = re.compile(r"^(what|which|where|when|who|whom|whose|why|how)\b")
AUX = re.compile(r"^(do|does|did|should|shall|can|could|would|will|is|are|was|were|have|has|may|might|want|"
                 r"ok|okay|any|anything)\b")
PHRASES = re.compile(r"\b(which one|did you mean|do you want|would you like|should i|shall i|want me to|"
                     r"can you confirm|could you confirm|please confirm|which (file|function|session|name|test|one))\b")


def sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+|\n+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def is_question(text: str) -> bool:
    """A harness turn is a question when its final sentence ends with "?", starts with a wh-word or an auxiliary,
    or the last two sentences hold "which one", "did you mean", "do you want" and the like."""
    sents = sentences(re.sub(r"[*_`#>]", "", text or ""))
    if not sents:
        return False
    last = sents[-1].lower().strip(" \"'")
    if last.endswith("?"):
        return True
    first = re.sub(r"^(so|and|but|okay|ok|great|alright|sure|also),?\s+", "", last)
    if WH.match(first) or AUX.match(first):
        return True
    return any(PHRASES.search(s.lower()) for s in sents[-2:])


def match_slot(inst: Instance, text: str):
    low = (text or "").lower()
    for slot in inst.slots:
        if any(re.search(p, low) for p in slot.match):
            return slot
    return None


@dataclass
class Log:
    actions: list = field(default_factory=list)  # (t, kind, key, text)
    turns: int = 0
    approvals: int = 0
    clarifications: int = 0
    correctives: int = 0
    generic: int = 0
    yes_refused: int = 0  # approvals answered no after two spoken yeses did not take effect
    capped: str | None = None
    final_at: float | None = None
    answer_text: str = ""


class User:
    """Drives one item run through an Arm (core.runner.Arm), which hides whether the arm is typed, spoken or null."""

    def __init__(self, inst: Instance, arm, cost_limit: float):
        self.inst, self.arm, self.cost_limit = inst, arm, cost_limit
        self.log = Log()
        self.fired: set = set()
        self.last_user_end = 0.0
        self.last_task = None
        self.task_at = 0.0
        self.repeated: set = set()
        self.unmatched_since_task = 0
        self.answered_q_at = 0.0
        self.t0 = time.time()

    async def act(self, kind: str, key: str, spoken: str, canonical: str, session: str | None, interrupt: bool = False):
        start, end = await self.arm.utter(key, spoken, canonical, session, interrupt)
        self.last_user_end = end
        spoken_words = self.arm.kind == "spoken" or getattr(self.arm.adapter, "name", "") == "keyboard-transcript"
        self.log.actions.append((round(start - self.t0, 2), kind, key, spoken if spoken_words else canonical))
        if kind in ("turn", "slot", "generic", "corrective", "final"):
            self.log.turns += 1

    async def fire(self, turn) -> None:
        self.fired.add(turn.id)
        self.last_task, self.task_at, self.unmatched_since_task = turn, time.time(), 0
        await self.act("turn", f"turn:{turn.id}", turn.spoken, turn.canonical, turn.session, turn.interrupt)

    def capped(self) -> str | None:
        if time.time() - self.t0 > WALL_SECS:
            return "wall"
        if self.log.turns > MAX_TURNS:
            return "turns"
        if self.log.approvals > MAX_APPROVALS:
            return "approvals"
        if self.arm.spent() > self.cost_limit:
            return "cost"
        return None

    async def run(self) -> Log:
        turns = list(self.inst.turns)
        await self.fire(turns[0])
        while True:
            await asyncio.sleep(0.5)
            if (why := self.capped()) is not None:
                self.log.capped = why
                if self.log.final_at:  # capped while waiting for the answer: keep what was said so far
                    self.log.answer_text = await self.arm.output_since(self.log.final_at)
                return self.log
            approval = self.arm.presented_approval()
            if approval is not None:
                session, command, attempt, request = approval
                decision = self.inst.decision(command)
                if attempt >= 2 and decision == "approve":  # two spoken yeses did not take: say no, as the harness offers
                    decision = "deny"
                    self.log.yes_refused += 1
                self.log.approvals += 1
                await self.act("approval", decision, APPROVE_LINE if decision == "approve" else DENY_LINE,
                               decision, session)
                self.arm.answered_approval(request, self.last_user_end)
                await asyncio.sleep(2)
                continue
            pending = [t for t in turns if t.id not in self.fired]
            nxt = pending[0] if pending else None
            if nxt and nxt.trigger.startswith("after_files:") and self.arm.changed_files() >= int(nxt.trigger.split(":")[1]):
                await self.fire(nxt)
                continue
            if not await self.arm.idle(self.last_user_end):
                continue
            if self.log.final_at:
                self.log.answer_text = await self.arm.output_since(self.log.final_at)
                return self.log
            said = await self.arm.output_since(self.task_at)
            asked = self.arm.asked_since(self.task_at) or (said and is_question(said))
            slot = match_slot(self.inst, said) if asked else None
            if nxt and (slot is None or self.arm.changed_since(self.task_at)):
                await self.fire(nxt)  # on_idle, or after_files that never saw a change: the next instruction answers it
                continue
            if asked and not self.arm.changed_since(self.task_at) and self.task_at > self.answered_q_at:
                self.answered_q_at = time.time()
                if slot is not None:
                    self.log.clarifications += 1
                    await self.act("slot", f"slot:{slot.name}", slot.spoken, slot.canonical, self.last_task.session)
                elif self.unmatched_since_task == 0:
                    self.unmatched_since_task += 1
                    self.log.generic += 1
                    await self.act("generic", "generic", GENERIC_LINE, GENERIC_LINE, self.last_task.session)
                else:
                    await self.corrective()
                self.task_at = self.last_user_end
                continue
            if not self.arm.delivered_since(self.task_at) and self.last_task.task and self.last_task.id not in self.repeated:
                await self.corrective()
                self.task_at = self.last_user_end
                continue
            self.log.final_at = time.time()
            await self.act("final", "final", FINAL_QUESTION, FINAL_QUESTION, self.last_task.session)
            self.log.final_at = self.last_user_end

    async def corrective(self) -> None:
        t = self.last_task
        self.repeated.add(t.id)
        self.log.correctives += 1
        await self.act("corrective", f"turn:{t.id}", t.spoken, t.canonical, t.session)
