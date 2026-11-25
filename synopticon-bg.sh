#!/usr/bin/env zsh
# Synopticon 后台常驻 + 防休眠（caffeinate）管理脚本
# 用法：
#   ./synopticon-bg.sh start [--lan]   # 后台启动 Web 服务（默认 127.0.0.1:8686；加 --lan 监听 0.0.0.0:8686）
#   ./synopticon-bg.sh stop            # 停止后台 Web 服务
#   ./synopticon-bg.sh restart [--lan] # 重启服务
#   ./synopticon-bg.sh status          # 查看运行状态与当前人脸提取进度
#   ./synopticon-bg.sh logs            # 实时查看服务日志

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

PID_FILE="$APP_DIR/data/synopticon-web.pid"
LOG_FILE="$APP_DIR/data/synopticon-web.log"
PORT="${SYNOPTICON_PORT:-8686}"
export SYNOPTICON_CONFIG="$APP_DIR/data/config.toml"

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

cmd_start() {
  local host="${SYNOPTICON_HOST:-127.0.0.1}"
  if [[ "${1:-}" == "--lan" ]]; then
    host="0.0.0.0"
  fi

  if is_running; then
    echo "Synopticon Web 已在后台运行（PID $(cat "$PID_FILE")），地址：http://127.0.0.1:${PORT}"
    return 0
  fi

  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[错误] 端口 ${PORT} 已被其他进程占用："
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
    exit 1
  fi

  chmod 600 "$SYNOPTICON_CONFIG" 2>/dev/null || true

  # 使用 caffeinate -i 阻止空闲休眠（允许显示器息屏，适合 Mac mini 长时间挂机跑提取）
  nohup /usr/bin/caffeinate -i \
    "$APP_DIR/.venv/bin/synopticon" web --host "$host" --port "$PORT" \
    >>"$LOG_FILE" 2>&1 </dev/null &
  local pid=$!
  echo "$pid" >"$PID_FILE"

  for _ in {1..40}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[错误] 服务启动失败，最近日志："
      tail -n 30 "$LOG_FILE"
      rm -f "$PID_FILE"
      exit 1
    fi
    if curl -sS -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/login" 2>/dev/null; then
      echo "Synopticon Web 已在后台启动（防休眠已开启，PID ${pid}）"
      echo "  本机访问 : http://127.0.0.1:${PORT}"
      if [[ "$host" == "0.0.0.0" ]]; then
        local lan_ip
        lan_ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<本机局域网IP>")"
        echo "  局域网访问: http://${lan_ip}:${PORT}"
      fi
      echo "  日志文件 : $LOG_FILE"
      return 0
    fi
    sleep 0.25
  done

  echo "[警告] 服务进程已启动（PID ${pid}），但尚未在 10 秒内就绪，请检查日志：$LOG_FILE"
}

cmd_stop() {
  if ! is_running; then
    echo "Synopticon Web 未在后台运行。"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  # 优先通知子进程（synopticon web）优雅退出，caffeinate 会随之退出
  pkill -TERM -P "$pid" 2>/dev/null || true
  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    pkill -KILL -P "$pid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  echo "Synopticon Web 已停止。"
}

cmd_status() {
  if is_running; then
    local pid
    pid="$(cat "$PID_FILE")"
    echo "状态 : 运行中（防休眠 caffeinate PID ${pid}）"
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 5 || true
  else
    echo "状态 : 未运行"
  fi
  echo ""
  echo "数据库当前提取进度："
  "$APP_DIR/.venv/bin/python" -c "
from synopticon.config import load_settings
from synopticon.db import store
from synopticon.web.stats import gather_stats
s = load_settings()
conn = store.connect(s)
st = gather_stats(conn, s)
ext = st['extract']
tot = sum(v['synced'] for v in st['photos'].values())
rem = ext['eligible'] - (ext['processed'] or 0)
pct = (ext['coverage'] or 0) * 100
print(f\"  已同步照片 : {tot:,}\")
print(f\"  可提取照片 : {ext['eligible']:,}\")
print(f\"  已提取完成 : {ext['processed']:,} ({pct:.2f}%) | 剩余 : {rem:,}\")
print(f\"  已检出人脸 : {st['faces']:,} | 特征向量 : {st['embeddings']:,}\")
print(f\"  管线版本   : {ext['pipeline_version']}\")
conn.close()
"
}

cmd_logs() {
  touch "$LOG_FILE"
  tail -n 50 -f "$LOG_FILE"
}

case "${1:-status}" in
  start)   cmd_start "${2:-}" ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start "${2:-}" ;;
  status)  cmd_status ;;
  logs)    cmd_logs ;;
  *)
    echo "用法: $0 {start [--lan]|stop|restart [--lan]|status|logs}"
    exit 2
    ;;
esac
