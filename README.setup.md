# virtio-bridge：通过共享文件系统给无网机器上网

**一句话**：两台机器挂载同一文件系统 → 一台有网当 relay，一台无网跑代理 → 无网机器获得互联网访问。

> 基于 [virtio-bridge](https://github.com/sounosuke/virtio-bridge) v0.7.0，已修复 `--allow-host "*"` 通配符支持。

## 文件说明

| 文件 | 用途 | 在哪台跑 |
|------|------|----------|
| `start-online.sh` | 启动 tcp-relay 服务端 | **有网的机器** |
| `start-offline.sh` | 启动 SOCKS5 + HTTP 双代理 | **无网的机器** |
| `http-socks-bridge.py` | HTTP→SOCKS5 桥接（脚本自动调用） | 无需手动运行 |

## 快速开始

### 1. 安装（两台都执行）

```bash
cd /path/to/network/virtio-bridge
pip install -e .
pip install PySocks
```

### 2. 有网机器 — 启动 relay

```bash
bash start-online.sh
```

### 3. 无网机器 — 启动代理

```bash
bash start-offline.sh
```

脚本会输出环境变量配置，复制粘贴执行即可。

### 4. 验证

```bash
wget www.baidu.com          # HTTP 代理 :8080
curl -O www.baidu.com       # HTTP 代理 :8080
pip install requests        # SOCKS5 :1080
```

## 端口说明

| 端口 | 协议 | 适用工具 |
|------|------|----------|
| 1080 | SOCKS5 | curl --socks5 / pip / git / Python / SSH |
| 8080 | HTTP 代理 | wget / curl / 不支持 SOCKS5 的工具 |

## 修改点

相对于上游 virtio-bridge，仅修改了一处：
- `virtio_bridge/security.py`：`is_host_allowed()` 增加 `*` 通配符支持，允许转发到任意互联网主机。

## 如果换了共享目录路径

修改两个 `start-*.sh` 中的 `BRIDGE_DIR` 变量即可。
