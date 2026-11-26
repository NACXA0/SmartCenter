# SmartCenter 工作台 UI

Frigate 风格：**无顶栏**；桌面左侧图标侧栏 + 底栏状态；移动端底栏导航。

| 路由 | 页 | 职责 |
|------|-----|------|
| `#/overview` | 概览 | `/api/stats` 统计、待重采 |
| `#/capture` | 采集 | 选人 + 自动质检会话 |
| `#/gallery` | 人脸库 | 启停/删/改名/详情帧/补采 |
| `#/audit` | 审计 | 流水 + 链路灯 |

技术栈：React 18 + Vite + HashRouter（`base: './'`，适配 HA Ingress）+ Radix UI + Lucide。

```bash
# 开发（需后端 :8080；一键 all 已含）
cd SmartCenter && ./START.sh addon-ui

# 构建到 app/webui（生产 / Docker / Ingress）
./START.sh addon-ui-build
```

完整工作流：[docs/开发工作流.md](../../../docs/开发工作流.md) · 产品说明：[docs/人脸-SmartCenter-Add-on.md](../../../docs/人脸-SmartCenter-Add-on.md)。
