from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic


class WakeOnLanError(RuntimeError):
    pass


_MAC_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
_MAC_SEARCH_PATTERN = re.compile(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
_SEND_LOCK = threading.Lock()
_last_sent_at = 0.0


def _mac_cache_path() -> Path:
    configured = os.environ.get("WOL_MAC_CACHE_PATH", "").strip()
    return Path(configured) if configured else Path(os.environ.get("DATA_DIR", "data")) / "wake_on_lan_mac.json"


def _discover_neighbor_mac(target_ip: str) -> str:
    commands = (["ip", "neigh", "show", target_ip], ["arp", "-n", target_ip])
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        match = _MAC_SEARCH_PATTERN.search(result.stdout or "")
        if match and match.group(0) != "00:00:00:00:00:00":
            return match.group(0).upper().replace("-", ":")
    return ""


def _cached_mac(target_ip: str) -> str:
    try:
        payload = json.loads(_mac_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    mac = str(payload.get("mac") or "").strip()
    return mac if payload.get("target_ip") == target_ip and _MAC_PATTERN.fullmatch(mac) else ""


def _remember_mac(target_ip: str, mac: str) -> None:
    try:
        path = _mac_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"target_ip": target_ip, "mac": mac}), encoding="utf-8")
    except OSError:
        pass


def _resolve_mac(target_ip: str) -> tuple[str, str]:
    configured = os.environ.get("WOL_TARGET_MAC", "").strip()
    if configured:
        return configured, "environment"
    auto_discover = os.environ.get("WOL_AUTO_DISCOVER", "true").lower() not in {"0", "false", "no", "off"}
    if auto_discover:
        discovered = _discover_neighbor_mac(target_ip)
        if discovered:
            _remember_mac(target_ip, discovered)
            return discovered, "neighbor"
    cached = _cached_mac(target_ip)
    return (cached, "cache") if cached else ("", "")


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
    target_ip = os.environ.get("WOL_TARGET_IP", "192.168.1.2").strip()
    broadcast = os.environ.get("WOL_BROADCAST_ADDRESS", "192.168.1.255").strip()

    try:
        ipaddress.IPv4Address(target_ip)
    except ipaddress.AddressValueError as exc:
        raise WakeOnLanError("WOL_TARGET_IP должен быть корректным IPv4-адресом.") from exc
    try:
        ipaddress.IPv4Address(broadcast)
    except ipaddress.AddressValueError as exc:
        raise WakeOnLanError("WOL_BROADCAST_ADDRESS должен быть корректным IPv4-адресом.") from exc
    mac, mac_source = _resolve_mac(target_ip)
    if mac and not _MAC_PATTERN.fullmatch(mac):
        raise WakeOnLanError("WOL_TARGET_MAC должен иметь вид AA:BB:CC:DD:EE:FF.")

    return {
        "mac": mac,
        "mac_source": mac_source,
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
        "mac_source": settings["mac_source"],
        "configuration_error": None if settings["mac"] else "MAC-адрес ещё не найден. Включите компьютер один раз, чтобы сервер запомнил его.",
    }


def send_magic_packet() -> dict:
    global _last_sent_at

    settings = _settings()
    if not settings["mac"]:
        raise WakeOnLanError("MAC-адрес ещё не найден. Включите компьютер один раз, чтобы сервер запомнил его.")

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


def send_once_on_startup() -> dict:
    target_ip = os.environ.get("WOL_TARGET_IP", "192.168.1.2").strip()
    marker = Path(os.environ.get("DATA_DIR", "data")) / f"wake_on_startup_{target_ip}.done"
    if marker.exists():
        return {"sent": False, "skipped": True, "target_ip": target_ip}
    result = send_magic_packet()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(result.get("sent_at") or "sent"), encoding="utf-8")
    except OSError:
        pass
    return result
