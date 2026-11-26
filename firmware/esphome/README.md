# 教室总控 · ESPHome（生产）

每间教室一颗 ESP32（推荐 S3），经 MQTT 接入 HAOS Mosquitto。  
路径：`SmartCenter/firmware/esphome/`（硬件固件统一在 [../](../)）。

**不要**部署 [../esp32s3_door/](../esp32s3_door/) 的 HTTP 门协议。

## 入口

```bash
./START.sh                 # 菜单；默认推荐 Device Builder
./START.sh builder         # http://127.0.0.1:6052
./START.sh prepare         # 创建 .venv 并安装 esphome-device-builder[esphome]

# 无头
./START.sh compile
./START.sh upload
```

从 SmartCenter 根：`./START.sh flash` → 转调本目录 `START.sh`。

Device Builder 打开的配置目录即本目录；编辑 `classroom_node.yaml` 的 `substitutions.room_id`（大门 `front_gate`、教室 `classroom_1`）。

`secrets.yaml` 里 `api_encryption_key` 必须是 **32 字节 base64**（`openssl rand -base64 32`），不能写占位英文。实体名不要含 `/`（ESPHome 会当成 URL 分隔符）。

## 目录

```text
esphome/
├── START.sh
├── classroom_node.yaml
├── secrets.yaml.example
├── packages/
│   ├── door.yaml            # home/<room_id>/door/command + ttl_sec
│   ├── climate_dht11.yaml
│   ├── siren.yaml
│   ├── rfid_core.yaml
│   ├── rfid_rs485.yaml
│   └── rfid_wiegand.yaml.example
└── external_components/
```

HA：`config/packages/door_mqtt.yaml`、`rfid_asset_guard.yaml`。  
`lobn_office` 适配器默认 `mqtt`，`gate|inner` → node。

边界：[docs/资产防盗-RFID.md](../../../docs/资产防盗-RFID.md)。
