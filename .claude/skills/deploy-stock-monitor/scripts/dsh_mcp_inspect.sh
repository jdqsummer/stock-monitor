#!/bin/sh
# 查看 dsh-mcp-client 包的入口与依赖，确认如何在其顶层 import 下驱动 MCP client。
ls /app/node_modules/@deepseek-ai/ 2>/dev/null | grep dsh-mcp-client
echo "--- package.json main/exports/deps ---"
cat /app/node_modules/@deepseek-ai/dsh-mcp-client/package.json 2>/dev/null | grep -E '"main"|"exports"|"module"|"types"' | head
echo "--- files ---"
ls /app/node_modules/@deepseek-ai/dsh-mcp-client/ 2>/dev/null | head
echo "--- sdk present in pnpm store? ---"
find /app/node_modules/.pnpm -maxdepth 1 -name "@modelcontextprotocol+sdk@*" 2>/dev/null | head -3
