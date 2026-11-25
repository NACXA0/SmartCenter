/**
 * LOBN 门禁：ESP32-S3 + W5500。
 * 只执行总控 door.command.v1 脉冲；DHT11 / PIR / 按钮可缺省，绝不自行开门。
 */
#include <Arduino.h>
#include <SPI.h>
#include <Ethernet.h>
#include <ArduinoJson.h>
#include <DHT.h>

#include "config.h"

#ifndef LOBN_FW_VERSION
#define LOBN_FW_VERSION "0.1.0"
#endif

static byte mac[] = {0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED};
static EthernetServer server(HTTP_PORT);
static DHT dht(PIN_DHT11, DHT11);

static bool dht_present = false;
static bool pir_present = false;
static bool button_present = false;

static bool pulsing = false;
static String active_command_id;
static unsigned long pulse_end_ms = 0;

static int last_pir = LOW;
static unsigned long pir_change_ms = 0;
static bool pir_stable_high = false;

static int last_btn = HIGH;
static unsigned long btn_change_ms = 0;
static bool btn_down = false;
static unsigned long last_press_report_ms = 0;

static unsigned long last_telemetry_ms = 0;

static void relay_set(bool on) {
  bool level = RELAY_ACTIVE_HIGH ? on : !on;
  digitalWrite(PIN_RELAY, level ? HIGH : LOW);
}

static void relay_release() {
  relay_set(false);
  pulsing = false;
  active_command_id = "";
  pulse_end_ms = 0;
}

static float clamp_seconds(float s) {
  if (s < 0.2f) return 0.2f;
  if (s > 15.0f) return 15.0f;
  return s;
}

static bool auth_ok(EthernetClient &client, const String &req) {
  int idx = req.indexOf("Authorization:");
  if (idx < 0) return false;
  int line_end = req.indexOf("\r\n", idx);
  String line = req.substring(idx, line_end >= 0 ? line_end : req.length());
  String expect = String("Bearer ") + LOBN_DOOR_TOKEN;
  return line.indexOf(expect) >= 0;
}

static void send_json(EthernetClient &client, int code, const String &body) {
  client.print("HTTP/1.1 ");
  client.print(code);
  client.println(code == 200 ? " OK" : (code == 409 ? " Conflict" : " Error"));
  client.println("Content-Type: application/json");
  client.print("Content-Length: ");
  client.println(body.length());
  client.println("Connection: close");
  client.println();
  client.print(body);
}

static String uuid_like() {
  char buf[40];
  snprintf(buf, sizeof(buf), "%08lx-%04lx-%04lx-%04lx-%08lx%04lx",
           (unsigned long)esp_random(),
           (unsigned long)(esp_random() & 0xffff),
           (unsigned long)(esp_random() & 0xffff),
           (unsigned long)(esp_random() & 0xffff),
           (unsigned long)esp_random(),
           (unsigned long)(esp_random() & 0xffff));
  return String(buf);
}

static bool post_sense(const String &json) {
  EthernetClient c;
  if (!c.connect(CENTER_HOST, CENTER_PORT)) return false;
  c.print("POST ");
  c.print(CENTER_SENSE_PATH);
  c.println(" HTTP/1.1");
  c.print("Host: ");
  c.println(CENTER_HOST);
  c.print("Authorization: Bearer ");
  c.println(LOBN_DOOR_TOKEN);
  c.println("Content-Type: application/json");
  c.print("Content-Length: ");
  c.println(json.length());
  c.println("Connection: close");
  c.println();
  c.print(json);
  unsigned long start = millis();
  while (c.connected() && millis() - start < 1500) {
    while (c.available()) (void)c.read();
  }
  c.stop();
  return true;
}

static void report_sense(const char *kind, const char *edge, float temp, float hum, bool has_th) {
  JsonDocument doc;
  doc["schema"] = "esp.sense.v1";
  doc["event_id"] = uuid_like();
  doc["kind"] = kind;
  if (edge && edge[0]) doc["edge"] = edge;
  doc["ts"] = (double)(millis() / 1000.0);  // 上线后可换 NTP；总控容忍偏差
  doc["device"]["dht"] = dht_present;
  doc["device"]["pir"] = pir_present;
  doc["device"]["button"] = button_present;
  if (has_th) {
    doc["temperature_c"] = temp;
    doc["humidity_pct"] = hum;
  }
  String out;
  serializeJson(doc, out);
  for (int i = 0; i < 2; i++) {
    if (post_sense(out)) break;
    delay(50);
  }
}

static void handle_health(EthernetClient &client) {
  JsonDocument doc;
  doc["ok"] = true;
  doc["version"] = LOBN_FW_VERSION;
  doc["door"] = pulsing ? "pulsing" : "locked";
  doc["command_id"] = active_command_id;
  doc["device"]["dht"] = dht_present;
  doc["device"]["pir"] = pir_present;
  doc["device"]["button"] = button_present;
  String out;
  serializeJson(doc, out);
  send_json(client, 200, out);
}

static void handle_door_command(EthernetClient &client, const String &body) {
  JsonDocument doc;
  if (deserializeJson(doc, body)) {
    send_json(client, 400, "{\"ok\":false,\"error\":\"invalid_json\"}");
    return;
  }
  const char *schema = doc["schema"] | "";
  const char *action = doc["action"] | "open";
  const char *cid = doc["command_id"] | "";
  float seconds = doc["seconds"] | 5.0f;

  if (strcmp(schema, "door.command.v1") != 0 || !cid[0]) {
    send_json(client, 400, "{\"ok\":false,\"error\":\"bad_command\"}");
    return;
  }

  if (strcmp(action, "close") == 0) {
    relay_release();
    send_json(client, 200, String("{\"result\":\"released\",\"command_id\":\"") + cid + "\"}");
    return;
  }

  if (strcmp(action, "open") != 0) {
    send_json(client, 400, "{\"ok\":false,\"error\":\"unknown_action\"}");
    return;
  }

  if (pulsing) {
    send_json(client, 409, "{\"ok\":false,\"error\":\"busy\"}");
    return;
  }

  seconds = clamp_seconds(seconds);
  active_command_id = cid;
  pulsing = true;
  pulse_end_ms = millis() + (unsigned long)(seconds * 1000.0f);
  relay_set(true);

  JsonDocument resp;
  resp["result"] = "pulsed";
  resp["command_id"] = cid;
  resp["seconds"] = seconds;
  String out;
  serializeJson(resp, out);
  send_json(client, 200, out);
}

static void serve_http() {
  EthernetClient client = server.available();
  if (!client) return;
  String req;
  unsigned long start = millis();
  while (client.connected() && millis() - start < 2000) {
    while (client.available()) {
      char c = client.read();
      req += c;
      if (req.endsWith("\r\n\r\n")) break;
    }
    if (req.endsWith("\r\n\r\n")) break;
  }
  int content_len = 0;
  int cl = req.indexOf("Content-Length:");
  if (cl >= 0) {
    content_len = req.substring(cl + 15).toInt();
  }
  String body;
  while ((int)body.length() < content_len && millis() - start < 3000) {
    while (client.available() && (int)body.length() < content_len) {
      body += (char)client.read();
    }
  }

  bool get_health = req.startsWith("GET /v1/health");
  bool post_door = req.startsWith("POST /v1/door/command");

  if (get_health) {
    handle_health(client);
  } else if (post_door) {
    if (!auth_ok(client, req)) {
      send_json(client, 401, "{\"ok\":false,\"error\":\"unauthorized\"}");
    } else {
      handle_door_command(client, body);
    }
  } else {
    send_json(client, 404, "{\"ok\":false,\"error\":\"not_found\"}");
  }
  delay(1);
  client.stop();
}

static void probe_devices() {
  dht.begin();
  delay(1500);
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  // 上电垃圾值：约 85℃ 且湿度 0
  if (!isnan(t) && !isnan(h) && !(fabsf(t - 85.0f) < 0.5f && h < 0.5f)) {
    dht_present = true;
  } else {
    dht_present = false;
  }

  pinMode(PIN_PIR, INPUT);
  int p1 = digitalRead(PIN_PIR);
  delay(5);
  int p2 = digitalRead(PIN_PIR);
  pir_present = (p1 == p2);  // 悬空抖动时仍可能误判；缺省靠接线稳定
  last_pir = p1;

  pinMode(PIN_BUTTON, INPUT_PULLUP);
  button_present = true;  // 上拉按键：未接也是高电平，默认 present；总控可抑制
  last_btn = digitalRead(PIN_BUTTON);
}

static bool dht_sample(float &t, float &h) {
  if (!dht_present) return false;
  t = dht.readTemperature();
  h = dht.readHumidity();
  if (isnan(t) || isnan(h)) return false;
  if (fabsf(t - 85.0f) < 0.5f && h < 0.5f) return false;
  if (t < -10.0f || t > 60.0f || h < 0.0f || h > 100.0f) return false;
  return true;
}

static void poll_sensors() {
  unsigned long now = millis();

  if (pir_present) {
    int v = digitalRead(PIN_PIR);
    if (v != last_pir) {
      pir_change_ms = now;
      last_pir = v;
    } else if (now - pir_change_ms >= PIR_DEBOUNCE_MS) {
      bool high = (v == HIGH);
      if (high && !pir_stable_high) {
        pir_stable_high = true;
        report_sense("pir", "rise", 0, 0, false);
      } else if (!high && pir_stable_high) {
        pir_stable_high = false;
        report_sense("pir", "fall", 0, 0, false);
      }
    }
  }

  if (button_present) {
    int raw = digitalRead(PIN_BUTTON);
    int pressed_level = BUTTON_ACTIVE_LOW ? LOW : HIGH;
    if (raw != last_btn) {
      btn_change_ms = now;
      last_btn = raw;
    } else if (now - btn_change_ms >= BUTTON_DEBOUNCE_MS) {
      bool down = (raw == pressed_level);
      if (down && !btn_down) {
        btn_down = true;
        if (now - last_press_report_ms >= BUTTON_PRESS_COOLDOWN_MS) {
          last_press_report_ms = now;
          report_sense("button", "press", 0, 0, false);
        }
      } else if (!down && btn_down) {
        btn_down = false;
        report_sense("button", "release", 0, 0, false);
      }
    }
  }

  if (now - last_telemetry_ms >= TELEMETRY_INTERVAL_MS) {
    last_telemetry_ms = now;
    float t = 0, h = 0;
    bool ok = dht_sample(t, h);
    report_sense("telemetry", "", t, h, ok);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RELAY, OUTPUT);
  relay_release();

  SPI.begin(PIN_ETH_SCK, PIN_ETH_MISO, PIN_ETH_MOSI, PIN_ETH_CS);
  Ethernet.init(PIN_ETH_CS);
#if ETH_IP_0 == 0 && ETH_IP_1 == 0 && ETH_IP_2 == 0 && ETH_IP_3 == 0
  Ethernet.begin(mac);
#else
  IPAddress ip(ETH_IP_0, ETH_IP_1, ETH_IP_2, ETH_IP_3);
  IPAddress gw(ETH_GW_0, ETH_GW_1, ETH_GW_2, ETH_GW_3);
  IPAddress sn(ETH_SN_0, ETH_SN_1, ETH_SN_2, ETH_SN_3);
  Ethernet.begin(mac, ip, gw, gw, sn);
#endif
  delay(1000);
  server.begin();
  probe_devices();
  Serial.printf("lobn door fw=%s ip=%s\n", LOBN_FW_VERSION, Ethernet.localIP().toString().c_str());
}

void loop() {
  if (pulsing && (long)(millis() - pulse_end_ms) >= 0) {
    relay_release();
  }
  serve_http();
  poll_sensors();
}
