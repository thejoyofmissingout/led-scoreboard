"""
Matrix Portal M4 — Live Scoreboard
Polls Mac server every 30s for selected game scores.
Rotates through selected games on the 64x32 LED matrix.
"""

import time
import gc
import board
import microcontroller
from watchdog import WatchDogMode
from adafruit_matrixportal.matrix import Matrix

import os
import display_mgr
import network_mgr
import numberwang

SERVER_URL = os.getenv("SERVER_URL")

POLL_LIVE        = 2    # seconds between polls when games are live
POLL_IDLE        = 15   # seconds between polls when no live games
GAME_DISPLAY_SEC = 10   # seconds each game stays on screen
RETRY_DELAY      = 10   # seconds before retrying after WiFi failure

# Initialize display via Matrix class (handles all pin config for Matrix Portal M4)
matrix = Matrix(width=64, height=32, bit_depth=3)
display = matrix.display

print("Matrix Portal Scoreboard starting...")
display_mgr.draw_message(display, "CONNECTING", "to WiFi...")

# Connect to WiFi
session = None
for attempt in range(3):
    session = network_mgr.init_network()
    if session:
        break
    print("WiFi attempt", attempt + 1, "failed, retrying...")
    display_mgr.draw_message(display, "WIFI ERROR", "retrying...", color=0xFF4400)
    time.sleep(RETRY_DELAY)

if not session:
    display_mgr.draw_message(display, "NO WIFI", "check secrets", color=0xFF0000)
    while True:
        time.sleep(60)

display_mgr.draw_message(display, "CONNECTED", "loading...")

# Arm hardware watchdog — resets board if main loop hangs >12s (e.g. stuck network call)
microcontroller.watchdog.timeout = 12
microcontroller.watchdog.mode = WatchDogMode.RESET

# Main state
games = []
game_index = 0
last_poll = 0
last_switch = 0
last_scores = {}  # {game_id: (away_score, home_score)} — track for change detection
last_next = 0    # track server's next counter for manual advance
auto_scroll = True  # mirrors server's auto-scroll setting
current_group = None
consecutive_failures = 0
MAX_FAILURES = 5


def show_game(idx):
    global current_group
    gc.collect()
    game = games[idx % len(games)]
    print("[display]", game["lg"], game["at"], game["as"] + "-" + game["hs"], game["ht"], "|", game["st"])
    try:
        new_group, away_pal, away_target, home_pal, home_target = display_mgr.make_scorebug(game)
        if current_group is not None:
            display_mgr.slide_to(display, current_group, new_group)
        else:
            display.root_group = new_group
        display_mgr.fade_in_bars(away_pal, away_target, home_pal, home_target)
        current_group = new_group
    except Exception as e:
        print("[display] Error:", e)
        current_group = None
    gc.collect()


while True:
    microcontroller.watchdog.feed()
    now = time.monotonic()

    # Poll faster when games are live
    poll_interval = POLL_LIVE if any(g["live"] == 1 for g in games) else POLL_IDLE

    # Poll server on interval
    if now - last_poll >= poll_interval or last_poll == 0:
        print("[poll] Fetching scores...")
        data = network_mgr.fetch_scores(session, SERVER_URL)

        if data is not None:
            consecutive_failures = 0
            if data.get("reset"):
                print("[reset] Remote reset")
                microcontroller.reset()

            new_games = data.get("games", [])
            games = new_games
            auto_scroll = data.get("auto", True)

            # Check for manual next button press
            server_next = data.get("next", 0)
            if server_next > last_next:
                last_next = server_next
                game_index = (game_index + 1) % len(games) if games else 0
                last_switch = 0  # Show immediately
                print("[next] Manual advance")

            # Check for score changes — jump to whichever game just scored
            scored_idx = None
            for i, game in enumerate(games):
                gid = game["id"]
                current = (game["as"], game["hs"])
                if gid in last_scores and last_scores[gid] != current:
                    old_as, old_hs = last_scores[gid]
                    print("[score] Change:", game["at"], game["as"], "-", game["hs"], game["ht"])
                    try:
                        fired = numberwang.check(display, game, old_as, old_hs)
                    except Exception as e:
                        print("[numberwang] Error:", e)
                        fired = False
                    if fired:
                        current_group = None  # animation detached the old group; skip slide
                    scored_idx = i
                last_scores[gid] = current

            if scored_idx is not None:
                game_index = scored_idx
                last_switch = 0  # Show immediately

            print("[poll]", len(games), "game(s)")
        else:
            consecutive_failures += 1
            print("[poll] Server unreachable — keeping last data (" + str(consecutive_failures) + "/" + str(MAX_FAILURES) + ")")
            if consecutive_failures >= MAX_FAILURES:
                print("[poll] Too many failures, resetting...")
                microcontroller.reset()
            if not games:
                display_mgr.draw_message(display, "NO SERVER", SERVER_URL[7:20] if SERVER_URL else "")

        last_poll = now
        gc.collect()

    # Show current game; rotate on timer only if auto_scroll is on
    if games:
        timer_expired = (now - last_switch >= GAME_DISPLAY_SEC)
        should_rotate = auto_scroll and timer_expired and len(games) > 1
        if last_switch == 0 or should_rotate:
            show_game(game_index)
            game_index = (game_index + 1) % len(games)
            last_switch = now
    else:
        if now - last_poll < 2:
            display_mgr.draw_message(display, "NO GAMES", "pick on iPhone")

    time.sleep(0.25)
