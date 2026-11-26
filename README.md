# SmartCenter · 店内 HAOS 配置与集成

生产形态见主仓 [docs/架构-HAOS四App.md](../docs/架构-HAOS四App.md)：

- 本仓库提供 **HA 配置目录**与（过渡期）`custom_components/lobn_office`
- 目标：**HA 零智能**——保命自动化、实体、Ingress；**刷脸采集 / 人脸库 / 比对 / 统计**在 **`addon/`（SmartCenter Add-on）**
- 门禁执行：**ESPHome** ← MQTT `home/*/command`；Add-on 只发 `business/access/grant`
- 监控：**Frigate**（关 Face Recognition），不是 SmartCCTV（[归档决策](../docs/决策-归档自研SmartCCTV.md)）
- 人脸专文：[docs/人脸-SmartCenter-Add-on.md](../docs/人脸-SmartCenter-Add-on.md)
- 本机开发：[docs/开发工作流.md](../docs/开发工作流.md)

基于 **Home Assistant**（见 `VERSION`），**不修改 HA 主干**。内网建议主机名走 HAOS；界面 `zh-Hans`。

## 快速开始（开发 · 热更新）

```bash
./START.sh repair --yes          # 首次：本机 HA (uv)
./START.sh addon-repair          # 首次：Add-on venv
./START.sh all                   # 一键：Vite HMR + API reload + 本机 HA（关终端=全停）
```

| 入口 | 地址 |
|------|------|
| 工作台（开发主入口） | http://127.0.0.1:5173/ |
| Add-on API / 构建页 | http://127.0.0.1:8080/ |
| 本机 HA | http://127.0.0.1:8123/ |

其它：`addon` / `addon-api` / `addon-ui` / `addon-ui-build` / `addon-test` / `dev` / `stop-all`。菜单：**启动 / 开发 / 运维 / 环境 / 固件**。

店内 HAOS 只做生产与终验 → [docs/对接已有HAOS.md](../docs/对接已有HAOS.md)。

## 结构

- `config/` — HA 配置（含 `custom_components/lobn_office`、`packages/`）
- `addon/` — **SmartCenter HA Add-on**
  - `app/` FastAPI：会话、底库、门口比对、维护任务、审计
  - `web/` Vite + React 工作台源码（概览 / 采集 / 人脸库 / 审计）
  - `app/webui/` 构建产物（Ingress / Docker 使用）
  - 本地单测：`./START.sh addon-test`
- `firmware/` — **硬件固件枢纽**（见 [firmware/README.md](firmware/README.md)）
  - `firmware/esphome/` — 生产教室总控（ESPHome）；`./firmware/esphome/START.sh`
  - `firmware/esp32s3_door/` — 旧 HTTP 门固件；**勿新部署**
- `docs/部署说明.md` — 部署与验收要点

## 职责边界

| 在本仓 / HA | 不在本仓 |
|-------------|----------|
| 保命自动化、MQTT/ZHA、Ingress、过渡期云端拉取 | Frigate 发行版、摄像头拉流 |
| **SmartCenter Add-on** 人脸库、工作台、刷脸 grant | 向量上云、Frigate 做人脸开门、自建登录 |
| **RFID 资产防盗**（ESPHome 比对 + HA 白名单/通知） | LOBN_FireClassroom 业务账 / 小程序 |
| **门禁脉冲**（`lobn_office` ← grant → `home/<node>/door/command`） | 旧 HTTP `EspDoorAdapter`（遗留） |

RFID：[docs/资产防盗-RFID.md](../docs/资产防盗-RFID.md) · 契约：[docs/接口契约.md](../docs/接口契约.md)。  
烧录：`./firmware/esphome/START.sh`（Device Builder）或 `./START.sh flash`。
