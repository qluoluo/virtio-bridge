#!/bin/bash
# 测试代理连通性：对比其他网站 vs DeepSeek
# 在 H100 上运行

echo "=== Test 1: httpbin.org (should work) ==="
curl --socks5 127.0.0.1:1080 -s -o /dev/null -w "HTTP %{http_code}, time %{time_total}s\n" https://httpbin.org/get

echo "=== Test 2: api.deepseek.com (check if fails) ==="
curl --socks5 127.0.0.1:1080 -s -o /dev/null -w "HTTP %{http_code}, time %{time_total}s\n" https://api.deepseek.com/v1/models

echo ""
echo "If Test 1 returns 200 and Test 2 fails, the issue is specific to DeepSeek."
