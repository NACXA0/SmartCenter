# SmartCenter · 店内 HAOS 配置与集成

生产形态见主仓 [docs/架构-HAOS四App.md](../docs/架构-HAOS四App.md)：

- 本仓库提供 **HA 配置目录**与（过渡期）`custom_components/lobn_office`
- 目标：**HA 零智能**——保命自动化、实体、侧边栏 iframe（Frigate / sidecar）；分析与开门决策在 **analytics-sidecar**
- 门禁执行：**ESPHome** ← MQTT `home/*/command`（旧 HTTP `door.command.v1` / 自研固件弃用中）
- 监控：**Frigate**，不是 SmartCCTV（[归档决策](../docs/决策-归档自研SmartCCTV.md)）

基于 **Home Assistant**（见 `VERSION`），**不修改 HA 主干**。内网建议主机名走 HAOS；界面 `zh-Hans`。

## 快速开始（开发）

```bash
./START.sh repair --yes
./START.sh start          # uv run hass -c config
```

浏览器打开 `:8123`。生产请用 **HAOS Supervisor** 安装 Mosquitto、Frigate Full Access、sidecar，而不是仅靠本机 uvicorn 冒充全栈。

## 结构

- `config/` — HA 配置（含 `custom_components/lobn_office`、`packages/rfid_asset_guard.yaml`）
- `esphome/` — **教室总控**（门 / DHT11 / RFID / 板载警号）；生产唯一固件形态
- `firmware/esp32s3_door/` — 旧 HTTP 门固件；**勿新部署**
- `docs/部署说明.md` — 部署与验收要点
- 后续：`addons/analytics_sidecar/`（或独立仓）按架构文档脚手架

## 职责边界

| 在本仓 / HA | 不在本仓 |
|-------------|----------|
| 保命自动化、MQTT/ZHA、iframe、过渡期云端拉取 | Frigate 发行版、摄像头拉流、经营分析算法 |
| **RFID 资产防盗**（ESPHome 比对 + HA 白名单/通知） | LOBN_FireClassroom / 小程序 / 云端台账 |

RFID：[docs/资产防盗-RFID.md](../docs/资产防盗-RFID.md) · 契约：[docs/接口契约.md](../docs/接口契约.md)。
