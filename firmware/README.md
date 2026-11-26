# SmartCenter · 硬件固件

店内 ESP / 外设固件统一落在本目录，与 HA 配置（`../config`）分开。

```text
firmware/
├── README.md                 # 本说明
├── esphome/                  # 【生产】教室总控 ESPHome YAML + START.sh
│   ├── START.sh              # Device Builder（主）/ CLI 编译烧录
│   ├── classroom_node.yaml
│   └── packages/
└── esp32s3_door/             # 【遗留】旧 HTTP 门固件（PlatformIO），勿新店部署
```

| 路径 | 角色 | 入口 |
|------|------|------|
| [esphome/](esphome/) | 门 / DHT11 / RFID / 警号，MQTT `home/<node>/…` | `./esphome/START.sh` 或仓库根 `./START.sh flash` |
| [esp32s3_door/](esp32s3_door/) | 历史 HTTP `door.command.v1` | 仅联调/单测；**不进** START 烧录菜单 |

原则：新功能只加在 `esphome/`；遗留目录只减不增。
