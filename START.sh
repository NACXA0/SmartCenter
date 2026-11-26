#!/usr/bin/env bash
# SmartCenter 交互菜单：启动 / 运维 / 环境检测（选中后清屏覆盖刷新）
# HA 经 uv 依赖安装；业务在 custom_components/lobn_office，不改主干。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
CONFIG_DIR="$ROOT/config"
PID_FILE="$ROOT/data/hass.pid"
LOG_FILE="$ROOT/data/hass.log"
EXPORT_DIR="$ROOT/export"
YES=0
CI=0

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

need_uv() {
  have uv || {
    echo "未找到 uv，正在安装…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
  }
}

ensure_dirs() {
  mkdir -p "$ROOT/data" "$CONFIG_DIR/.lobn_audit"
}

# ---------- 环境 ----------
cmd_diagnose() {
  echo "=== 环境检测 ==="
  local fail=0
  need_uv
  have uv && echo "[OK] uv $(uv --version 2>/dev/null | head -1)" || { echo "[FAIL] uv"; fail=1; }
  local py
  py="$(uv python find 3.14 2>/dev/null || true)"
  if [[ -n "$py" ]]; then echo "[OK] python $py"; else echo "[WARN] 未安装 Python 3.14，请先环境修复"; fi
  [[ -f "$ROOT/VERSION" ]] && echo "[OK] HA 钉选 $(cat "$ROOT/VERSION")" || echo "[WARN] 无 VERSION"
  [[ -f "$ROOT/pyproject.toml" ]] && echo "[OK] pyproject.toml" || { echo "[FAIL] pyproject.toml"; fail=1; }
  [[ -d "$CONFIG_DIR/custom_components/lobn_office" ]] && echo "[OK] lobn_office 自定义集成" || { echo "[FAIL] 缺 lobn_office"; fail=1; }
  [[ -f "$CONFIG_DIR/configuration.yaml" ]] && echo "[OK] configuration.yaml" || { echo "[FAIL] configuration.yaml"; fail=1; }
  if [[ -f "$CONFIG_DIR/secrets.yaml" ]]; then
    local mode
    mode="$(stat -c '%a' "$CONFIG_DIR/secrets.yaml" 2>/dev/null || echo '?')"
    if [[ "$mode" == "600" || "$mode" == "400" ]]; then
      echo "[OK] secrets.yaml 权限 $mode"
    else
      echo "[WARN] secrets.yaml 权限 $mode（建议 chmod 600）"
    fi
  else
    echo "[WARN] 无 secrets.yaml（repair 可从 example 生成）"
  fi
  if [[ -d "$ROOT/.venv" ]]; then echo "[OK] .venv"; else echo "[WARN] 无 .venv，请环境修复"; fi
  echo "--- 磁盘 ---"
  df -h "$ROOT" | tail -1
  return "$fail"
}

cmd_repair() {
  need_uv
  ensure_dirs
  echo "将执行: uv python install 3.14 && uv sync"
  if [[ "$YES" -eq 1 ]] || { read -r -p "继续? [y/N] " a && [[ "$a" =~ ^[Yy]$ ]]; }; then
    uv python install 3.14
    uv sync
  fi
  if [[ ! -f "$CONFIG_DIR/secrets.yaml" && -f "$CONFIG_DIR/secrets.yaml.example" ]]; then
    cp "$CONFIG_DIR/secrets.yaml.example" "$CONFIG_DIR/secrets.yaml"
    chmod 600 "$CONFIG_DIR/secrets.yaml"
    echo "已生成 config/secrets.yaml（请填写后保持 0600）"
  fi
  echo "修复完成。HA 钉选：$(cat "$ROOT/VERSION" 2>/dev/null || echo '?')"
}

cmd_test() {
  need_uv
  ensure_dirs
  # 单测不依赖完整 homeassistant；优先本机 .venv，避免 uv sync 拉 HA 超时
  if [[ ! -x "$ROOT/.venv/bin/pytest" ]]; then
    echo "安装轻量测试依赖（pydantic/httpx/pytest，不含完整 HA）…"
    uv venv --python 3.14
    uv pip install "pydantic>=2.10" "httpx>=0.28" "pytest>=8.3" "pytest-asyncio>=0.25"
  fi
  echo "=== 单元测试（热路径/HMAC/门禁，不启完整 HA）==="
  PYTHONPATH=config/custom_components "$ROOT/.venv/bin/pytest" -q
}

# ---------- 启动 ----------
is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

cmd_start() {
  need_uv
  ensure_dirs
  [[ -d "$ROOT/.venv" ]] || cmd_repair
  if is_running; then
    echo "已在运行 pid=$(cat "$PID_FILE")"
    return 0
  fi
  echo "启动 Home Assistant → $CONFIG_DIR"
  nohup uv run hass -c "$CONFIG_DIR" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  echo "pid=$(cat "$PID_FILE")  日志 $LOG_FILE"
  echo "面板: http://smartcenter.lobn:8123 或 http://127.0.0.1:8123"
  echo "首次请在「设置 → 设备与服务」添加「智慧办公室」集成"
}

cmd_dev() {
  # Center 无独立 Vite：开发=前台 HA，日志打终端
  need_uv
  ensure_dirs
  [[ -d "$ROOT/.venv" ]] || cmd_repair
  if is_running; then
    echo "先停止后台 HA…"
    cmd_stop
  fi
  echo "开发/前台：Home Assistant → $CONFIG_DIR"
  echo "面板 http://127.0.0.1:8123  · Ctrl+C 停止"
  echo "----------------------------------------"
  uv run hass -c "$CONFIG_DIR"
}

cmd_export() {
  # 无独立 frontend.zip：管理 Web = HA 自带 UI + lobn_office
  ensure_dirs
  mkdir -p "$EXPORT_DIR"
  local stamp stage out
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  out="$EXPORT_DIR/center-${stamp}.zip"
  stage="$(mktemp -d)"
  echo "=== 导出 SmartCenter 运行包（不含 secrets / .venv / 存储）==="
  mkdir -p "$stage/SmartCenter/config" "$stage/SmartCenter/data"
  rsync -a \
    --exclude '__pycache__' --exclude '*.pyc' \
    "$CONFIG_DIR/custom_components" \
    "$stage/SmartCenter/config/"
  [[ -f "$CONFIG_DIR/configuration.yaml" ]] && cp "$CONFIG_DIR/configuration.yaml" "$stage/SmartCenter/config/"
  [[ -f "$CONFIG_DIR/secrets.yaml.example" ]] && cp "$CONFIG_DIR/secrets.yaml.example" "$stage/SmartCenter/config/"
  for f in pyproject.toml START.sh VERSION README.md; do
    [[ -f "$ROOT/$f" ]] && cp "$ROOT/$f" "$stage/SmartCenter/"
  done
  [[ -f "$ROOT/uv.lock" ]] && cp "$ROOT/uv.lock" "$stage/SmartCenter/"
  cat >"$stage/SmartCenter/README-RUN.txt" <<'EOF'
SmartCenter 运行包
1. uv sync
2. cp config/secrets.yaml.example config/secrets.yaml && chmod 600 …
3. ./START.sh start   # 或「开发」前台
管理 Web = Home Assistant :8123（无单独 Vite 前端包）
业务集成: config/custom_components/lobn_office
EOF
  (cd "$stage" && zip -qr "$out" SmartCenter)
  ln -sfn "$(basename "$out")" "$EXPORT_DIR/center.zip"
  echo "[OK] $out"
  echo "软链: $EXPORT_DIR/center.zip"
  rm -rf "$stage"
}

cmd_stop() {
  if ! is_running; then
    echo "未运行"
    rm -f "$PID_FILE"
    return 0
  fi
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  sleep 1
  if is_running; then kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true; fi
  rm -f "$PID_FILE"
  echo "已停止"
}

# ---------- 运维 ----------
cmd_status() {
  echo "=== 状态 ==="
  if is_running; then
    echo "HA: running  pid=$(cat "$PID_FILE")"
  else
    echo "HA: stopped"
  fi
  echo "配置目录: $CONFIG_DIR"
  echo "集成: lobn_office → $CONFIG_DIR/custom_components/lobn_office"
  echo "--- 最近日志 ---"
  if [[ -f "$LOG_FILE" ]]; then tail -n 25 "$LOG_FILE"; else echo "(尚日志)"; fi
}

cmd_logs() {
  mkdir -p "$(dirname "$LOG_FILE")"
  touch "$LOG_FILE"
  echo "跟踪日志（Ctrl+C 返回）: $LOG_FILE"
  trap 'trap - INT; echo; echo "已停止跟踪"' INT
  tail -f "$LOG_FILE" || true
  trap - INT
}

cmd_check_secrets() {
  if [[ ! -f "$CONFIG_DIR/secrets.yaml" ]]; then
    echo "无 secrets.yaml"
    return 1
  fi
  chmod 600 "$CONFIG_DIR/secrets.yaml"
  echo "已确保 secrets.yaml 为 0600"
  echo "请确认其中 HMAC / 门禁 URL / 企业微信 已填写，且勿提交 git"
}

cmd_help() {
  cat <<EOF
用法: ./START.sh [子命令] [--yes|--ci]

SmartCenter = Home Assistant（uv 依赖）+ custom_components/lobn_office
升级 HA：改 pyproject.toml / VERSION 中版本后执行「环境修复」

交互菜单：
  启动   后台 HA / 开发(前台) / 导出 / 杀死 / 教室总控固件
  运维   状态 / 日志 / 校验密钥权限 / 帮助
  环境   环境检测 / 环境修复 / 自动化测试
  主菜单亦可直接选「教室总控固件」→ firmware/esphome/START.sh

说明: 管理 Web 即 HA 面板，无独立 Vite；导出仅 center.zip。
生产固件: firmware/esphome/（Device Builder）；遗留: firmware/esp32s3_door/
子命令: diagnose | repair | start | dev | export | stop | status | logs | secrets | test | flash | help
域名建议: smartcenter.lobn → 本机
EOF
}

run_action() {
  local title="$1"
  shift
  clear_screen
  echo "SmartCenter · $title"
  echo "----------------------------------------"
  "$@" || true
  pause_back
}

cmd_esphome_flash() {
  local entry="$ROOT/firmware/esphome/START.sh"
  if [[ ! -x "$entry" ]]; then
    if [[ -f "$entry" ]]; then
      chmod +x "$entry" || true
    else
      echo "[FAIL] 缺少 $entry"
      return 1
    fi
  fi
  # 转调固件目录 START（Device Builder / CLI）
  "$entry" "$@"
}

menu_start() {
  while true; do
    clear_screen
    cat <<EOF
SmartCenter · 启动
  1) 后台启动 Home Assistant
  2) 开发（前台 HA，终端；管理 Web 即 HA）
  3) 导出运行包（center.zip，无独立前端包）
  4) 杀死进程
  5) 教室总控固件（firmware/esphome）
  0) 返回上级
EOF
    read -r -p "> " c
    case "$c" in
      1) run_action "启动 HA" cmd_start ;;
      2) clear_screen; echo "SmartCenter · 开发"; echo "----------------------------------------"; cmd_dev || true; pause_back ;;
      3) run_action "导出运行包" cmd_export ;;
      4) run_action "杀死进程" cmd_stop ;;
      5) clear_screen; cmd_esphome_flash || true; pause_back ;;
      0) return 0 ;;
      *) ;;
    esac
  done
}

menu_ops() {
  while true; do
    clear_screen
    cat <<EOF
SmartCenter · 运维
  1) 状态
  2) 日志（跟踪）
  3) 校验密钥权限
  4) 帮助
  0) 返回上级
EOF
    read -r -p "> " c
    case "$c" in
      1) run_action "状态" cmd_status ;;
      2) clear_screen; echo "SmartCenter · 日志"; echo "----------------------------------------"; cmd_logs; pause_back ;;
      3) run_action "校验密钥" cmd_check_secrets ;;
      4) run_action "帮助" cmd_help ;;
      0) return 0 ;;
      *) ;;
    esac
  done
}

menu_env() {
  while true; do
    clear_screen
    cat <<EOF
SmartCenter · 环境检测
  1) 环境检测
  2) 环境修复 / 安装
  3) 自动化测试
  0) 返回上级
EOF
    read -r -p "> " c
    case "$c" in
      1) run_action "环境检测" cmd_diagnose ;;
      2) run_action "环境修复" cmd_repair ;;
      3) run_action "自动化测试" cmd_test ;;
      0) return 0 ;;
      *) ;;
    esac
  done
}

menu() {
  while true; do
    clear_screen
    cat <<EOF
SmartCenter（中央总控）
  1) 启动
  2) 运维
  3) 环境检测
  4) 教室总控固件（firmware/esphome）
  0) 退出
EOF
    read -r -p "> " choice
    case "$choice" in
      1) menu_start ;;
      2) menu_ops ;;
      3) menu_env ;;
      4) clear_screen; cmd_esphome_flash || true; pause_back ;;
      0) clear_screen; exit 0 ;;
      *) ;;
    esac
  done
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    "") menu ;;
    diagnose) cmd_diagnose ;;
    repair|install) cmd_repair ;;
    start) cmd_start ;;
    dev|start-fg) cmd_dev ;;
    export) cmd_export ;;
    stop|kill) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    status) cmd_status ;;
    logs) cmd_logs ;;
    secrets) cmd_check_secrets ;;
    test) cmd_test ;;
    flash|esphome) cmd_esphome_flash ;;
    help|-h|--help) cmd_help ;;
    *) echo "未知: $cmd"; cmd_help; exit 1 ;;
  esac
}

main "$@"
