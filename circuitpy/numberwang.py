"""
THAT'S NUMBERWANG!
Animations triggered by specific score conditions on the 64x32 LED matrix.
"""

import gc
import time
import random
import displayio
import terminalio
import microcontroller
from adafruit_display_text import label

# Colors
BLACK  = 0x000000
WHITE  = 0xFFFFFF
GOLD   = 0xFFCC00
RED    = 0xFF2200
BLUE   = 0x0044FF
GREEN  = 0x00CC44
PURPLE = 0x8800FF
ORANGE = 0xFF6600
PINK   = 0xFF1493

CHAOS_COLORS  = [RED, ORANGE, GOLD, GREEN, BLUE, PURPLE, WHITE, PINK]

_WANG_NAMES = ("", "", "DOUBLEWANG", "TRIPLEWANG", "QUADWANG", "MEGAWANG")

# Triangle wave for bounce/pulse — avoids importing math
_BOUNCE_Y = (0, 1, 2, 3, 4, 3, 2, 1, 0, -1, -2, -3, -4, -3, -2, -1)

# Palette indices for fireworks bitmap (0=black, 1-8=colors)
_SPARK_COLORS = [RED, ORANGE, GOLD, WHITE, GREEN, BLUE, PURPLE, PINK]


def _lerp_color(c1, c2, t):
    """Smoothly interpolate between two colors. t in [0.0, 1.0]."""
    r = int(((c1 >> 16) & 0xFF) * (1 - t) + ((c2 >> 16) & 0xFF) * t)
    g = int(((c1 >>  8) & 0xFF) * (1 - t) + ((c2 >>  8) & 0xFF) * t)
    b = int(( c1        & 0xFF) * (1 - t) + ( c2        & 0xFF) * t)
    return (r << 16) | (g << 8) | b


def _flash(display, colors, hold=0.12, steps=20):
    """Flash through colors with smooth cross-fades. Reuses one group/bitmap."""
    bmp = displayio.Bitmap(64, 32, 1)
    pal = displayio.Palette(1)
    group = displayio.Group()
    group.append(displayio.TileGrid(bmp, pixel_shader=pal))
    display.root_group = group
    prev = BLACK
    for color in colors:
        microcontroller.watchdog.feed()
        for i in range(steps + 1):
            pal[0] = _lerp_color(prev, color, i / steps)
            time.sleep(hold / steps)
        time.sleep(hold)
        prev = color
    for i in range(steps + 1):
        pal[0] = _lerp_color(prev, BLACK, i / steps)
        time.sleep(hold / steps)


def _scroll_fireworks(display, text, text_color, burst_colors=None, speed=0.050):
    """
    Scroll text over a live fireworks background.
    Sparks burst from random points and drift outward.
    Positions stored *10 for smooth sub-pixel motion using integers only.
    """
    if burst_colors is None:
        burst_colors = _SPARK_COLORS

    # Build palette: 0=black, 1..N=spark colors
    n = len(burst_colors)
    pal = displayio.Palette(n + 1)
    pal[0] = BLACK
    for i, c in enumerate(burst_colors):
        pal[i + 1] = c

    bmp = displayio.Bitmap(64, 32, n + 1)
    group = displayio.Group()
    group.append(displayio.TileGrid(bmp, pixel_shader=pal))
    lbl = label.Label(terminalio.FONT, text=text, color=text_color, x=64, y=16)
    group.append(lbl)
    display.root_group = group

    # sparks: [x*10, y*10, dx, dy, color_idx, life]
    sparks = []
    end = -(len(text) * 6 + 10)
    frame = 0

    for lx in range(64, end, -1):
        microcontroller.watchdog.feed()
        lbl.x = lx

        # New burst every ~22 frames, cap at 20 sparks total
        if frame % 22 == 0 and len(sparks) < 20:
            cx = random.randint(6, 58) * 10
            cy = random.randint(3, 28) * 10
            ci = random.randint(1, n)
            for _ in range(8):
                dx = random.randint(-28, 28)
                dy = random.randint(-18, 18)
                sparks.append([cx, cy, dx, dy, ci, 8])

        # Clear old positions
        for s in sparks:
            ox, oy = s[0] // 10, s[1] // 10
            if 0 <= ox < 64 and 0 <= oy < 32:
                bmp[ox, oy] = 0

        # Move and redraw
        new_sparks = []
        for s in sparks:
            s[0] += s[2]
            s[1] += s[3]
            s[5] -= 1
            if s[5] > 0:
                nx, ny = s[0] // 10, s[1] // 10
                if 0 <= nx < 64 and 0 <= ny < 32:
                    bmp[nx, ny] = s[4]
                new_sparks.append(s)
        sparks = new_sparks

        time.sleep(speed)
        frame += 1


def _scroll_rainbow(display, text, colors, bg_color=BLACK, speed=0.044):
    """Scroll text cycling through a list of colors."""
    group = displayio.Group()
    bg_bmp = displayio.Bitmap(64, 32, 1)
    bg_pal = displayio.Palette(1)
    bg_pal[0] = bg_color
    group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
    lbl = label.Label(terminalio.FONT, text=text, color=colors[0], x=64, y=16)
    group.append(lbl)
    display.root_group = group
    end = -(len(text) * 6 + 10)
    ci = 0
    for x in range(64, end, -1):
        microcontroller.watchdog.feed()
        lbl.x = x
        if x % 6 == 0:
            ci = (ci + 1) % len(colors)
            lbl.color = colors[ci]
        time.sleep(speed)


def _scroll_bounce(display, text, text_color, bg_color=BLACK, speed=0.044):
    """Scroll text with a vertical bounce."""
    group = displayio.Group()
    bg_bmp = displayio.Bitmap(64, 32, 1)
    bg_pal = displayio.Palette(1)
    bg_pal[0] = bg_color
    group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
    lbl = label.Label(terminalio.FONT, text=text, color=text_color, x=64, y=16)
    group.append(lbl)
    display.root_group = group
    end = -(len(text) * 6 + 10)
    for i, x in enumerate(range(64, end, -1)):
        microcontroller.watchdog.feed()
        lbl.x = x
        lbl.y = 16 + _BOUNCE_Y[i % len(_BOUNCE_Y)]
        time.sleep(speed)


def _scroll_pulse(display, text, text_color, bg_color=BLACK, speed=0.044):
    """Scroll text with brightness pulsing in and out."""
    group = displayio.Group()
    bg_bmp = displayio.Bitmap(64, 32, 1)
    bg_pal = displayio.Palette(1)
    bg_pal[0] = bg_color
    group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
    lbl = label.Label(terminalio.FONT, text=text, color=text_color, x=64, y=16)
    group.append(lbl)
    display.root_group = group
    end = -(len(text) * 6 + 10)
    for i, x in enumerate(range(64, end, -1)):
        microcontroller.watchdog.feed()
        lbl.x = x
        t = (_BOUNCE_Y[i % len(_BOUNCE_Y)] + 4) / 8  # 0.0 → 1.0
        lbl.color = _lerp_color(BLACK, text_color, 0.35 + t * 0.65)
        time.sleep(speed)


def _spin(display, colors, reps=3, step_time=0.05):
    """Cycle through colors with smooth fades. Used for rotate-board."""
    bmp = displayio.Bitmap(64, 32, 1)
    pal = displayio.Palette(1)
    group = displayio.Group()
    group.append(displayio.TileGrid(bmp, pixel_shader=pal))
    display.root_group = group
    steps = 12
    prev = BLACK
    for _ in range(reps):
        for color in colors:
            microcontroller.watchdog.feed()
            for i in range(steps + 1):
                pal[0] = _lerp_color(prev, color, i / steps)
                time.sleep(step_time / steps)
            prev = color


# --- Animations ---

def anim_numberwang(display):
    """THAT'S NUMBERWANG! — gold flash + fireworks scroll"""
    gc.collect()
    _flash(display, [GOLD, WHITE, GOLD], hold=0.10)
    _scroll_fireworks(display, "THAT'S NUMBERWANG!", GOLD,
                      burst_colors=[GOLD, ORANGE, WHITE, GOLD, ORANGE, WHITE])
    _flash(display, [GOLD, WHITE, GOLD], hold=0.10)
    gc.collect()


def anim_symmewang(display):
    """SYMME-WANG! — mirror scores, blue/red flash + bouncing scroll"""
    gc.collect()
    _flash(display, [BLUE, RED, BLUE, RED], hold=0.09)
    _scroll_bounce(display, "SYMME-WANG!", WHITE, BLUE)
    gc.collect()


def anim_centerwang(display):
    """CENTERWANG! — scores add to 100, pulse scroll"""
    gc.collect()
    _flash(display, [GREEN, WHITE, GREEN], hold=0.10)
    _scroll_pulse(display, "CENTERWANG!", GREEN)
    _flash(display, [GREEN], hold=0.15)
    gc.collect()


def anim_digitwang(display):
    """DIGIT-WANG! — same last digit, rainbow scroll"""
    gc.collect()
    _flash(display, [PURPLE, PINK, PURPLE], hold=0.10)
    _scroll_rainbow(display, "DIGIT-WANG!", [PURPLE, PINK, WHITE, PINK, PURPLE])
    gc.collect()


def anim_rotate_board(display):
    """LET'S ROTATE THE BOARD! — fireworks scroll + color spin"""
    gc.collect()
    _scroll_fireworks(display, "LET'S ROTATE THE BOARD!", GOLD,
                      burst_colors=[RED, ORANGE, GOLD, GREEN, BLUE, PURPLE, WHITE, PINK],
                      speed=0.040)
    _spin(display, [RED, ORANGE, GOLD, GREEN, BLUE, PURPLE, WHITE, PINK], reps=3, step_time=0.05)
    _flash(display, [WHITE, GOLD, WHITE], hold=0.10)
    gc.collect()


def anim_chaos(display):
    """Pure chaos — numberwang then color spin"""
    gc.collect()
    anim_numberwang(display)
    _spin(display, CHAOS_COLORS, reps=2, step_time=0.06)
    gc.collect()


def anim_multiwang(display, count):
    """DOUBLEWANG / TRIPLEWANG / etc. — announce simultaneous multi-trigger."""
    gc.collect()
    name = _WANG_NAMES[count] if count < len(_WANG_NAMES) else "MEGAWANG"
    _flash(display, CHAOS_COLORS, hold=0.07)
    _scroll_fireworks(display, name + "!", WHITE,
                      burst_colors=CHAOS_COLORS, speed=0.040)
    _flash(display, CHAOS_COLORS, hold=0.07)
    gc.collect()


# --- Trigger checker ---

COOLDOWN = 45  # seconds between animations
_last_fired = 0


def check(display, game, old_as, old_hs):
    """
    Check all Numberwang conditions for a score update.
    Multiple simultaneous triggers → DOUBLEWANG / TRIPLEWANG / etc., then all animations play.
    Enforces a cooldown so animations don't stack up.
    """
    global _last_fired

    now = time.monotonic()
    if now - _last_fired < COOLDOWN:
        return False

    try:
        new_a = int(game["as"])
        new_h = int(game["hs"])
        old_a = int(old_as) if str(old_as) not in ("--", "") else -1
        old_h = int(old_hs) if str(old_hs) not in ("--", "") else -1
    except (ValueError, TypeError):
        return False

    # Collect all triggered animations — don't short-circuit
    triggers = []

    # Lead change → rotate the board (only when previous scores are known)
    if old_a >= 0 and old_h >= 0:
        old_lead = (old_a > old_h) - (old_a < old_h)
        new_lead = (new_a > new_h) - (new_a < new_h)
        if old_lead != 0 and new_lead != 0 and old_lead != new_lead:
            triggers.append(anim_rotate_board)

    if new_a == new_h and new_a > 0:
        triggers.append(anim_symmewang)

    if new_a + new_h == 100:
        triggers.append(anim_centerwang)

    if new_a != new_h and new_a % 10 == new_h % 10 and new_a > 9 and new_h > 9:
        triggers.append(anim_digitwang)

    if random.random() < 0.02:
        triggers.append(anim_chaos)

    if not triggers:
        return False

    if len(triggers) >= 2:
        anim_multiwang(display, len(triggers))

    for anim in triggers:
        anim(display)

    # Release animation objects before gc so scorebug can allocate
    _empty = displayio.Group()
    display.root_group = _empty
    _last_fired = time.monotonic()
    gc.collect()
    return True
