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

脚本会输出环境变量配置。

### 4. （推荐）启用全局透明代理

环境变量只对 curl/wget/pip/git 这类"认识代理"的程序生效。想做到**所有程序自动走代理**（跟直连外网一样），需要 proxychains + LD_PRELOAD。总共三步：

#### 4a. 编译 proxychains-ng（如果还没编过）

```bash
cd /path/to/virtio-bridge/proxychains-ng
./configure
make
# 编译产物：libproxychains4.so（核心）和 proxychains4（测试用）
```

#### 4b. 创建 /etc/proxychains.conf

```bash
sudo tee /etc/proxychains.conf << 'EOF'
strict_chain
quiet_mode
proxy_dns
remote_dns_subnet 224
tcp_read_time_out 15000
tcp_connect_time_out 8000

# 排除本地回环（防止 LD_PRELOAD 下自身被代理，死循环）
localnet 127.0.0.0/255.0.0.0
# 排除内网地址
localnet 10.0.0.0/255.0.0.0
localnet 172.16.0.0/255.240.0.0
localnet 192.168.0.0/255.255.0.0

[ProxyList]
socks5 127.0.0.1 1080
EOF
```

核心要点：`localnet 127.0.0.0/8` 确保 virtio-bridge 自身的连接不会被代理，否则会死循环。

#### 4c. 在 ~/.zshrc 末尾加入开关函数

注意把 `PC_LIB` 路径改成你自己的：

```bash
filemaho() {
    # 环境变量（兼容标准程序）
    export http_proxy=http://127.0.0.1:8080
    export https_proxy=http://127.0.0.1:8080
    export HTTP_PROXY=http://127.0.0.1:8080
    export HTTPS_PROXY=http://127.0.0.1:8080
    export ALL_PROXY=socks5://127.0.0.1:1080
    export all_proxy=socks5://127.0.0.1:1080

    # 全局透明代理（LD_PRELOAD 拦截所有 TCP 连接）
    PC_LIB="/path/to/virtio-bridge/proxychains-ng/libproxychains4.so"
    export PROXYCHAINS_CONF_FILE="/etc/proxychains.conf"
    export PROXYCHAINS_QUIET_MODE=1
    export LD_PRELOAD="$PC_LIB${LD_PRELOAD:+:$LD_PRELOAD}"

    echo "代理已开启（环境变量 + 全局透明）"
}

unfilemaho() {
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
    unset LD_PRELOAD PROXYCHAINS_CONF_FILE PROXYCHAINS_QUIET_MODE
    echo "代理已关闭"
}
```

写入后 `source ~/.zshrc` 生效。

### 5. 验证

```bash
filemaho                        # 开代理
wget www.baidu.com              # HTTP 代理
curl -O www.baidu.com           # HTTP 代理
pip install requests            # SOCKS5

# 关键测试：裸 socket 不设任何环境变量，也能连通 → 全局透明生效
python3 -c "import socket; socket.create_connection(('www.baidu.com',80))"

unfilemaho                      # 关代理
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
