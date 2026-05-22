"""
Display manager for 64x32 RGB LED matrix via Matrix Portal M4.
All pixel layout and rendering logic lives here.

Layout (64x32):
  Row 1 (y=1-8):   Away abbrev + score | divider | Home abbrev + score
  Row 2 (y=12-20): League badge + status string
  Color bar (y=28-31): Away color (left 32px) | Home color (right 32px)
"""

import time
import displayio
import terminalio
from adafruit_display_text import label

# Colors
WHITE   = 0xFFFFFF
DIM     = 0x333333
BLACK   = 0x000000
GREEN   = 0x00CC44
RED     = 0xFF2222
YELLOW  = 0xFFCC00


def _hex_to_int(hex_str):
    """Convert '0066cc' string to integer 0x0066cc."""
    try:
        return int(str(hex_str).lstrip("#"), 16) or 0x222222
    except Exception:
        return 0x222222


def _boost_saturation(color_int, factor=1.8):
    """Push channels away from average to increase saturation."""
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    avg = (r + g + b) // 3
    r = min(255, max(0, avg + int((r - avg) * factor)))
    g = min(255, max(0, avg + int((g - avg) * factor)))
    b = min(255, max(0, avg + int((b - avg) * factor)))
    return (r << 16) | (g << 8) | b


def _dim_color(color_int, factor=0.4):
    """Scale down a color so team color bars aren't blinding."""
    r = int(((color_int >> 16) & 0xFF) * factor)
    g = int(((color_int >> 8) & 0xFF) * factor)
    b = int((color_int & 0xFF) * factor)
    return (r << 16) | (g << 8) | b


def fade_to(display, new_group, steps=8, delay=0.12):
    """Fade display to black, swap to new_group, fade back in.
    steps=8 matches bit_depth=3 (8 hardware brightness levels).
    Total transition time: steps * delay * 2 = ~0.64s at defaults.
    """
    for i in range(steps, -1, -1):
        display.brightness = i / steps
        time.sleep(delay)
    display.root_group = new_group
    for i in range(steps + 1):
        display.brightness = i / steps
        time.sleep(delay)


def make_scorebug(game):
    """
    Build a displayio.Group for one game dict.
    Returns the group; assign to display.root_group to show it.

    game keys: id, lg, at, ht, as, hs, ac, hc, st, live
    """
    group = displayio.Group()

    away_color = _hex_to_int(game.get("ac", "444444"))
    home_color = _hex_to_int(game.get("hc", "444444"))
    live = game.get("live", 0)

    # --- Background ---
    bg_bitmap = displayio.Bitmap(64, 32, 1)
    bg_palette = displayio.Palette(1)
    bg_palette[0] = BLACK
    group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

    # --- Color bar at bottom (y=28, height=4) ---
    away_palette = displayio.Palette(1)
    away_palette[0] = _dim_color(away_color)
    away_bar_bmp = displayio.Bitmap(32, 4, 1)
    group.append(displayio.TileGrid(away_bar_bmp, pixel_shader=away_palette, x=0, y=28))

    home_palette = displayio.Palette(1)
    home_palette[0] = _dim_color(home_color)
    home_bar_bmp = displayio.Bitmap(32, 4, 1)
    group.append(displayio.TileGrid(home_bar_bmp, pixel_shader=home_palette, x=32, y=28))

    away_score = str(game.get("as", "--"))
    home_score = str(game.get("hs", "--"))
    score_color_away = GREEN if (live == 2 and int(game.get("as", 0) or 0) > int(game.get("hs", 0) or 0)) else WHITE
    score_color_home = GREEN if (live == 2 and int(game.get("hs", 0) or 0) > int(game.get("as", 0) or 0)) else WHITE

    # Shorten abbreviations to 2 chars when scores hit triple digits to prevent overlap
    at = game.get("at", "??")
    ht = game.get("ht", "??")
    if len(away_score) >= 3:
        at = at[:2]
    if len(home_score) >= 3:
        ht = ht[:2]

    # --- Away team abbreviation (far left) ---
    away_lbl = label.Label(terminalio.FONT, text=at, color=away_color, x=1, y=5)
    group.append(away_lbl)

    # --- Away score (right-aligned to just before divider) ---
    away_score_x = 29 - len(away_score) * 6
    away_score_lbl = label.Label(terminalio.FONT, text=away_score,
                                 color=score_color_away, x=away_score_x, y=5)
    group.append(away_score_lbl)

    # --- Home score (left-aligned just after divider) ---
    home_score_lbl = label.Label(terminalio.FONT, text=home_score,
                                 color=score_color_home, x=33, y=5)
    group.append(home_score_lbl)

    # --- Home team abbreviation (far right) ---
    home_x = 64 - len(ht) * 6
    home_lbl = label.Label(terminalio.FONT, text=ht, color=home_color, x=home_x, y=5)
    group.append(home_lbl)

    # --- Status string (center, row 2) ---
    status_text = game.get("st", "")
    # Center the status text: terminalio font is 6px wide per char
    status_x = max(0, (64 - len(status_text) * 6) // 2)
    status_lbl = label.Label(terminalio.FONT, text=status_text,
                              color=WHITE, x=status_x, y=14)
    group.append(status_lbl)

    # --- League badge (small, bottom-left above color bar) ---
    lg = game.get("lg", "")[:4]
    lg_lbl = label.Label(terminalio.FONT, text=lg, color=DIM, x=1, y=23)
    group.append(lg_lbl)

    return group


def draw_message(display, line1, line2="", color=WHITE):
    """
    Show a simple one or two-line centered message.
    Used for errors and idle states.
    """
    group = displayio.Group()

    bg_bitmap = displayio.Bitmap(64, 32, 1)
    bg_palette = displayio.Palette(1)
    bg_palette[0] = BLACK
    group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

    x1 = max(0, (64 - len(line1) * 6) // 2)
    y1 = 9 if not line2 else 5
    lbl1 = label.Label(terminalio.FONT, text=line1, color=color, x=x1, y=y1)
    group.append(lbl1)

    if line2:
        x2 = max(0, (64 - len(line2) * 6) // 2)
        lbl2 = label.Label(terminalio.FONT, text=line2, color=DIM, x=x2, y=20)
        group.append(lbl2)

    display.root_group = group
