# ESPHome 教室总控

生产节点：每间教室一颗 ESP32（推荐 S3），跑 ESPHome，经 MQTT 接入 HAOS Mosquitto。  
**不要**再部署 [firmware/esp32s3_door](../firmware/esp32s3_door/) 的 HTTP 门协议。

## 职责

- 采集：RFID 通道读头（默认 RS485）、DHT11、门磁 / sense
- 执行：门继电器脉冲、**板载 GPIO 警号**
- 本地：按 HA 下发的 retained 白名单比对；断网仍报警
- 不上：预约平台、资产名称台账、自研整套固件业务逻辑

边界全文：[docs/资产防盗-RFID.md](../../docs/资产防盗-RFID.md)。

## 目录

```text
esphome/
├── classroom_node.yaml          # 教室总控主配置（改 substitutions）
├── secrets.yaml.example
├── packages/
│   ├── door.yaml
│   ├── climate_dht11.yaml
│   ├── siren.yaml
│   ├── rfid_core.yaml           # allowlist + 比对 + event
│   ├── rfid_rs485.yaml          # 默认读头口
│   └── rfid_wiegand.yaml.example
└── external_components/
    └── README.md                # 厂商帧 / 韦根外挂组件接入点
```

## 烧录（店内）

```bash
cp secrets.yaml.example secrets.yaml   # 填 wifi / mqtt
# 按教室改 classroom_node.yaml 的 substitutions（room_id、引脚）
esphome run classroom_node.yaml
```

HA 侧白名单与通知：[config/packages/rfid_asset_guard.yaml](../config/packages/rfid_asset_guard.yaml)。

## 接口选型

| 教室读头 | 启用包 | 说明 |
|----------|--------|------|
| **RS485（默认）** | `rfid_rs485.yaml` | UART + DE/RE；厂商帧在 `external_components` |
| 韦根 | 换用 `rfid_wiegand.yaml.example`，关掉 RS485 包 | 独立时序组件，短线 |
| RS232 | 复用 RS485 包，去掉 DE/RE 脚 | 仍走 `transport: rs232` 上报 |
