# ESP32-S3 门禁固件（历史 · HTTP）

> **迁移目标**：生产改用 **ESPHome**，经 MQTT `home/<door>/command` / `state` 执行与上报。  
> 见主仓 [docs/架构-HAOS四App.md](../../../docs/架构-HAOS四App.md)。本目录保留作旧联调与单测参考，**新店不要再部署 HTTP 门协议**。

旧链路：SmartCenter HTTP → 以太网 W5500 → ESP32-S3 → 继电器。

- 只执行总控 `door.command.v1`（Bearer token）。
- DHT11 / PIR / 按钮可缺省；PIR / 按钮只上报 `esp.sense.v1`，本地不开门。

## 烧录（仅遗留）

```bash
cp include/config.example.h include/config.h   # 改引脚与 token
pio run -t upload
```

## HTTP（废弃中）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/health` | 门状态、器件在位 |
| POST | `/v1/door/command` | 需 `Authorization: Bearer <token>` |

`host_sim/door_logic.py` 镜像脉冲夹紧与忙时拒绝，供仓库单测。
