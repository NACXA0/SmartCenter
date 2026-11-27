# SmartCenter · 待归档（勿作日常入口）

> **状态：已裁定升入父仓根NACXA0/SmartOffice，本目录 / 本远程仓库归档。**  
> 日期：2026-11-27

## 请改去这里

| 你想… | 去哪 |
|-------|------|
| 日常开发 / 热更 | 父仓根：`cd .. && ./START.sh all` |
| Add-on / HA 配置 / 固件 | 父仓根 `addon/` · `config/` · `firmware/` |
| 决策说明 | [docs/决策-归档SmartCenter子模块.md](../docs/决策-归档SmartCenter子模块.md) |
| 手动归档步骤 | [docs/归档-SmartCenter准备清单.md](../docs/归档-SmartCenter准备清单.md) |
| 现行架构 | [docs/架构-HAOS四App.md](../docs/架构-HAOS四App.md) |

**不要**再在本目录执行 `./START.sh`。产品名「SmartCenter Add-on」（HA Ingress / 侧边栏）保留；归档的是**本子模块仓库布局**，不是 Add-on 能力。

父仓已复制本仓源码并改文档指向；GitHub `NACXA0/SmartCenter` 与工作树删除由你按清单手动完成。

---

## 历史摘要（只读对照）

本目录曾是店内 HAOS 配置与集成仓：

- `config/` — HA 配置与过渡期 `lobn_office`
- `addon/` — SmartCenter Add-on（人脸采集 / 库 / 比对 / 工作台）
- `firmware/` — ESPHome 教室总控；`esp32s3_door/` HTTP 遗留

原则未变：**HA 零智能**；刷脸在 Add-on；门禁执行经 MQTT → ESPHome；监控用 Frigate（关 Face Recognition），不是 SmartCCTV。

对照用旧入口（**仅历史**）：

```bash
# 已废弃 —— 请到父仓根
./START.sh all
```
