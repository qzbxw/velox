#!/bin/bash
set -e

echo "🚀 Deploying Velox..."

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Pull latest changes
echo -e "${BLUE}📥 Pulling latest changes...${NC}"
git pull origin main

# Stop containers
echo -e "${BLUE}🛑 Stopping containers...${NC}"
docker compose down

# Clean up Docker garbage (free space)
echo -e "${BLUE}🧹 Cleaning Docker cache and old images...${NC}"
docker image prune -af
echo -e "${GREEN}✅ Docker cleaned!${NC}"

# Rebuild images
echo -e "${BLUE}🔨 Rebuilding images...${NC}"
docker compose build

# Start containers
echo -e "${BLUE}🚀 Starting containers...${NC}"
docker compose up -d

# Show logs
echo -e "${BLUE}📋 Checking logs...${NC}"
sleep 2
docker compose logs --tail=50

echo -e "${GREEN}✅ Deploy complete!${NC}"
echo -e "${BLUE}Run 'docker compose logs -f' to follow logs${NC}"
