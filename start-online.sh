#!/bin/bash
# 本机（有网）启动 tcp-relay 服务端

SESSION="virtio-relay"

# === 修改为你的共享文件系统路径 ===
BRIDGE_DIR="/path/to/shared/.bridge"

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
