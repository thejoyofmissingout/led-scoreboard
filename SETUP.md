# LED Scoreboard Setup Guide

## Hardware
- Adafruit Matrix Portal M4
- 64x32 RGB LED matrix (5mm pitch)

---

## Step 1: Verify CircuitPython on the Matrix Portal M4

Plug the board into your Mac with a **USB data cable** (not a charge-only cable).

- If **CIRCUITPY** appears as a drive in Finder → you're ready, skip to Step 3
- If **MATRIXM4BOOT** or **FEATHERBOOT** appears → follow Step 2
- If nothing appears → try a different cable (most cables are charge-only)

---

## Step 2: Install CircuitPython (if needed)

1. Go to: https://circuitpython.org/board/adafruit_matrix_portal_m4/
2. Download the latest `.uf2` file
3. Double-click the reset button on the Matrix Portal to enter the bootloader (MATRIXM4BOOT drive appears)
4. Drag the `.uf2` file onto the MATRIXM4BOOT drive
5. The board reboots and CIRCUITPY appears

---

## Step 3: Install CircuitPython Libraries

With CIRCUITPY mounted, open Terminal:

```bash
pip3 install circup
circup install adafruit_matrixportal adafruit_display_text adafruit_bitmap_font neopixel adafruit_esp32spi adafruit_requests
```

---

## Step 4: Copy Board Files to CIRCUITPY

Copy these files from `scoreboard-server/circuitpy/` to your CIRCUITPY drive:

```
scoreboard-server/circuitpy/code.py        → /Volumes/CIRCUITPY/code.py
scoreboard-server/circuitpy/display_mgr.py → /Volumes/CIRCUITPY/display_mgr.py
scoreboard-server/circuitpy/network_mgr.py → /Volumes/CIRCUITPY/network_mgr.py
scoreboard-server/circuitpy/secrets.py     → /Volumes/CIRCUITPY/secrets.py
```

**Edit `/Volumes/CIRCUITPY/secrets.py`** with your actual WiFi credentials and Mac's IP:

```python
secrets = {
    "ssid":       "YourActualWiFiName",
    "password":   "YourActualPassword",
    "server_url": "http://YOUR_MAC_IP:5000/scores",
}
```

Find your Mac's local IP:
```bash
ipconfig getifaddr en0
```

---

## Step 5: Mac Server One-Time Setup

```bash
cd ~/Documents/Dev\ -\ claude/scoreboard-server
python3 -m venv venv
source venv/bin/activate
pip install flask requests
```

---

## Daily Use

**Start the server (Mac):**
```bash
cd ~/Documents/Dev\ -\ claude/scoreboard-server
source venv/bin/activate
python server.py
```

Server prints your local IP when it starts. Open that URL on your iPhone.

**Pick games (iPhone):**
- Open `http://YOUR_MAC_IP:5000` in Safari
- Check the games you want on the board
- Tap **Update Board**

**Power on the Matrix Portal** — it connects to WiFi and starts showing selected game scores, rotating every 10 seconds.

---

## VS Code Development Workflow

1. Open the CIRCUITPY drive as a folder in VS Code
2. Install the **CircuitPython** extension (by joedevivo)
3. Edit files directly — the board auto-restarts when you save
4. View serial output (print statements): open a terminal and run:
   ```bash
   ls /dev/tty.usbmodem*   # find your board's serial port
   tio /dev/tty.usbmodemXXXX
   ```
   Press Ctrl+C on the board to enter REPL, Ctrl+D to reload

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Board shows "NO WIFI" | Check `secrets.py` SSID/password, ensure same WiFi network |
| Board shows "NO SERVER" | Make sure `python server.py` is running on Mac |
| Board shows "NO GAMES" | Open the iPhone picker and select some games |
| CIRCUITPY doesn't appear | Try a different USB cable — most are charge-only |
| Games not updating | Tap "Refresh scores" at bottom of the iPhone picker page |
| Memory error on board | Too many games selected — try selecting ≤10 games |

---

## Adjusting Timezone for Pre-Game Times

Edit `espn_client.py` and change:
```python
UTC_OFFSET_HOURS = -5  # Central Time (standard)
# Use -6 for CST, -5 for CDT, -8 for PST, -7 for PDT, -5 for EST, -4 for EDT
```
