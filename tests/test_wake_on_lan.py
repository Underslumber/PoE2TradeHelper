import socket

import pytest

from app import wake_on_lan


class FakeSocket:
    def __init__(self, *args):
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def setsockopt(self, *args):
        return None

    def sendto(self, packet, address):
        self.sent.append((packet, address))


def test_send_magic_packet(monkeypatch):
    fake_socket = FakeSocket()
    monkeypatch.setenv("WOL_TARGET_MAC", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("WOL_TARGET_IP", "192.168.1.2")
    monkeypatch.setenv("WOL_BROADCAST_ADDRESS", "192.168.1.255")
    monkeypatch.setenv("WOL_REPEAT", "3")
    monkeypatch.setattr(socket, "socket", lambda *args: fake_socket)
    monkeypatch.setattr(wake_on_lan, "_last_sent_at", 0.0)

    result = wake_on_lan.send_magic_packet()

    assert result["sent"] is True
    assert result["packets_sent"] == 3
    assert len(fake_socket.sent) == 3
    assert fake_socket.sent[0][1] == ("192.168.1.255", 9)
    assert fake_socket.sent[0][0] == bytes.fromhex("FF" * 6 + "AABBCCDDEEFF" * 16)


def test_missing_mac_is_not_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("WOL_TARGET_MAC", raising=False)
    monkeypatch.setenv("WOL_AUTO_DISCOVER", "false")
    monkeypatch.setenv("WOL_MAC_CACHE_PATH", str(tmp_path / "mac.json"))

    assert wake_on_lan.status()["configured"] is False
    with pytest.raises(wake_on_lan.WakeOnLanError, match="MAC-адрес"):
        wake_on_lan.send_magic_packet()


def test_discovered_mac_is_cached(monkeypatch, tmp_path):
    cache_path = tmp_path / "mac.json"
    monkeypatch.delenv("WOL_TARGET_MAC", raising=False)
    monkeypatch.setenv("WOL_AUTO_DISCOVER", "true")
    monkeypatch.setenv("WOL_MAC_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(wake_on_lan, "_discover_neighbor_mac", lambda target_ip: "AA:BB:CC:DD:EE:FF")

    discovered = wake_on_lan.status()
    monkeypatch.setattr(wake_on_lan, "_discover_neighbor_mac", lambda target_ip: "")
    cached = wake_on_lan.status()

    assert discovered["configured"] is True
    assert discovered["mac_source"] == "neighbor"
    assert cached["configured"] is True
    assert cached["mac_source"] == "cache"
