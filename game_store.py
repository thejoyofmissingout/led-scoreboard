"""
Thread-safe persistence for selected game IDs.
Backed by selections.json so selections survive server restarts.
"""

import json
import os
import threading
import tempfile
import time

STORE_FILE = os.path.join(os.path.dirname(__file__), "selections.json")

_lock = threading.Lock()
_selected: set[str] = set()
_next_counter: int = 0
_auto_scroll: bool = True
_game_ended_times: dict[str, float] = {}  # game_id -> epoch when first seen as final
_reset_requested: bool = False

FINAL_DISPLAY_SECS = 300  # 5 minutes


def load():
    """Load selections from disk into memory. Call once at startup."""
    global _selected
    try:
        with open(STORE_FILE) as f:
            data = json.load(f)
            with _lock:
                _selected = set(data.get("selected", []))
    except FileNotFoundError:
        _selected = set()
    except Exception as e:
        print(f"[store] Load error: {e}")
        _selected = set()


def save(ids: set[str]):
    """Atomically write selections to disk."""
    try:
        dir_ = os.path.dirname(STORE_FILE)
        with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as tmp:
            json.dump({"selected": list(ids)}, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, STORE_FILE)
    except Exception as e:
        print(f"[store] Save error: {e}")


def get_selected() -> set[str]:
    with _lock:
        return set(_selected)


def set_selected(ids: set[str]):
    global _selected
    with _lock:
        _selected = set(ids)
    save(_selected)


def get_next_counter() -> int:
    with _lock:
        return _next_counter


def increment_next() -> int:
    global _next_counter
    with _lock:
        _next_counter += 1
        return _next_counter


def get_auto_scroll() -> bool:
    with _lock:
        return _auto_scroll


def toggle_auto_scroll() -> bool:
    global _auto_scroll
    with _lock:
        _auto_scroll = not _auto_scroll
        return _auto_scroll


def request_reset() -> None:
    global _reset_requested
    with _lock:
        _reset_requested = True


def consume_reset() -> bool:
    """Return True and clear the flag if a board reset was requested."""
    global _reset_requested
    with _lock:
        if _reset_requested:
            _reset_requested = False
            return True
        return False


def record_game_ended(game_id: str):
    """Record the first time a game is seen as final. Idempotent."""
    with _lock:
        if game_id not in _game_ended_times:
            _game_ended_times[game_id] = time.time()


def is_game_expired(game_id: str) -> bool:
    """True if the game ended more than FINAL_DISPLAY_SECS ago."""
    with _lock:
        ended_at = _game_ended_times.get(game_id)
    if ended_at is None:
        return False
    return (time.time() - ended_at) > FINAL_DISPLAY_SECS
