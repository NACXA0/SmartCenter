# SmartCenter · 智慧办公室中央总控

基于 **Home Assistant 2026.11.3**（`requires-python >=3.14.2`），用官方 **自定义集成（custom_components）** 增量开发，**不修改 HA 主干**，升级只需改版本钉并 `uv sync`。

内网域名建议：`smartcenter.lobn`，默认端口 `8123`。界面语言：`zh-Hans`。

## 为什么不用整仓 fork

| 方式 | 升级成本 |
|------|----------|
| fork 改 `homeassistant/components/` | 每次合上游冲突多 |
| **custom_components + 配置入口**（本仓库） | 主干只升依赖；业务全在 `lobn_office` |

HA 提供的增量接口：Config Entry / Config Flow、Entity、HTTP View、Service、DataUpdateCoordinator、Intent/Conversation。

## 快速开始

```bash
./START.sh repair --yes   # uv + Python ≥3.14.2 + 依赖
./START.sh start          # uv run hass -c config
```

浏览器打开 `http://smartcenter.lobn:8123`（或本机 `8123`）。首次按 HA 向导建用户，再在「设置 → 设备与服务」添加 **智慧办公室 (lobn_office)**。

## 结构

- `config/` — HA 配置目录（含 `custom_components/lobn_office`）
- `config/custom_components/lobn_office/` — 自有集成（门禁唯一出口、监控事件入口、授权预取、企业微信、管家意图）
- `tests/` — 热路径 / HMAC / 门禁 mock 单测（不依赖完整 HA）
- `docs/部署说明.md` — systemd、密钥、TLS

## 职责

软件开门**只**由本集成发往 ESP32ETH。监控只上报事件；云端只发授权单。详见主仓库 [`docs/接口契约.md`](../docs/接口契约.md)。
