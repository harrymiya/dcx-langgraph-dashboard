#!/bin/sh
# DEV-01 外部 secret 注入示例。全部为合成占位值，不是真实凭据。
# 用法： source ./secret-injection.example.sh  (仅本地内存，不落盘)
export MAPP_SANDBOX_TOKEN="synthetic-dev-token-0000"
export WISH_SANDBOX_TOKEN="synthetic-test-token-0000"
export MER_SANDBOX_TOKEN="synthetic-mer-token-0000"
echo "synthetic sandbox tokens injected (memory only)"
