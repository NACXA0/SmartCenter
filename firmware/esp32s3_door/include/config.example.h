#pragma once
// 复制为 config.h 后填入真实值；config.h 勿提交。

#define LOBN_FW_VERSION "0.1.0"

// W5500 SPI（按实际接线改）
#define PIN_ETH_CS   14
#define PIN_ETH_RST  9
#define PIN_ETH_SCK  12
#define PIN_ETH_MISO 13
#define PIN_ETH_MOSI 11

// 继电器：高电平吸合（短接门锁两线）
#define PIN_RELAY    4
#define RELAY_ACTIVE_HIGH 1

// 可选器件：未接时启动探测失败 → present=false，门服务照常
#define PIN_DHT11    5
#define PIN_PIR      6
#define PIN_BUTTON   7
#define BUTTON_ACTIVE_LOW 1

// 网络：0.0.0.0 表示 DHCP
#define ETH_IP_0 0
#define ETH_IP_1 0
#define ETH_IP_2 0
#define ETH_IP_3 0
#define ETH_GW_0 192
#define ETH_GW_1 168
#define ETH_GW_2 1
#define ETH_GW_3 1
#define ETH_SN_0 255
#define ETH_SN_1 255
#define ETH_SN_2 255
#define ETH_SN_3 0

#define HTTP_PORT 8080

// 与总控 EspDoorAdapter / sense 共用 Bearer token
#define LOBN_DOOR_TOKEN "change-me-esp-token"

// 总控上报地址（内网）
#define CENTER_HOST "center.lobn"
#define CENTER_PORT 8123
#define CENTER_SENSE_PATH "/api/lobn_office/esp/sense"

#define TELEMETRY_INTERVAL_MS 30000
#define PIR_DEBOUNCE_MS 200
#define BUTTON_DEBOUNCE_MS 50
#define BUTTON_PRESS_COOLDOWN_MS 3000
