"""Script and voiceover approval gates shared by the CLI and the studio.

`--auto` skips every gate. `--approve-script` / `--approve-voice` skip one.
Studio injects an ApprovalGate so HTTP Approve / Edit / Regen unblocks the
same `video_pipeline.run` thread — there is no second pipeline.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

Say = Callable[[str], None]


class ApprovalGate:
    """Park a pipeline thread until the operator decides."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self.pending: dict[str, Any] | None = None
        self.answer = "ok"
        self.edits: dict[str, Any] = {}
        self.log: list[dict[str, Any]] = []
        self.closed = False

    def say(self, text: str = "") -> None:
        line = {"t": time.time(), "text": str(text)}
        with self._lock:
            self.log.append(line)

    def wait(self, prompt: str, options: tuple[str, ...], payload: dict[str, Any] | None = None) -> str:
        if self.closed:
            return "quit"
        with self._lock:
            self.pending = {
                "prompt": prompt,
                "options": list(options),
                "payload": payload or {},
                "stage": (payload or {}).get("stage") or "ask",
            }
            self.answer = "ok"
            self.edits = {}
            self._event.clear()
        self.say(f"  [gate] {prompt}  waiting {','.join(options)}")
        self._event.wait()
        if self.closed:
            return "quit"
        return self.answer or "ok"

    def decide(self, answer: str, edits: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self.answer = (answer or "ok").strip().lower()
            self.edits = dict(edits or {})
            self.pending = None
            self._event.set()
        self.say(f"  [gate] decided {self.answer}")
        return {"ok": True, "answer": self.answer}

    def close(self, answer: str = "quit") -> None:
        self.closed = True
        self.decide(answer)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pending": dict(self.pending) if self.pending else None,
                "log": list(self.log[-200:]),
                "closed": self.closed,
            }


_GATE: ApprovalGate | None = None
_SAY: Say | None = None


def set_gate(gate: ApprovalGate | None) -> None:
    global _GATE
    _GATE = gate


def set_say(fn: Say | None) -> None:
    global _SAY
    _SAY = fn


def current_gate() -> ApprovalGate | None:
    return _GATE


def say(text: str = "") -> None:
    if _SAY is not None:
        _SAY(text)
        return
    if _GATE is not None:
        _GATE.say(text)
    print(text)


def ask(prompt: str, options: tuple[str, ...], auto: bool, payload: dict[str, Any] | None = None) -> str:
    if auto:
        say(f"  {prompt} -> ok (auto)")
        return "ok"
    if _GATE is not None:
        return _GATE.wait(prompt, options, payload)
    joined = "/".join(options)
    while True:
        answer = input(f"  {prompt} [{joined}]: ").strip().lower()
        if answer in options:
            return answer
        if answer == "" and "ok" in options:
            return "ok"
        say(f"  Please answer one of: {joined}")


def script_approved(auto: bool, flag: bool) -> bool:
    return bool(auto or flag)


def voice_approved(auto: bool, flag: bool) -> bool:
    return bool(auto or flag)


def review_script(
    review: dict[str, Any],
    *,
    auto: bool,
    approve_script: bool,
) -> str:
    """Show hook / body / bait and wait for OK unless skipped."""
    lang = review.get("language") or ""
    say(f"  --- script review ({lang}) ---")
    say(f"  HOOK:  {review.get('hook')}")
    if review.get("punch"):
        say(f"  PUNCH: {review.get('punch')}")
    say(f"  BODY:  {review.get('body_summary')}")
    say(f"  BAIT:  {review.get('outro_bait')}")
    book = review.get("bookends") or {}
    if book.get("clean_body") is False:
        say("  [warn] curses leaked into the body — lock_bookends should have stripped them")
    if script_approved(auto, approve_script):
        say("  script -> ok (approved)")
        return "ok"
    return ask(
        "Script good? Start production (voice + render) after OK",
        ("ok", "edit", "quit"),
        False,
        payload={"stage": "script", **review},
    )


def review_voice(
    *,
    language: str,
    path: str,
    seconds: float | None,
    auto: bool,
    approve_voice: bool,
) -> str:
    dur = f"{seconds:.1f}s" if seconds else "unknown duration"
    say(f"  --- voice review ({language}) ---")
    say(f"  file: {path}  ({dur})")
    if voice_approved(auto, approve_voice):
        say("  voice -> ok (approved)")
        return "ok"
    return ask(
        "Approve this voiceover and assemble the dubbed master?",
        ("ok", "regen", "quit"),
        False,
        payload={"stage": "voice", "language": language, "path": path, "seconds": seconds},
    )
