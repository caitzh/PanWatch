#!/bin/bash
# PanWatch 盯盘侠 - 启动脚本
# 使用方法: ./start.sh

# ========== 配置 ==========
CONTAINER_NAME="panwatch"
IMAGE_NAME="panwatch"
PORT="8000"
DATA_DIR="/root/PanWatch/data"

echo "======================================"
echo "   PanWatch 盯盘侠 - 启动"
echo "======================================"

# ========== 启动 PanWatch ==========
echo ""
echo "[STEP 1] 启动 PanWatch 盯盘侠..."
echo "--------------------------------------"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "[INFO] 容器 ${CONTAINER_NAME} 已在运行中"
    else
        echo "[INFO] 容器存在但未运行，正在启动..."
        docker start ${CONTAINER_NAME}
    fi
else
    echo "[INFO] 首次启动，正在创建容器..."
    docker run -d \
        --name ${CONTAINER_NAME} \
        -p ${PORT}:8000 \
        -v ${DATA_DIR}:/app/data \
        -e PYTHONUNBUFFERED=1 \
        -e TZ=Asia/Shanghai \
        --restart unless-stopped \
        ${IMAGE_NAME}
fi

# 等待服务启动
sleep 3

# ========== 检查启动状态 ==========
echo ""
echo "======================================"
echo "   启动状态"
echo "======================================"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[SUCCESS] PanWatch 盯盘侠启动成功!"
    echo ""
    echo "访问地址:"
    echo "  - PanWatch: http://localhost:${PORT}"
    echo ""
    echo "查看日志:"
    echo "  - docker logs -f ${CONTAINER_NAME}"
else
    echo "[ERROR] PanWatch 启动失败，请检查日志:"
    docker logs ${CONTAINER_NAME}
    exit 1
fi
