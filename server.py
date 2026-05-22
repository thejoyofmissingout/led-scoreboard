"""
Scoreboard server — Flask app with 3 endpoints:
  GET  /         iPhone game picker UI
  POST /select   Save user's game selections
  GET  /scores   Compact JSON for the Matrix Portal to poll
"""

import json
import time
from flask import Flask, render_template, request, redirect, url_for, jsonify

import espn_client
import game_store

app = Flask(__name__)

# Load persisted selections on startup
game_store.load()


@app.route("/")
def index():
    """Game picker UI — shows today's games grouped by league with checkboxes."""
    all_games = espn_client.fetch_all_games()
    selected = game_store.get_selected()

    # Group by league in preferred display order
    league_order = ["NFL", "NBA", "MLB", "NHL", "WNBA"]
    grouped = {}
    for lg in league_order:
        games = [g for g in all_games if g["lg"] == lg]
        if games:
            grouped[lg] = games

    # Any leagues not in order (shouldn't happen but be safe)
    for g in all_games:
        if g["lg"] not in grouped:
            grouped.setdefault(g["lg"], []).append(g)

    return render_template("index.html",
                           grouped=grouped,
                           selected=selected,
                           total_games=len(all_games),
                           selected_count=len(selected & {g["id"] for g in all_games}))


@app.route("/select", methods=["POST"])
def select():
    """Save selected game IDs from form POST."""
    selected_ids = set(request.form.getlist("game_id"))
    game_store.set_selected(selected_ids)
    return redirect(url_for("index"))


@app.route("/scores")
def scores():
    """
    Compact JSON endpoint polled by the Matrix Portal.
    Only returns selected games, pre-formatted for the board.
    """
    all_games = espn_client.fetch_all_games()
    selected = game_store.get_selected()
    selected_games = espn_client.get_selected_games(all_games, selected)

    # For live selected games, hit per-game summary for freshest scores
    selected_games = espn_client.refresh_live_scores(selected_games)

    # Record finish time for any newly-final games, then filter board output:
    #   - Skip pre-game (live == 0): selected but not started yet
    #   - Skip expired finals: games that ended more than 5 min ago
    board_games = []
    for g in selected_games:
        if g["live"] == 0:
            continue  # not started yet — keep it selected, just don't show on board
        if g["live"] == 2:
            game_store.record_game_ended(g["id"])
            if game_store.is_game_expired(g["id"]):
                continue  # ended >5 min ago, drop from board
        board_games.append(g)

    return jsonify({
        "ts": int(time.time()),
        "next": game_store.get_next_counter(),
        "auto": game_store.get_auto_scroll(),
        "reset": game_store.consume_reset(),
        "games": board_games,
    })


@app.route("/next", methods=["POST"])
def next_game():
    """Advance the board to the next game."""
    game_store.increment_next()
    return ("", 204)


@app.route("/autoscroll", methods=["POST"])
def autoscroll():
    """Toggle auto-scroll on/off."""
    state = game_store.toggle_auto_scroll()
    return jsonify({"auto": state})


@app.route("/reset-board", methods=["POST"])
def reset_board():
    """Signal the Matrix Portal to perform a hard reset on its next poll."""
    game_store.request_reset()
    return ("", 204)


@app.route("/refresh")
def refresh():
    """Force-refresh ESPN cache (useful for testing)."""
    games = espn_client.fetch_all_games(force=True)
    return jsonify({"refreshed": True, "total_games": len(games)})


if __name__ == "__main__":
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "unknown"

    print(f"\n{'='*50}")
    print(f"  Scoreboard server starting...")
    print(f"  Local URL: http://{local_ip}:5000")
    print(f"  Open this on your iPhone (same WiFi)")
    print(f"  Board polls: http://{local_ip}:5000/scores")
    print(f"{'='*50}\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
