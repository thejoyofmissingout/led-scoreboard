"""
Animation test — cycles through all Numberwang animations with a 4-second pause.
Swap this in as code.py to preview animations on the board.
"""
import time
import board
from adafruit_matrixportal.matrix import Matrix
import numberwang
import display_mgr

matrix = Matrix(width=64, height=32, bit_depth=3)
display = matrix.display

ANIMS = [
    ("NUMBERWANG", numberwang.anim_numberwang),
    ("SYMMEWANG",  numberwang.anim_symmewang),
    ("CENTERWANG", numberwang.anim_centerwang),
    ("DIGITWANG",  numberwang.anim_digitwang),
    ("ROTATE BOARD", numberwang.anim_rotate_board),
    ("CHAOS",      numberwang.anim_chaos),
]

while True:
    for name, anim in ANIMS:
        display_mgr.draw_message(display, name, "starting...")
        time.sleep(2)
        print("Playing:", name)
        anim(display)
        display_mgr.draw_message(display, name, "done")
        time.sleep(3)
