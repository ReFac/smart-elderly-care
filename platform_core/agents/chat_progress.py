"""User-scoped partial replies and short, server-derived speech segments."""

from contextlib import closing
import re
from threading import Lock
from time import monotonic

BREAKS = re.compile(r"[。！？；!?;\n]")
PAUSES = re.compile(r"[，、：,]")
MAX_SENTENCES = 520
_pending_audio = {}
_lock = Lock()


def sentences(text, *, final):
    """Derive an append-only sequence so live and persisted replies use identical IDs."""
    text = text.lstrip()
    parts = []
    while text:
        maximum = 52 if not parts else 128
        minimum = 10 if not parts else 24
        cutoff = next((m.end() for m in BREAKS.finditer(text[:maximum])
                       if m.end() >= minimum), 0)
        if not cutoff and len(text) >= maximum:
            pauses = [m.end() for m in PAUSES.finditer(text[:maximum]) if m.end() >= maximum // 2]
            cutoff = pauses[-1] if pauses else maximum
        if not cutoff:
            if final:
                parts.append(text.rstrip())
            break
        parts.append(text[:cutoff].rstrip())
        text = text[cutoff:].lstrip()
    return parts


def pending(store, actor, scope, generation, request, part):
    with _lock:
        active = _pending_audio.get((store, actor, scope, generation, request))
        return active.parts[part] if active and part < len(active.parts) else None


class Progress:
    def __init__(self, store, emit, *, speak=False):
        self.store, self.emit, self.speak = store, emit, speak
        self.identity = None
        self.text = ""
        self.unsent = ""
        self.parts = []
        self.check = None
        self.last_flush = 0
        self.suppressed = False

    def bind(self, actor, scope, generation, request, check):
        self.identity = self.store, actor, scope, generation, request
        self.check = check
        with closing(self.store.connect()) as db:
            self.check(db)
        if self.speak:
            with _lock:
                _pending_audio[self.identity] = self
        self.emit({"type": "begin", "scopeKey": scope, "generation": generation, "requestId": request})

    def delta(self, text):
        if self.suppressed:
            return
        self.text += text
        self.unsent += text
        if monotonic() - self.last_flush >= .065:
            self.flush()

    def flush(self):
        if not self.unsent:
            return
        from ..store import Conflict, SignedOut

        try:
            self.authorize()
        except (Conflict, SignedOut, PermissionError, FileNotFoundError, ValueError):
            # Keep collecting the provider's usage receipt after revocation.
            self.suppressed = True
            self.unsent = ""
            self.close()
            return
        self.last_flush = monotonic()
        self.emit({"type": "text", "text": self.unsent})
        self.unsent = ""
        if self.speak:
            self.send_parts(self.text, final=False)

    def send_parts(self, text, *, final):
        parts = sentences(text, final=final)
        with _lock:
            offset = len(self.parts)
            if self.parts != parts[:offset]:
                return
            self.parts = parts
        for index in range(offset, len(parts)):
            self.emit({"type": "speech", "sentence": index})

    def complete(self, answer):
        self.authorize()
        if self.text:
            self.flush()
        else:
            self.emit({"type": "text", "text": answer})
        if self.speak:
            self.send_parts(answer, final=True)

    def authorize(self):
        with closing(self.store.connect()) as db:
            db.execute("BEGIN")
            self.check(db)

    def close(self):
        if self.identity:
            with _lock:
                if _pending_audio.get(self.identity) is self:
                    _pending_audio.pop(self.identity)
