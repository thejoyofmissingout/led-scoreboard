"""
Display manager for 64x32 RGB LED matrix via Matrix Portal M4.
All pixel layout and rendering logic lives here.

Layout (64x32):
  Row 1 (y=1-8):   Away abbrev + score | divider | Home abbrev + score
  Row 2 (y=11-27): Status string (quarter/time)
  Row 3 (y=28-31): Color bars — Away (left 32px) | Home (right 32px)
"""

import time
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_fancyled.adafruit_fancyled import CHSV, mix

# Colors
WHITE   = 0xFFFFFF
DIM     = 0x333333
BLACK   = 0x000000
GREEN   = 0x00CC44
RED     = 0xFF2222
YELLOW  = 0xFFCC00
ORANGE  = 0xFF8800


def _hex_to_int(hex_str):
    try:
        return int(str(hex_str).lstrip("#"), 16) or 0x222222
    except Exception:
        return 0x222222


def _boost_saturation(color_int, factor=1.8):
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    avg = (r + g + b) // 3
    r = min(255, max(0, avg + int((r - avg) * factor)))
    g = min(255, max(0, avg + int((g - avg) * factor)))
    b = min(255, max(0, avg + int((b - avg) * factor)))
    return (r << 16) | (g << 8) | b


def _dim_color(color_int, factor=0.4):
    r = int(((color_int >> 16) & 0xFF) * factor)
    g = int(((color_int >> 8) & 0xFF) * factor)
    b = int((color_int & 0xFF) * factor)
    return (r << 16) | (g << 8) | b


def _rgb_to_chsv(rgb_int):
    r = ((rgb_int >> 16) & 0xFF) / 255.0
    g = ((rgb_int >> 8) & 0xFF) / 255.0
    b = (rgb_int & 0xFF) / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    v = mx
    d = mx - mn
    s = 0.0 if mx == 0 else d / mx
    if d == 0:
        h = 0.0
    elif mx == r:
        h = (((g - b) / d) % 6) / 6.0
    elif mx == g:
        h = ((b - r) / d + 2) / 6.0
    else:
        h = ((r - g) / d + 4) / 6.0
    return CHSV(h, s, v)


def fade_in_bars(away_palette, away_target, home_palette, home_target, steps=12, delay=0.02):
    black = CHSV(0, 0, 0)
    to_away = _rgb_to_chsv(away_target)
    to_home = _rgb_to_chsv(home_target)
    for i in range(1, steps + 1):
        t = i / steps
        away_palette[0] = mix(black, to_away, t).pack()
        home_palette[0] = mix(black, to_home, t).pack()
        time.sleep(delay)


def _collect_colors(group):
    """Snapshot original colors from all Label and TileGrid children."""
    entries = []
    for i in range(len(group)):
        child = group[i]
        if hasattr(child, 'color') and child.color is not None and child.color != 0:
            entries.append((child, None, child.color))
        elif hasattr(child, 'pixel_shader'):
            ps = child.pixel_shader
            try:
                for j in range(len(ps)):
                    c = ps[j]
                    if c and c != 0:
                        entries.append((None, (ps, j), c))
            except (IndexError, TypeError, AttributeError):
                pass
    return entries


def _apply_brightness(entries, factor):
    """Set each collected color to factor * its original value."""
    for child, ps_info, orig in entries:
        c = orig
        r = min(255, int(((c >> 16) & 0xFF) * factor))
        g = min(255, int(((c >> 8) & 0xFF) * factor))
        b = min(255, int((c & 0xFF) * factor))
        val = (r << 16) | (g << 8) | b
        if child is not None:
            child.color = val if val != 0 else 1
        else:
            ps, j = ps_info
            ps[j] = val


def slide_to(display, old_group, new_group, steps=16, delay=0.04):
    # Old group fades out as it slides left; new group slides in at full brightness
    wrapper = displayio.Group()
    old_colors = []
    try:
        old_colors = _collect_colors(old_group)
        new_group.x = 64
        wrapper.append(new_group)
        display.root_group = wrapper
        old_group.x = 0
        wrapper.append(old_group)
        for i in range(1, steps + 1):
            offset = (64 * i) // steps
            old_group.x = -offset
            new_group.x = 64 - offset
            _apply_brightness(old_colors, (steps - i) / steps)
            time.sleep(delay)
    except Exception as e:
        print("[slide] error:", e)
    finally:
        try:
            for i in range(len(wrapper)):
                if wrapper[i] is new_group:
                    del wrapper[i]
                    break
        except Exception:
            pass
        display.root_group = new_group
        new_group.x = 0


def _draw_mlb_extras(group, game):
    """
    Row 3 MLB-live widget: 64×9 bitmap placed at y=19.
    Left:   3 out-dots  (red=out, dim=empty)     — same row as diamond 3B/1B
    Center: tilted diamond, 4 bases as 2×2 blocks (yellow=occupied, dim=empty)
    Right:  3 ball-dots (green) upper, 2 strike-dots (orange) lower
    """
    runners = game.get("runners", 0)
    outs    = game.get("outs",    0)
    balls   = game.get("balls",   0)
    strikes = game.get("strikes", 0)

    pal = displayio.Palette(6)
    pal[0] = BLACK
    pal[1] = 0x303030  # dim (empty)
    pal[2] = YELLOW    # base occupied
    pal[3] = RED       # out
    pal[4] = GREEN     # ball
    pal[5] = ORANGE    # strike

    bmp = displayio.Bitmap(64, 9, 6)

    def sq(bx, by, c):
        bmp[bx,   by  ] = c
        bmp[bx+1, by  ] = c
        bmp[bx,   by+1] = c
        bmp[bx+1, by+1] = c

    # Diamond — 2×2 blocks; screen y = bitmap_y + 19
    sq(30, 1, 2 if (runners & 0x2) else 1)  # 2B  (bit 1) → screen y=20-21
    sq(26, 4, 2 if (runners & 0x4) else 1)  # 3B  (bit 2) → screen y=23-24
    sq(34, 4, 2 if (runners & 0x1) else 1)  # 1B  (bit 0) → screen y=23-24
    sq(30, 7, 1)                             # HP  always dim → screen y=26-27

    # Outs — 3 dots left of diamond, same row as 3B/1B
    for i in range(3):
        sq(2 + i * 5, 4, 3 if i < outs else 1)

    # Balls — 3 dots upper-right, same row as 2B
    for i in range(3):
        sq(42 + i * 5, 1, 4 if i < balls else 1)

    # Strikes — 2 dots lower-right, same row as HP
    for i in range(2):
        sq(44 + i * 5, 7, 5 if i < strikes else 1)

    group.append(displayio.TileGrid(bmp, pixel_shader=pal, x=0, y=19))


def _draw_nba_extras(group, game):
    """
    Row 3 NBA/WNBA-live widget: 64×9 bitmap placed at y=19.
    Left:   away bonus indicator (2×3 block, yellow=in bonus)
    Center: shot clock depletion bar (24px=24s, green→yellow→red)
    Right:  home bonus indicator
    """
    shot_clock = game.get("shot_clock", -1)
    bonus_away = game.get("bonus_away", False)
    bonus_home = game.get("bonus_home", False)

    pal = displayio.Palette(5)
    pal[0] = BLACK
    pal[1] = 0x303030  # dim (empty)
    pal[2] = GREEN     # shot clock safe (>8s)
    pal[3] = YELLOW    # shot clock warning (5-8s) / bonus indicator
    pal[4] = RED       # shot clock danger (≤5s)

    bmp = displayio.Bitmap(64, 9, 5)

    # Away bonus indicator: 2×3 block at x=2-3, y=3-5
    ba = 3 if bonus_away else 1
    for bx in (2, 3):
        for by in (3, 4, 5):
            bmp[bx, by] = ba

    # Home bonus indicator: 2×3 block at x=61-62, y=3-5
    bh = 3 if bonus_home else 1
    for bx in (61, 62):
        for by in (3, 4, 5):
            bmp[bx, by] = bh

    # Shot clock bar: 24px at x=20-43, y=3-5 (1px per second)
    if shot_clock >= 0:
        sc = min(24, max(0, int(shot_clock)))
        bar_c = 2 if sc > 8 else (3 if sc > 5 else 4)
        for xi in range(24):
            c = bar_c if xi < sc else 1
            for by in (3, 4, 5):
                bmp[20 + xi, by] = c

    group.append(displayio.TileGrid(bmp, pixel_shader=pal, x=0, y=19))


def make_scorebug(game):
    group = displayio.Group()

    away_color = _hex_to_int(game.get("ac", "444444"))
    home_color = _hex_to_int(game.get("hc", "444444"))
    live = game.get("live", 0)

    bg_bitmap = displayio.Bitmap(64, 32, 1)
    bg_palette = displayio.Palette(1)
    bg_palette[0] = BLACK
    group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

    away_dim = _dim_color(away_color, factor=0.6)
    away_palette = displayio.Palette(1)
    away_palette[0] = BLACK
    away_bar_bmp = displayio.Bitmap(32, 4, 1)

    home_dim = _dim_color(home_color, factor=0.6)
    home_palette = displayio.Palette(1)
    home_palette[0] = BLACK
    home_bar_bmp = displayio.Bitmap(32, 4, 1)

    away_score = str(game.get("as", "--"))
    home_score = str(game.get("hs", "--"))
    try:
        as_int = int(away_score) if away_score not in ("--", "") else -1
        hs_int = int(home_score) if home_score not in ("--", "") else -1
    except (ValueError, TypeError):
        as_int = -1
        hs_int = -1
    score_color_away = GREEN if (live == 2 and as_int >= 0 and hs_int >= 0 and as_int > hs_int) else WHITE
    score_color_home = GREEN if (live == 2 and as_int >= 0 and hs_int >= 0 and hs_int > as_int) else WHITE

    at = str(game.get("at", "??"))
    ht = str(game.get("ht", "??"))
    if len(away_score) >= 3:
        at = at[:2]
    if len(home_score) >= 3:
        ht = ht[:2]

    # Away: [TEAM SCORE] left-anchored
    away_lbl = label.Label(terminalio.FONT, text=at, color=away_color, x=0, y=5)
    group.append(away_lbl)

    away_score_x = len(at) * 6 + 1
    away_score_lbl = label.Label(terminalio.FONT, text=away_score,
                                 color=score_color_away, x=away_score_x, y=5)
    group.append(away_score_lbl)

    # Home: [SCORE TEAM] right-anchored
    home_x = 65 - len(ht) * 6
    home_lbl = label.Label(terminalio.FONT, text=ht, color=home_color, x=home_x, y=5)
    group.append(home_lbl)

    home_score_x = home_x - 1 - len(home_score) * 6
    home_score_lbl = label.Label(terminalio.FONT, text=home_score,
                                 color=score_color_home, x=home_score_x, y=5)
    group.append(home_score_lbl)

    status_text = str(game.get("st", "") or "")
    status_x = max(0, (64 - len(status_text) * 6) // 2)
    status_lbl = label.Label(terminalio.FONT, text=status_text,
                              color=WHITE, x=status_x, y=14)
    group.append(status_lbl)

    # Sport-specific live extras in the space between status and bars
    lg = str(game.get("lg", "")).strip()
    if live == 1 and lg == "MLB":
        _draw_mlb_extras(group, game)
    elif live == 1 and lg in ("NBA", "WNBA"):
        _draw_nba_extras(group, game)

    # Bars appended last so they render on top of any transparent label bounding box overhang
    group.append(displayio.TileGrid(away_bar_bmp, pixel_shader=away_palette, x=0, y=28))
    group.append(displayio.TileGrid(home_bar_bmp, pixel_shader=home_palette, x=32, y=28))

    return group, away_palette, away_dim, home_palette, home_dim


def draw_message(display, line1, line2="", color=WHITE):
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
