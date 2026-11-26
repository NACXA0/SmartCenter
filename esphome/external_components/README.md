# ESPHome external_components（教室总控）

ESPHome 自带不够时，在这里补**小组件**，仍烧 ESPHome 固件，不恢复自研 HTTP 整仓固件。

## 需要外挂的场景

| 场景 | 建议 |
|------|------|
| RS485 / RS232 厂商二进制帧（非 ASCII 行、非 Modbus） | `rfid_uart_frame`：解析后只回调标签字符串 → `rfid_handle_tag` |
| 韦根 26/34 bit | `wiegand_reader`：GPIO 中断或 RMT，输出卡号；勿在 lambda 位采样 |
| Modbus 寄存器读 EPC | 优先用 ESPHome 自带 `modbus` / `modbus_controller`，可不写外挂 |

## 接入约定

1. 组件输出**统一**为标签字符串（EPC hex 或十进制卡号）。
2. 调用 `id(rfid_handle_tag)->execute(tag);`，比对 / 警号 / MQTT 由 `packages/rfid_core.yaml` 负责。
3. 在 `classroom_node.yaml` 增加：

```yaml
external_components:
  - source:
      type: local
      path: external_components
    components: [rfid_uart_frame]   # 或 wiegand_reader
```

4. 一间教室只启用一种读头包（RS485 **或** 韦根）。

组件源码待选定具体读写器型号后再补；联调阶段用 `rfid_rs485.yaml` 里的模拟按钮即可验收 HA 白名单链路。
