#!/bin/bash
# 无网机器启动代理：SOCKS5 (1080) + HTTP (8080)，一窗双开
set -e

SESSION="virtio-proxy"
# === 修改为你的共享文件系统路径 ===
BRIDGE_DIR="/path/to/shared/.bridge"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 如果 tmux 会话已存在，先杀掉重建
tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION"

# 创建 tmux 会话，上窗 SOCKS5，下窗 HTTP 桥接
tmux new-session -d -s "$SESSION" \
  "echo '[SOCKS5] virtio-bridge socks on :1080'; echo '---'; virtio-bridge socks --listen 127.0.0.1:1080 --bridge-dir '$BRIDGE_DIR' --verbose"
tmux split-window -t "$SESSION" -v \
  "sleep 2; echo '[HTTP] http→socks bridge on :8080'; echo '---'; python3 '$SCRIPT_DIR/http-socks-bridge.py'"

echo ""
echo "  ✓ SOCKS5 代理: 127.0.0.1:1080  (curl / pip / git / Python)"
echo "  ✓ HTTP  代理: 127.0.0.1:8080  (wget / apt)"
echo ""
echo "配置代理环境变量 (复制粘贴执行):"
echo ""
echo "  unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY"
echo "  export http_proxy=http://127.0.0.1:8080"
echo "  export https_proxy=http://127.0.0.1:8080"
echo "  export HTTP_PROXY=http://127.0.0.1:8080"
echo "  export HTTPS_PROXY=http://127.0.0.1:8080"
echo "  export ALL_PROXY=socks5://127.0.0.1:1080"
echo "  export all_proxy=socks5://127.0.0.1:1080"
echo ""
echo "验证:"
echo "  curl -O www.baidu.com          # 走 HTTP  代理 8080"
echo "  wget www.baidu.com             # 走 HTTP  代理 8080"
echo "  curl --socks5 127.0.0.1:1080 https://www.baidu.com  # 走 SOCKS5 1080"
echo ""
echo "tmux 会话: $SESSION"
echo "查看日志: tmux attach -t $SESSION"
echo "退出 tmux: Ctrl+B 然后按 D"
