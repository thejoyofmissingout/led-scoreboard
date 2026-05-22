"""
WiFi + HTTP for Matrix Portal M4.
Reads credentials from settings.toml via os.getenv().
"""

import os
import board
from adafruit_matrixportal.network import Network

_network = None


def init_network():
    """Initialize and connect to WiFi. Returns network object or None on failure."""
    global _network
    try:
        _network = Network(status_neopixel=board.NEOPIXEL, debug=False)
        print("[net] Connecting to WiFi:", os.getenv("CIRCUITPY_WIFI_SSID"))
        _network.connect()
        print("[net] Connected!")
        return _network
    except Exception as e:
        print("[net] Init failed:", e)
        return None


def fetch_scores(network, url):
    """GET url, parse JSON. Returns dict or None on error."""
    response = None
    try:
        response = network.fetch(url, timeout=8)
        data = response.json()
        return data
    except MemoryError:
        print("[net] MemoryError — response too large")
        import gc
        gc.collect()
        return None
    except Exception as e:
        print("[net] Fetch error:", e)
        return None
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
