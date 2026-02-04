#!/bin/bash
# PanWatch 盯盘侠 - 重启脚本
# 使用方法: ./restart.sh

CONTAINER_NAME="panwatch"

echo "======================================"
echo "   PanWatch 盯盘侠 - 重启"
echo "======================================"

echo ""
echo "[STEP 1] 停止服务..."
echo "--------------------------------------"
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[INFO] 正在停止容器 ${CONTAINER_NAME}..."
    docker stop ${CONTAINER_NAME}
    echo "[SUCCESS] 服务已停止"
else
    echo "[INFO] 容器未在运行"
fi

echo ""
echo "[STEP 2] 启动服务..."
echo "--------------------------------------"
./start.sh
