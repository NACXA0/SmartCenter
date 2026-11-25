# ESP32-S3 门禁固件

链路：SmartCenter → 以太网 W5500 → ESP32-S3 → 继电器短接两线 → 开门。

- 只执行总控 `door.command.v1`（Bearer token）。
- DHT11 / PIR / 按钮可缺省；不上报也不影响门服务。
- PIR / 按钮只上报 `esp.sense.v1`，本地不开门。

## 烧录

```bash
cp include/config.example.h include/config.h   # 改引脚与 token
pio run -t upload
```

## HTTP

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/health` | 门状态、器件在位 |
| POST | `/v1/door/command` | 需 `Authorization: Bearer <token>` |

`host_sim/door_logic.py` 镜像脉冲夹紧与忙时拒绝，供仓库单测。
