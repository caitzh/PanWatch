#!/bin/bash
# PanWatch 盯盘侠 - 停止脚本
# 使用方法: ./stop.sh

CONTAINER_NAME="panwatch"

echo "======================================"
echo "   PanWatch 盯盘侠 - 停止"
echo "======================================"

# ========== 停止 PanWatch ==========
echo ""
echo "[STEP 1] 停止 PanWatch 盯盘侠..."
echo "--------------------------------------"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[INFO] 正在停止容器 ${CONTAINER_NAME}..."
    docker stop ${CONTAINER_NAME}
    echo "[SUCCESS] PanWatch 盯盘侠已停止"
else
    echo "[INFO] 容器 ${CONTAINER_NAME} 未在运行"
fi

echo ""
echo "======================================"
echo "[SUCCESS] 服务已停止"
echo "======================================"
