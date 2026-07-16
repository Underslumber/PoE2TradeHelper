from __future__ import annotations

import ipaddress
import os
import re
import socket
import threading
from datetime import datetime, timezone
from time import monotonic


class WakeOnLanError(RuntimeError):
    pass


_MAC_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
_SEND_LOCK = threading.Lock()
_last_sent_at = 0.0


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise WakeOnLanError(f"{name} должно быть целым числом.") from exc
    if not minimum <= value <= maximum:
        raise WakeOnLanError(f"{name} должно быть от {minimum} до {maximum}.")
    return value


def _settings() -> dict:
    mac = os.environ.get("WOL_TARGET_MAC", "").strip()
    target_ip = os.environ.get("WOL_TARGET_IP", "192.168.1.2").strip()
    broadcast = os.environ.get("WOL_BROADCAST_ADDRESS", "192.168.1.255").strip()

    if mac and not _MAC_PATTERN.fullmatch(mac):
        raise WakeOnLanError("WOL_TARGET_MAC должен иметь вид AA:BB:CC:DD:EE:FF.")
    try:
        ipaddress.IPv4Address(target_ip)
    except ipaddress.AddressValueError as exc:
        raise WakeOnLanError("WOL_TARGET_IP должен быть корректным IPv4-адресом.") from exc
    try:
        ipaddress.IPv4Address(broadcast)
    except ipaddress.AddressValueError as exc:
        raise WakeOnLanError("WOL_BROADCAST_ADDRESS должен быть корректным IPv4-адресом.") from exc

    return {
        "mac": mac,
        "target_ip": target_ip,
        "broadcast_address": broadcast,
        "port": _read_int("WOL_PORT", 9, 1, 65535),
        "repeat": _read_int("WOL_REPEAT", 3, 1, 5),
        "cooldown_seconds": _read_int("WOL_COOLDOWN_SECONDS", 10, 1, 300),
    }


def status() -> dict:
    try:
        settings = _settings()
    except WakeOnLanError as exc:
        return {
            "configured": False,
            "target_ip": os.environ.get("WOL_TARGET_IP", "192.168.1.2").strip(),
            "configuration_error": str(exc),
        }
    return {
        "configured": bool(settings["mac"]),
        "target_ip": settings["target_ip"],
        "broadcast_address": settings["broadcast_address"],
        "port": settings["port"],
        "configuration_error": None if settings["mac"] else "WOL_TARGET_MAC не задан.",
    }


def send_magic_packet() -> dict:
    global _last_sent_at

    settings = _settings()
    if not settings["mac"]:
        raise WakeOnLanError("WOL_TARGET_MAC не задан.")

    normalized_mac = settings["mac"].replace(":", "").replace("-", "")
    packet = bytes.fromhex("FF" * 6 + normalized_mac * 16)

    with _SEND_LOCK:
        elapsed = monotonic() - _last_sent_at
        if _last_sent_at and elapsed < settings["cooldown_seconds"]:
            remaining = max(1, int(settings["cooldown_seconds"] - elapsed + 0.999))
            raise WakeOnLanError(f"Повторная отправка будет доступна через {remaining} сек.")

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for _ in range(settings["repeat"]):
                sock.sendto(packet, (settings["broadcast_address"], settings["port"]))
        _last_sent_at = monotonic()

    return {
        **status(),
        "sent": True,
        "packets_sent": settings["repeat"],
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
