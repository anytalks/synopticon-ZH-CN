#!/usr/bin/env zsh
# 双击启动 Synopticon 中文 Web 服务（带 macOS 防休眠 caffeinate）
# 用法：
#   双击运行：默认监听 http://127.0.0.1:8686（仅本机访问）
#   终端传入 --lan：监听 http://0.0.0.0:8686（允许局域网设备访问）

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

HOST="${SYNOPTICON_HOST:-127.0.0.1}"
PORT="${SYNOPTICON_PORT:-8686}"
if [[ "${1:-}" == "--lan" ]]; then
  HOST="0.0.0.0"
fi

export SYNOPTICON_CONFIG="$APP_DIR/data/config.toml"

if [[ ! -x "$APP_DIR/.venv/bin/synopticon" ]]; then
  echo "[错误] 未找到虚拟环境：$APP_DIR/.venv/bin/synopticon"
  echo "请先在该目录运行：uv sync --frozen --no-dev --python 3.11 --extra cpu --extra review --extra faiss"
  read -r "?按回车键退出..."
  exit 1
fi

chmod 600 "$SYNOPTICON_CONFIG" 2>/dev/null || true

URL="http://127.0.0.1:${PORT}"

# 若端口已在运行，则直接打开浏览器，避免端口冲突报错
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Synopticon Web 服务已在端口 ${PORT} 运行，正在打开浏览器：${URL}"
  open "$URL"
  exit 0
fi

echo "============================================================"
echo "  Synopticon 中文 Web 服务（Apple Silicon CoreML+CPU 加速）"
echo "  工作目录 : $APP_DIR"
echo "  配置文件 : $SYNOPTICON_CONFIG"
echo "  监听地址 : http://${HOST}:${PORT}"
if [[ "$HOST" == "0.0.0.0" ]]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<本机局域网IP>")"
  echo "  局域网访问: http://${LAN_IP}:${PORT}"
fi
echo "  防休眠   : 已启用 caffeinate -i（允许息屏，阻止系统空闲休眠）"
echo "  停止服务 : 按 Ctrl+C 或直接关闭此终端窗口"
echo "============================================================"
echo ""

# 等待服务就绪后自动在默认浏览器中打开首页
(
  for _ in {1..40}; do
    if curl -sS -o /dev/null --max-time 1 "${URL}/login" 2>/dev/null; then
      open "$URL"
      break
    fi
    sleep 0.3
  done
) &

exec /usr/bin/caffeinate -i "$APP_DIR/.venv/bin/synopticon" web --host "$HOST" --port "$PORT"
