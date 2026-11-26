#!/usr/bin/env bash
# SmartCenter 交互菜单：启动 / 运维 / 环境检测（选中后清屏覆盖刷新）
#
# 两套东西，不要混：
#   1) Home Assistant 开发态 —— uv sync 拉 homeassistant；测 lobn_office / packages
#   2) SmartCenter Add-on —— addon/ 里独立 FastAPI；本地 uvicorn --reload，不必装进 HAOS
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
CONFIG_DIR="$ROOT/config"
PID_FILE="$ROOT/data/hass.pid"
LOG_FILE="$ROOT/data/hass.log"
ADDON_DIR="$ROOT/addon"
ADDON_PID_FILE="$ROOT/data/addon.pid"
ADDON_LOG_FILE="$ROOT/data/addon.log"
ADDON_PORT="${SMARTCENTER_ADDON_PORT:-8080}"
ADDON_UI_PORT="${SMARTCENTER_ADDON_UI_PORT:-5173}"
ADDON_UI_PID_FILE="$ROOT/data/addon-ui.pid"
ADDON_WEB_DIR="$ADDON_DIR/web"
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
  echo "【本机 HA 开发环境】uv sync → homeassistant"
  echo "  用于改 packages / lobn_office；比连内网 HAOS 更方便、不碰生产。"
  echo "  人脸 Add-on 另用 ./START.sh addon（不依赖本项）。"
  if [[ "$YES" -eq 1 ]] || { read -r -p "安装本机 HA 依赖? [y/N] " a && [[ "$a" =~ ^[Yy]$ ]]; }; then
    uv python install 3.14
    uv sync
  fi
  if [[ ! -f "$CONFIG_DIR/secrets.yaml" && -f "$CONFIG_DIR/secrets.yaml.example" ]]; then
    cp "$CONFIG_DIR/secrets.yaml.example" "$CONFIG_DIR/secrets.yaml"
    chmod 600 "$CONFIG_DIR/secrets.yaml"
    echo "已生成 config/secrets.yaml（请填写后保持 0600）"
  fi
  echo "完成。HA 钉选：$(cat "$ROOT/VERSION" 2>/dev/null || echo '?')"
}

# ---------- Add-on（独立 FastAPI，本地热重载）----------
addon_venv_python() {
  if [[ -x "$ADDON_DIR/.venv/bin/python" ]]; then
    echo "$ADDON_DIR/.venv/bin/python"
  else
    echo ""
  fi
}

is_addon_running() {
  [[ -f "$ADDON_PID_FILE" ]] && kill -0 "$(cat "$ADDON_PID_FILE")" 2>/dev/null
}

is_addon_ui_running() {
  [[ -f "$ADDON_UI_PID_FILE" ]] && kill -0 "$(cat "$ADDON_UI_PID_FILE")" 2>/dev/null
}

ensure_addon_py() {
  local py
  py="$(addon_venv_python)"
  if [[ -z "$py" ]] || ! "$py" -c "import uvicorn" 2>/dev/null; then
    cmd_addon_repair
    py="$(addon_venv_python)"
  fi
  echo "$py"
}

addon_export_env() {
  export SMARTCENTER_DATA="${SMARTCENTER_DATA:-$ADDON_DIR/data}"
  export SMARTCENTER_DEV_AUTH="${SMARTCENTER_DEV_AUTH:-1}"
  export SMARTCENTER_EMBEDDER="${SMARTCENTER_EMBEDDER:-mock}"
  # 本机无 HAOS Mosquitto；要联真实总线再 export MQTT_HOST=…
  export MQTT_HOST="${MQTT_HOST:-off}"
  mkdir -p "$SMARTCENTER_DATA"
}

cmd_addon_repair() {
  need_uv
  ensure_dirs
  [[ -d "$ADDON_DIR" ]] || { echo "[FAIL] 缺少 $ADDON_DIR"; return 1; }
  echo "【Add-on】安装依赖（FastAPI 等，不含 homeassistant）"
  local index="${UV_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
  (
    cd "$ADDON_DIR"
    [[ -d .venv ]] || uv venv .venv
    UV_INDEX_URL="$index" uv pip install -r requirements-dev.txt --python .venv/bin/python
  )
  echo "就绪。开发: ./START.sh addon · 单测: ./START.sh addon-test"
}

cmd_addon_test() {
  ensure_dirs
  local py
  py="$(ensure_addon_py)"
  echo "=== Add-on 单测 ==="
  (cd "$ADDON_DIR" && "$py" -m pytest -q)
}

open_browser() {
  local url="$1"
  [[ "$CI" -eq 1 ]] && return 0
  if have xdg-open; then
    xdg-open "$url" >/dev/null 2>&1 || true
  elif have sensible-browser; then
    sensible-browser "$url" >/dev/null 2>&1 || true
  fi
}

# 仅后端（前台）
cmd_addon_api() {
  ensure_dirs
  [[ -d "$ADDON_DIR" ]] || { echo "[FAIL] 缺少 $ADDON_DIR"; return 1; }
  local py
  py="$(ensure_addon_py)"
  addon_export_env
  echo "Add-on 后端 API → http://127.0.0.1:${ADDON_PORT}/  （/docs · /healthz）"
  echo "  改 app/ 热重载；Ctrl+C 结束 · 采集页请另开「仅前端」或用「全栈」"
  (
    cd "$ADDON_DIR"
    exec "$py" -m uvicorn app.main:app --host 127.0.0.1 --port "$ADDON_PORT" --reload --app-dir .
  )
}

ensure_addon_web_node() {
  [[ -d "$ADDON_WEB_DIR" ]] || { echo "[FAIL] 缺少 $ADDON_WEB_DIR"; return 1; }
  if [[ ! -d "$ADDON_WEB_DIR/node_modules" ]]; then
    echo "安装前端依赖（npm install）…"
    (cd "$ADDON_WEB_DIR" && npm install)
  fi
}

cmd_addon_ui_build() {
  ensure_addon_web_node || return 1
  echo "构建工作台 → $ADDON_DIR/app/webui"
  (cd "$ADDON_WEB_DIR" && npm run build)
  echo "完成。生产/全栈用 http://127.0.0.1:${ADDON_PORT}/"
}

# 仅前端：Vite 热更（代理 /api → 本机 Add-on）；需后端已起或稍后起
cmd_addon_ui() {
  ensure_dirs
  ensure_addon_web_node || return 1
  local url="http://127.0.0.1:${ADDON_UI_PORT}/"
  echo "Add-on 前端 Vite → $url"
  echo "  改 web/src 热更新；API 代理 → http://127.0.0.1:${ADDON_PORT}（请先起后端）"
  if is_addon_ui_running; then
    echo "前端已在跑 pid=$(cat "$ADDON_UI_PID_FILE")"
    open_browser "$url"
    return 0
  fi
  open_browser "$url"
  (
    cd "$ADDON_WEB_DIR"
    exec npx vite --host 127.0.0.1 --port "$ADDON_UI_PORT"
  )
}

# 全栈：后端后台 + 浏览器打开同域采集页（生产同构：API 兼静态）
cmd_addon_full() {
  ensure_dirs
  [[ -d "$ADDON_DIR" ]] || { echo "[FAIL] 缺少 $ADDON_DIR"; return 1; }
  local py
  py="$(ensure_addon_py)"
  addon_export_env
  if ! is_addon_running; then
    echo "后台启动后端…"
    (
      cd "$ADDON_DIR"
      nohup "$py" -m uvicorn app.main:app --host 127.0.0.1 --port "$ADDON_PORT" --reload --app-dir . \
        >>"$ADDON_LOG_FILE" 2>&1 &
      echo $! >"$ADDON_PID_FILE"
    )
    sleep 1
  fi
  local url="http://127.0.0.1:${ADDON_PORT}/"
  echo "全栈就绪（API + 采集页同端口）→ $url"
  echo "  日志 $ADDON_LOG_FILE · 停: ./START.sh addon-stop"
  open_browser "$url"
  if [[ "$CI" -eq 1 || "$YES" -eq 1 ]]; then
    return 0
  fi
  echo "按 Ctrl+C 停止跟踪日志（服务仍后台）；要停服务用菜单运维或 addon-stop"
  trap 'trap - INT; echo' INT
  tail -f "$ADDON_LOG_FILE" || true
  trap - INT
}

# 兼容旧名：addon / addon-dev = 全栈前台（uvicorn 兼页面，Ctrl+C 停）
cmd_addon_dev() {
  ensure_dirs
  [[ -d "$ADDON_DIR" ]] || { echo "[FAIL] 缺少 $ADDON_DIR"; return 1; }
  # 无构建产物时自动编一次工作台
  if [[ ! -d "$ADDON_DIR/app/webui/assets" && -d "$ADDON_WEB_DIR" ]]; then
    cmd_addon_ui_build || echo "[WARN] 前端构建失败，将回落旧静态页（若有）"
  fi
  local py
  py="$(ensure_addon_py)"
  if is_addon_running; then
    echo "后端已在后台跑；打开采集页。停后台: ./START.sh addon-stop"
    open_browser "http://127.0.0.1:${ADDON_PORT}/"
    return 0
  fi
  addon_export_env
  echo "全栈前台（API+页）→ http://127.0.0.1:${ADDON_PORT}/  Ctrl+C 结束"
  open_browser "http://127.0.0.1:${ADDON_PORT}/"
  (
    cd "$ADDON_DIR"
    exec "$py" -m uvicorn app.main:app --host 127.0.0.1 --port "$ADDON_PORT" --reload --app-dir .
  )
}

cmd_addon_start() {
  ensure_dirs
  local py
  py="$(ensure_addon_py)"
  if is_addon_running; then
    echo "后端已在运行 pid=$(cat "$ADDON_PID_FILE")"
    return 0
  fi
  addon_export_env
  echo "后台启动 Add-on 后端 → http://127.0.0.1:${ADDON_PORT}/"
  (
    cd "$ADDON_DIR"
    nohup "$py" -m uvicorn app.main:app --host 127.0.0.1 --port "$ADDON_PORT" --reload --app-dir . \
      >>"$ADDON_LOG_FILE" 2>&1 &
    echo $! >"$ADDON_PID_FILE"
  )
  sleep 1
  echo "pid=$(cat "$ADDON_PID_FILE")  停: ./START.sh addon-stop"
}

_stop_pid_tree() {
  local pid="${1:-}"
  [[ -z "$pid" ]] && return 0
  local c
  for c in $(pgrep -P "$pid" 2>/dev/null || true); do
    _stop_pid_tree "$c"
  done
  kill "$pid" 2>/dev/null || true
}

# 一键：前台会话；关终端 / Ctrl+C = 全部停掉（与终端同生命周期）
# 热更新：uvicorn --reload（API）+ Vite HMR（工作台）+ 本机 HA
cmd_dev_all() {
  ensure_dirs
  need_uv
  echo "=== 一键开发：Add-on(API热更+Vite HMR) + 本机 HA（跟本终端同生共死）==="
  if [[ ! -d "$ROOT/.venv" ]]; then
    echo "首次需安装本机 HA 依赖…"
    YES=1 cmd_repair
  fi
  ensure_addon_web_node || return 1
  local py
  py="$(ensure_addon_py)"
  addon_export_env

  # 清掉先前 nohup/残留，避免端口占用
  if is_addon_running || is_running || is_addon_ui_running; then
    echo "停止已有实例…"
    cmd_stop_all >/dev/null 2>&1 || true
  fi

  local addon_pid="" ui_pid="" ha_pid="" cleaned=0
  local ui_log="$ROOT/data/addon-ui.log"
  _dev_all_cleanup() {
    [[ "$cleaned" -eq 1 ]] && return 0
    cleaned=1
    trap - EXIT INT TERM HUP
    echo
    echo "终端结束 → 停止一键开发…"
    _stop_pid_tree "${ui_pid:-}"
    _stop_pid_tree "${addon_pid:-}"
    _stop_pid_tree "${ha_pid:-}"
    sleep 0.8
    _stop_pid_tree "${ui_pid:-}"
    _stop_pid_tree "${addon_pid:-}"
    _stop_pid_tree "${ha_pid:-}"
    kill -9 "${ui_pid:-}" "${addon_pid:-}" "${ha_pid:-}" 2>/dev/null || true
    rm -f "$ADDON_PID_FILE" "$ADDON_UI_PID_FILE" "$PID_FILE"
    echo "已全部停止"
  }
  trap _dev_all_cleanup EXIT INT TERM HUP

  mkdir -p "$(dirname "$ADDON_LOG_FILE")" "$(dirname "$LOG_FILE")"
  : >"$ADDON_LOG_FILE"
  : >"$ui_log"
  : >"$LOG_FILE"

  (
    cd "$ADDON_DIR"
    exec "$py" -m uvicorn app.main:app --host 127.0.0.1 --port "$ADDON_PORT" --reload --app-dir .
  ) >>"$ADDON_LOG_FILE" 2>&1 &
  addon_pid=$!
  echo "$addon_pid" >"$ADDON_PID_FILE"

  (
    cd "$ADDON_WEB_DIR"
    # 代理目标跟 ADDON_PORT 对齐（vite.config 默认 8080）
    export SMARTCENTER_ADDON_PORT="$ADDON_PORT"
    exec npx vite --host 127.0.0.1 --port "$ADDON_UI_PORT"
  ) >>"$ui_log" 2>&1 &
  ui_pid=$!
  echo "$ui_pid" >"$ADDON_UI_PID_FILE"

  (
    exec uv run hass -c "$CONFIG_DIR"
  ) >>"$LOG_FILE" 2>&1 &
  ha_pid=$!
  echo "$ha_pid" >"$PID_FILE"

  sleep 2
  # 开发主入口 = Vite（HMR）；API 同端口也可看构建产物
  open_browser "http://127.0.0.1:${ADDON_UI_PORT}/"
  open_browser "http://127.0.0.1:8123/"
  echo
  echo "就绪（勿关本终端；Ctrl+C 或关终端 = 全停）："
  echo "  工作台 HMR  http://127.0.0.1:${ADDON_UI_PORT}/   ← 改 web/src 即热更"
  echo "  API reload  http://127.0.0.1:${ADDON_PORT}/       ← 改 app/*.py 即热更"
  echo "  HA          http://127.0.0.1:8123/"
  echo "  日志        $ADDON_LOG_FILE · $ui_log · $LOG_FILE"
  echo "----------------------------------------"
  wait
}

cmd_stop_all() {
  echo "停止 Add-on…"
  cmd_addon_stop || true
  echo "停止本机 HA…"
  cmd_stop || true
  echo "一键开发已全部停止"
}

cmd_addon_ui_start() {
  ensure_dirs
  ensure_addon_web_node || return 1
  if is_addon_ui_running; then
    echo "前端已在运行 pid=$(cat "$ADDON_UI_PID_FILE")"
    return 0
  fi
  (
    cd "$ADDON_WEB_DIR"
    nohup npx vite --host 127.0.0.1 --port "$ADDON_UI_PORT" >>"$ROOT/data/addon-ui.log" 2>&1 &
    echo $! >"$ADDON_UI_PID_FILE"
  )
  sleep 0.5
  echo "前端 Vite http://127.0.0.1:${ADDON_UI_PORT}/ （代理 API → :${ADDON_PORT}）"
  open_browser "http://127.0.0.1:${ADDON_UI_PORT}/"
}

cmd_addon_stop() {
  local n=0
  if is_addon_running; then
    kill "$(cat "$ADDON_PID_FILE")" 2>/dev/null || true
    rm -f "$ADDON_PID_FILE"
    echo "后端已停"
    n=1
  else
    rm -f "$ADDON_PID_FILE"
  fi
  if is_addon_ui_running; then
    kill "$(cat "$ADDON_UI_PID_FILE")" 2>/dev/null || true
    rm -f "$ADDON_UI_PID_FILE"
    echo "前端已停"
    n=1
  else
    rm -f "$ADDON_UI_PID_FILE"
  fi
  [[ "$n" -eq 1 ]] || echo "Add-on 未在跑"
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
  if is_addon_running; then
    echo "Add-on 后端: running  pid=$(cat "$ADDON_PID_FILE")  :${ADDON_PORT}"
  else
    echo "Add-on 后端: stopped"
  fi
  if is_addon_ui_running; then
    echo "Add-on 前端: running  pid=$(cat "$ADDON_UI_PID_FILE")  :${ADDON_UI_PORT}"
  else
    echo "Add-on 前端: stopped（全栈时页面由后端同端口提供）"
  fi
  if is_running; then
    echo "本机 HA（可选）: running  pid=$(cat "$PID_FILE")  :8123"
  else
    echo "本机 HA（可选）: stopped  · 生产 HA 在 HAOS，不必起本机"
  fi
  echo "配置: $CONFIG_DIR"
  echo "--- Add-on 日志尾 ---"
  if [[ -f "$ADDON_LOG_FILE" ]]; then tail -n 15 "$ADDON_LOG_FILE"; else echo "(无)"; fi
}

cmd_logs() {
  mkdir -p "$(dirname "$ADDON_LOG_FILE")"
  touch "$ADDON_LOG_FILE"
  echo "跟踪 Add-on 日志（Ctrl+C 返回）: $ADDON_LOG_FILE"
  echo "（本机 HA 日志: $LOG_FILE）"
  trap 'trap - INT; echo; echo "已停止跟踪"' INT
  tail -f "$ADDON_LOG_FILE" || true
  trap - INT
}

cmd_logs_ha() {
  mkdir -p "$(dirname "$LOG_FILE")"
  touch "$LOG_FILE"
  echo "跟踪本机 HA 日志（Ctrl+C 返回）: $LOG_FILE"
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

开发优先本机：Add-on（uvicorn）+ 本机 HA（packages/lobn_office）。
生产才用店内 HAOS；日常不连内网 HAOS（免误伤、免端口/ACL）。

菜单
  启动   Add-on 起停、固件、导出
  开发   Add-on 全栈/前后端；本机 HA :8123
  运维   状态、日志
  环境   Add-on 依赖 · 本机 HA 依赖（uv sync）

一键：all | dev-all（前台，关终端=全停）· 残留清理：stop-all
Add-on：addon | addon-api | addon-ui | addon-ui-build | addon-start/stop | addon-test
本机 HA：dev | start | stop | repair | test | logs-ha
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
  1) Add-on 后台启动（后端 :${ADDON_PORT}）
  2) Add-on 停止（后端+独立前端）
  3) 教室总控固件（ESPHome）
  4) 导出 center.zip
  0) 返回
EOF
    read -r -p "> " c
    case "$c" in
      1) run_action "Add-on 后台" cmd_addon_start ;;
      2) run_action "Add-on 停止" cmd_addon_stop ;;
      3) clear_screen; cmd_esphome_flash || true; pause_back ;;
      4) run_action "导出" cmd_export ;;
      0) return 0 ;;
      *) ;;
    esac
  done
}

menu_dev() {
  while true; do
    clear_screen
    cat <<EOF
SmartCenter · 开发（本机；不连店内 HAOS）
  1) 一键开发 — Add-on+本机HA（前台；关终端即全停）
  2) 强制停残留（一般不必；关终端会自动停）
  —— 分开起 ——
  3) 仅 Add-on 全栈 :${ADDON_PORT}（前台热重载）
  4) 仅后端 / 5) 仅前端 :${ADDON_UI_PORT} / 6) Add-on 单测
  7) 仅本机 HA 前台 :8123
  8) 仅本机 HA 后台
  9) 仅停本机 HA
  0) 返回
EOF
    read -r -p "> " c
    case "$c" in
      1) clear_screen; echo "SmartCenter · 一键开发"; echo "----------------------------------------"; cmd_dev_all || true; pause_back ;;
      2) run_action "强制停残留" cmd_stop_all ;;
      3) clear_screen; echo "SmartCenter · Add-on 全栈"; echo "----------------------------------------"; cmd_addon_dev || true; pause_back ;;
      4) clear_screen; echo "SmartCenter · 仅后端"; echo "----------------------------------------"; cmd_addon_api || true; pause_back ;;
      5) clear_screen; echo "SmartCenter · 仅前端"; echo "----------------------------------------"; cmd_addon_ui || true; pause_back ;;
      6) run_action "Add-on 单测" cmd_addon_test ;;
      7) clear_screen; echo "SmartCenter · 本机 HA"; echo "----------------------------------------"; cmd_dev || true; pause_back ;;
      8) run_action "本机 HA 后台" cmd_start ;;
      9) run_action "停本机 HA" cmd_stop ;;
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
  2) Add-on 日志
  3) 本机 HA 日志（开发用）
  4) 校验 secrets 权限
  5) 帮助
  0) 返回
EOF
    read -r -p "> " c
    case "$c" in
      1) run_action "状态" cmd_status ;;
      2) clear_screen; echo "SmartCenter · Add-on 日志"; echo "----------------------------------------"; cmd_logs; pause_back ;;
      3) clear_screen; echo "SmartCenter · HA 日志"; echo "----------------------------------------"; cmd_logs_ha; pause_back ;;
      4) run_action "校验密钥" cmd_check_secrets ;;
      5) run_action "帮助" cmd_help ;;
      0) return 0 ;;
      *) ;;
    esac
  done
}

menu_env() {
  while true; do
    clear_screen
    cat <<EOF
SmartCenter · 环境
  1) Add-on 依赖（人脸开发）
  2) 本机 HA 依赖（uv sync → homeassistant；开发 packages 用）
  3) 环境检测
  4) lobn_office 单测（不启 HA 进程）
  0) 返回
EOF
    read -r -p "> " c
    case "$c" in
      1) run_action "Add-on 依赖" cmd_addon_repair ;;
      2) run_action "本机 HA 依赖" cmd_repair ;;
      3) run_action "环境检测" cmd_diagnose ;;
      4) run_action "lobn_office 测试" cmd_test ;;
      0) return 0 ;;
      *) ;;
    esac
  done
}

menu() {
  while true; do
    clear_screen
    cat <<EOF
SmartCenter
  生产 HA/Frigate 在 HAOS。本机菜单面向 Add-on 与固件。

  1) 启动
  2) 开发 ← 一键 Add-on+本机HA / 分开起
  3) 运维
  4) 环境
  5) 教室总控固件
  0) 退出
EOF
    read -r -p "> " choice
    case "$choice" in
      1) menu_start ;;
      2) menu_dev ;;
      3) menu_ops ;;
      4) menu_env ;;
      5) clear_screen; cmd_esphome_flash || true; pause_back ;;
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
    logs-ha) cmd_logs_ha ;;
    secrets) cmd_check_secrets ;;
    test) cmd_test ;;
    flash|esphome) cmd_esphome_flash ;;
    all|dev-all) cmd_dev_all ;;
    stop-all) cmd_stop_all ;;
    addon|addon-dev|addon-full) cmd_addon_dev ;;
    addon-api) cmd_addon_api ;;
    addon-ui) cmd_addon_ui ;;
    addon-ui-start) cmd_addon_ui_start ;;
    addon-ui-build) cmd_addon_ui_build ;;
    addon-start) cmd_addon_start ;;
    addon-stop) cmd_addon_stop ;;
    addon-test) cmd_addon_test ;;
    addon-repair) cmd_addon_repair ;;
    help|-h|--help) cmd_help ;;
    *) echo "未知: $cmd"; cmd_help; exit 1 ;;
  esac
}

main "$@"
