#!/bin/bash
# PanWatch 盯盘侠 - 重启脚本
# 使用方法: ./restart.sh
# 说明: 此脚本会停止、删除旧容器，然后使用最新镜像重新创建容器

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
echo "[STEP 2] 删除旧容器..."
echo "--------------------------------------"
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[INFO] 正在删除旧容器 ${CONTAINER_NAME}..."
    docker rm ${CONTAINER_NAME}
    echo "[SUCCESS] 旧容器已删除，将使用最新镜像重新创建"
else
    echo "[INFO] 容器不存在，无需删除"
fi

echo ""
echo "[STEP 3] 启动服务..."
echo "--------------------------------------"
/root/PanWatch/scripts/start.sh
