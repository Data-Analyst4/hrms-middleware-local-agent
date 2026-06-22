from __future__ import annotations

import socket


def guess_site_lan_ip(fallback: str = "127.0.0.1") -> str:
    """Best-effort LAN IP for the interface used to reach the internet."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return fallback
