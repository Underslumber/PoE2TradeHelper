from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


MAC_RE = re.compile(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")


def load_settings() -> dict[str, str]:
    settings = dict(os.environ)
    env_file = Path(settings.get("APP_ENV_FILE", ""))
    if env_file.is_file():
        settings = {**dotenv_values(env_file), **settings}
    return {key: str(value or "") for key, value in settings.items()}


def find_mac(target_ip: str, configured: str) -> str:
    match = MAC_RE.fullmatch(configured.strip())
    if match:
        return match.group(0)
    for command in (["ip", "neigh", "show", target_ip], ["arp", "-n", target_ip]):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        match = MAC_RE.search(result.stdout or "")
        if match and match.group(0) != "00:00:00:00:00:00":
            return match.group(0)
    arp_path = Path("/proc/net/arp")
    if arp_path.is_file():
        for line in arp_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.split(maxsplit=1)[0] == target_ip:
                match = MAC_RE.search(line)
                if match and match.group(0) != "00:00:00:00:00:00":
                    return match.group(0)
    return ""


def main() -> int:
    settings = load_settings()
    target_ip = settings.get("WOL_TARGET_IP") or "192.168.1.2"
    ipaddress.IPv4Address(target_ip)
    marker = Path(settings.get("WAKE_ON_DEPLOY_MARKER") or ".wake-target-on-deploy.done")
    if marker.exists():
        print(f"Emergency Wake-on-LAN already completed for {target_ip}")
        return 0
    mac = find_mac(target_ip, settings.get("WOL_TARGET_MAC", ""))
    if not mac:
        print(f"MAC for {target_ip} is absent from the server neighbor table", file=sys.stderr)
        return 2
    broadcast = settings.get("WOL_BROADCAST_ADDRESS") or str(
        ipaddress.IPv4Network(f"{target_ip}/24", strict=False).broadcast_address
    )
    packet = bytes.fromhex("FF" * 6 + mac.replace(":", "").replace("-", "") * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(5):
            sock.sendto(packet, (broadcast, 9))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{target_ip} {mac}\n", encoding="utf-8")
    print(f"Emergency Wake-on-LAN sent to {target_ip} via {broadcast}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
