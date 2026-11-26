# SmartCenter Add-on

HAOS Supervisor Add-on：交互式人脸采集、本地人脸库、门口比对 → `business/access/grant`，以及 Ingress **工作台**（概览 / 采集 / 人脸库 / 审计）。

- 专文：[docs/人脸-SmartCenter-Add-on.md](../../docs/人脸-SmartCenter-Add-on.md)  
- 本机热更：[docs/开发工作流.md](../../docs/开发工作流.md)  
- 前端源码：[web/README.md](web/README.md)

## 开发（本机优先，不连店内 HAOS）

```bash
cd SmartCenter
./START.sh addon-repair && ./START.sh repair   # 首次各装一次依赖
./START.sh all                                 # 一键前台：Vite HMR + API reload + 本机 HA
# 关终端即停
```

| 场景 | 命令 |
|------|------|
| 一键开发（热更） | `./START.sh all` → 工作台 **:5173** · API **:8080** · HA **:8123** |
| 全栈（构建页同端口） | `./START.sh addon` |
| 仅后端 / 仅前端 | `addon-api` / `addon-ui` |
| 构建工作台 | `addon-ui-build` → `app/webui` |
| 单测 | `addon-test` |
| 停残留 | `stop-all` / `addon-stop` |

默认 `MQTT_HOST=off`。店内 HAOS 只做**生产安装与终验**；日常不要 `env.lan` 绑生产。

## 生产

装到 HAOS；Frigate 关人脸；`packages/face_grant_mqtt.yaml` 译 grant。  
对接步骤：[docs/对接已有HAOS.md](../../docs/对接已有HAOS.md)

长时间运行：日志滚动（`/data/logs/`）、审计/`grants_seen`/孤儿帧自动裁剪、门口匹配限流；详见人脸专文「长时间运行」。

## 目录

| 路径 | 说明 |
|------|------|
| `app/` | FastAPI：会话、store、比对、维护、MQTT |
| `web/` | Vite + React 工作台 |
| `app/webui/` | 构建产物（Ingress / Docker） |
| `config.yaml` | Supervisor 选项与 schema |
| `Dockerfile` | 多阶段：Node 构建 UI + Python 运行时 |
