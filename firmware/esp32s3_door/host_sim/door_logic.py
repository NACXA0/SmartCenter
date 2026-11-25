"""固件门脉冲规则的主机侧镜像，供单测；不驱动硬件。"""

from __future__ import annotations


def clamp_seconds(seconds: float) -> float:
    if seconds < 0.2:
        return 0.2
    if seconds > 15.0:
        return 15.0
    return float(seconds)


class DoorPulseSim:
    def __init__(self) -> None:
        self.pulsing = False
        self.command_id = ""
        self.relay_on = False

    def open(self, command_id: str, seconds: float) -> tuple[int, dict]:
        if not command_id:
            return 400, {"ok": False, "error": "bad_command"}
        if self.pulsing:
            return 409, {"ok": False, "error": "busy"}
        sec = clamp_seconds(seconds)
        self.pulsing = True
        self.command_id = command_id
        self.relay_on = True
        return 200, {"result": "pulsed", "command_id": command_id, "seconds": sec}

    def close(self, command_id: str = "") -> tuple[int, dict]:
        self.pulsing = False
        self.command_id = ""
        self.relay_on = False
        return 200, {"result": "released", "command_id": command_id}

    def tick_release(self) -> None:
        """模拟脉冲到期。"""
        self.pulsing = False
        self.command_id = ""
        self.relay_on = False


def is_dht_garbage(temp_c: float, humidity_pct: float) -> bool:
    if abs(temp_c - 85.0) < 0.5 and humidity_pct < 0.5:
        return True
    if temp_c < -10 or temp_c > 60 or humidity_pct < 0 or humidity_pct > 100:
        return True
    return False
