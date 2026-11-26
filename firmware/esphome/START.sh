#!/usr/bin/env bash
# 教室总控固件入口（生产：ESPHome）
# 日常：ESPHome Device Builder Web UI；CI/无头：compile / upload
# 遗留 HTTP 固件见 ../esp32s3_door/（本脚本不部署）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
YES=0
CI=0
CONFIG_FILE="${ESPHOME_CONFIG:-classroom_node.yaml}"
VENV_DIR="${ESPHOME_VENV:-$ROOT/.venv}"
BUILDER_PORT="${ESPHOME_BUILDER_PORT:-6052}"

for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    --ci) CI=1; YES=1 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

clear_screen() {
  if [[ -t 1 && "$CI" -eq 0 ]]; then
    printf '\033[H\033[2J'
  fi
}

pause_back() {
  if [[ "$CI" -eq 1 || "$YES" -eq 1 ]]; then return 0; fi
  echo
  read -r -p "按回车返回菜单… " _
}

run_action() {
  local title="$1"
  shift
  clear_screen
  echo "firmware/esphome · $title"
  echo "----------------------------------------"
  "$@" || true
  pause_back
}

activate_venv() {
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
}

ensure_venv_builder() {
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "创建 venv: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  activate_venv
  if ! python -c "import esphome_device_builder" 2>/dev/null; then
    echo "安装 esphome-device-builder[esphome] …"
    pip install -U pip
    pip install 'esphome-device-builder[esphome]'
  fi
  if ! have esphome && ! python -c "import esphome" 2>/dev/null; then
    echo "[WARN] esphome 未随 extra 装上，尝试 pip install esphome"
    pip install esphome
  fi
}

need_esphome_cli() {
  if have esphome; then return 0; fi
  if [[ -x "$VENV_DIR/bin/esphome" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    return 0
  fi
  echo "[FAIL] 未找到 esphome CLI"
  echo "请先执行菜单「准备 / 更新 Device Builder 环境」，或："
  echo "  python3 -m venv .venv && . .venv/bin/activate"
  echo "  pip install 'esphome-device-builder[esphome]'"
  return 1
}

cmd_diagnose() {
  echo "=== firmware/esphome 检测 ==="
  local fail=0
  echo "配置目录: $ROOT"
  [[ -f "$ROOT/$CONFIG_FILE" ]] && echo "[OK] $CONFIG_FILE" || { echo "[FAIL] 缺 $CONFIG_FILE"; fail=1; }
  [[ -f "$ROOT/packages/door.yaml" ]] && echo "[OK] packages/door.yaml" || { echo "[FAIL] packages"; fail=1; }
  if [[ -f "$ROOT/secrets.yaml" ]]; then
    echo "[OK] secrets.yaml"
  else
    echo "[WARN] 无 secrets.yaml（可菜单生成）"
  fi
  if [[ -d "$VENV_DIR" ]]; then
    echo "[OK] venv $VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate" 2>/dev/null || true
  else
    echo "[WARN] 无 venv（菜单「准备环境」可创建）"
  fi
  if have esphome-device-builder || python -c "import esphome_device_builder" 2>/dev/null; then
    echo "[OK] esphome-device-builder"
  else
    echo "[WARN] 未装 Device Builder（日常烧录建议安装）"
  fi
  if have esphome; then
    echo "[OK] esphome $(esphome version 2>/dev/null | head -1 || echo present)"
  else
    echo "[WARN] esphome CLI 不在 PATH（可用 venv）"
  fi
  echo "--- 串口 ---"
  ls -1 /dev/ttyUSB* /dev/ttyACM* /dev/cu.usb* 2>/dev/null || echo "(未检测到)"
  echo
  echo "遗留 HTTP 固件: ../esp32s3_door/（勿用本 START 部署）"
  echo "Device Builder 默认: http://127.0.0.1:${BUILDER_PORT}"
  return "$fail"
}

cmd_prepare() {
  ensure_venv_builder
  activate_venv
  echo "环境就绪。"
  echo "  Device Builder: esphome-device-builder $ROOT"
  echo "  CLI:            esphome compile $CONFIG_FILE"
  python -c "import esphome; print('esphome import OK')" 2>/dev/null || true
}

cmd_init_secrets() {
  if [[ -f "$ROOT/secrets.yaml" ]]; then
    echo "已存在 secrets.yaml，跳过。"
    return 0
  fi
  if [[ ! -f "$ROOT/secrets.yaml.example" ]]; then
    echo "[FAIL] 缺 secrets.yaml.example"
    return 1
  fi
  cp "$ROOT/secrets.yaml.example" "$ROOT/secrets.yaml"
  if have openssl; then
    local key
    key="$(openssl rand -base64 32)"
    # api_encryption_key 必须是合法 base64（32 字节）
    if have python3; then
      API_KEY="$key" python3 - <<'PY'
from pathlib import Path
import os, re
p = Path("secrets.yaml")
key = os.environ["API_KEY"]
text = p.read_text(encoding="utf-8")
text, n = re.subn(r'^api_encryption_key:\s*.*$', f'api_encryption_key: "{key}"', text, count=1, flags=re.M)
if n != 1:
    raise SystemExit("未能写入 api_encryption_key")
p.write_text(text, encoding="utf-8")
PY
    fi
  fi
  chmod 600 "$ROOT/secrets.yaml" 2>/dev/null || true
  echo "已生成 secrets.yaml（含随机 api_encryption_key）。请填写 Wi‑Fi / MQTT / OTA。"
}

cmd_builder() {
  ensure_venv_builder
  activate_venv
  [[ -f "$ROOT/secrets.yaml" ]] || cmd_init_secrets
  echo "启动 ESPHome Device Builder"
  echo "  目录: $ROOT"
  echo "  打开: http://127.0.0.1:${BUILDER_PORT}"
  echo "  停止: Ctrl+C"
  echo
  # 官方：配置目录为位置参数；--port 随版本可能不同
  if esphome-device-builder --help 2>&1 | grep -qE -- '--port'; then
    exec esphome-device-builder --port "$BUILDER_PORT" "$ROOT"
  else
    echo "(本版 CLI 无 --port，使用默认端口)"
    exec esphome-device-builder "$ROOT"
  fi
}

pick_port() {
  local ports=()
  local p
  for p in /dev/ttyUSB* /dev/ttyACM* /dev/cu.usbmodem* /dev/cu.usbserial*; do
    [[ -e "$p" ]] && ports+=("$p")
  done
  if [[ ${#ports[@]} -eq 0 ]]; then
    echo ""
    return 0
  fi
  if [[ ${#ports[@]} -eq 1 || "$YES" -eq 1 || "$CI" -eq 1 ]]; then
    echo "${ports[0]}"
    return 0
  fi
  echo "可选串口：" >&2
  local i=1
  for p in "${ports[@]}"; do
    echo "  $i) $p" >&2
    i=$((i + 1))
  done
  read -r -p "选择编号 [1]: " idx >&2 || true
  idx="${idx:-1}"
  if [[ "$idx" =~ ^[0-9]+$ ]] && (( idx >= 1 && idx <= ${#ports[@]} )); then
    echo "${ports[$((idx - 1))]}"
  else
    echo "${ports[0]}"
  fi
}

with_esphome() {
  need_esphome_cli || return 1
  if [[ -x "$VENV_DIR/bin/esphome" ]]; then
    activate_venv
  fi
  [[ -f "$ROOT/secrets.yaml" ]] || cmd_init_secrets
  "$@"
}

cmd_compile() { with_esphome esphome compile "$CONFIG_FILE"; }
cmd_upload() {
  local port
  port="$(pick_port)"
  if [[ -n "$port" ]]; then
    with_esphome esphome upload "$CONFIG_FILE" --device "$port"
  else
    with_esphome esphome upload "$CONFIG_FILE"
  fi
}
cmd_run() {
  local port
  port="$(pick_port)"
  if [[ -n "$port" ]]; then
    with_esphome esphome run "$CONFIG_FILE" --device "$port"
  else
    with_esphome esphome run "$CONFIG_FILE"
  fi
}
cmd_logs() {
  local port
  port="$(pick_port)"
  if [[ -n "$port" ]]; then
    with_esphome esphome logs "$CONFIG_FILE" --device "$port"
  else
    with_esphome esphome logs "$CONFIG_FILE"
  fi
}
cmd_clean() { with_esphome esphome clean "$CONFIG_FILE"; }

cmd_help() {
  cat <<EOF
教室总控固件 · firmware/esphome/START.sh

生产配置目录即本目录（Device Builder 打开后可见 classroom_node.yaml）。

推荐日常：
  ./START.sh              # 菜单 → 启动 Device Builder
  ./START.sh builder      # 直接打开 Web UI :${BUILDER_PORT}

无头 / CI：
  ./START.sh prepare
  ./START.sh compile
  ./START.sh upload

环境变量: ESPHOME_CONFIG、ESPHOME_VENV、ESPHOME_BUILDER_PORT
遗留: ../esp32s3_door/（HTTP，勿部署）
EOF
}

menu() {
  while true; do
    clear_screen
    cat <<EOF
firmware/esphome · 教室总控
配置: $CONFIG_FILE
  1) 启动 Device Builder（推荐 · Web :${BUILDER_PORT}）
  2) 准备 / 更新 Python 环境
  3) 环境检测
  4) 生成 secrets.yaml
  5) CLI 编译
  6) CLI 烧录
  7) CLI run（编译+烧录+日志）
  8) CLI 日志
  9) CLI clean
  h) 帮助
  0) 退出
EOF
    read -r -p "> " c
    case "$c" in
      1) clear_screen; cmd_builder ;;
      2) run_action "准备环境" cmd_prepare ;;
      3) run_action "环境检测" cmd_diagnose ;;
      4) run_action "生成 secrets" cmd_init_secrets ;;
      5) run_action "编译" cmd_compile ;;
      6) run_action "烧录" cmd_upload ;;
      7) clear_screen; echo "CLI run"; echo "----------------------------------------"; cmd_run || true; pause_back ;;
      8) clear_screen; echo "CLI 日志"; echo "----------------------------------------"; cmd_logs || true; pause_back ;;
      9) run_action "clean" cmd_clean ;;
      h|H) run_action "帮助" cmd_help ;;
      0) clear_screen; exit 0 ;;
      *) ;;
    esac
  done
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    "") menu ;;
    builder|ui|dashboard) cmd_builder ;;
    prepare|install) cmd_prepare ;;
    diagnose) cmd_diagnose ;;
    secrets|init-secrets) cmd_init_secrets ;;
    compile) cmd_compile ;;
    upload|flash) cmd_upload ;;
    run) cmd_run ;;
    logs) cmd_logs ;;
    clean) cmd_clean ;;
    help|-h|--help) cmd_help ;;
    *) echo "未知: $cmd"; cmd_help; exit 1 ;;
  esac
}

main "$@"
