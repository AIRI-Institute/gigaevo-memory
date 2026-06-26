#!/bin/bash
# GigaEvo Memory Module - Stop Script

echo "🛑 Stopping GigaEvo Memory Module..."
echo "======================================"
echo ""

# Stop API
echo "Stopping API..."
pkill -f "uvicorn app.main:app" && echo "✅ API stopped" || echo "⚠️  API not running"

# Stop Web UI
echo "Stopping Web UI..."
pkill -f "python -m app.main" && echo "✅ Web UI stopped" || echo "⚠️  Web UI not running"

# Stop Docker containers
echo "Stopping Docker containers..."
docker stop postgres-gigaevo 2>/dev/null && echo "✅ PostgreSQL stopped" || echo "⚠️  PostgreSQL not running"
docker stop redis-gigaevo 2>/dev/null && echo "✅ Redis stopped" || echo "⚠️  Redis not running"

echo ""
echo "✅ All services stopped"
