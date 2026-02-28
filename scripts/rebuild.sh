#!/bin/bash
# PanWatch 盯盘侠 - 重新构建并部署
# 使用方法: ./rebuild.sh [version]
# 说明: 构建前端 + Docker镜像，然后重启服务

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 默认值
VERSION=${1:-"latest"}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${GREEN}======================================"
echo -e "   PanWatch 盯盘侠 - 重新构建部署"
echo -e "======================================${NC}"
echo -e "版本: ${YELLOW}${VERSION}${NC}"
echo ""

# Step 1: 构建 Docker 镜像
echo -e "${GREEN}[STEP 1] 构建 Docker 镜像...${NC}"
echo "--------------------------------------"
cd "$PROJECT_DIR"

docker build --platform linux/amd64 -t panwatch:${VERSION} .

if [ "$VERSION" != "latest" ]; then
    docker tag panwatch:${VERSION} panwatch:latest
fi

echo -e "${GREEN}✅ 镜像构建完成${NC}"
echo ""

# Step 2: 重启服务
echo -e "${GREEN}[STEP 2] 重启服务...${NC}"
echo "--------------------------------------"
cd "$SCRIPT_DIR"
./restart.sh

echo ""
echo -e "${GREEN}🎉 部署完成！${NC}"
