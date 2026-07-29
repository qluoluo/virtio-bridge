#!/bin/bash
# 本机（有网）启动 tcp-relay 服务端

SESSION="virtio-relay"

# 从配置文件读取 BRIDGE_DIR（不提交到 git）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/bridge-dir.conf" ]; then
  source "$SCRIPT_DIR/bridge-dir.conf"
else
  BRIDGE_DIR="/path/to/shared/.bridge"
fi

# 如果 tmux 会话已存在，先杀掉重建
tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION"

tmux new-session -d -s "$SESSION" \
  "virtio-bridge tcp-relay \
    --bridge-dir '$BRIDGE_DIR' \
    --allow-host '*' \
    --verbose"

echo "tcp-relay 已启动，tmux 会话: $SESSION"
echo "查看日志: tmux attach -t $SESSION"
echo "退出 tmux: Ctrl+B 然后按 D"
