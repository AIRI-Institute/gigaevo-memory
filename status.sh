#!/bin/bash
# GigaEvo Memory Module - Status Check

echo "🔍 GigaEvo Memory Module - Status"
echo "=================================="
echo ""

# Check PostgreSQL
echo "📦 PostgreSQL:"
if docker ps -q -f name=postgres-gigaevo > /dev/null 2>&1; then
    echo "  Status: ✅ Running"
    docker ps -f name=postgres-gigaevo --format "  Container: {{.Names}} ({{.Status}})"
else
    echo "  Status: ❌ Not running"
fi
echo ""

# Check Redis
echo "📦 Redis:"
if docker ps -q -f name=redis-gigaevo > /dev/null 2>&1; then
    echo "  Status: ✅ Running"
    docker ps -f name=redis-gigaevo --format "  Container: {{.Names}} ({{.Status}})"
else
    echo "  Status: ❌ Not running"
fi
echo ""

# Check API
echo "🌐 API (port 8000):"
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "  Status: ✅ Running"
    HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null)
    echo "  Health: $HEALTH"
    echo "  Docs:   http://localhost:8000/docs"
else
    echo "  Status: ❌ Not running"
fi
echo ""

# Check Web UI
echo "🎨 Web UI (port 7860):"
if curl -s http://localhost:7860 > /dev/null 2>&1; then
    echo "  Status: ✅ Running"
    echo "  URL:    http://localhost:7860"
else
    echo "  Status: ❌ Not running"
fi
echo ""

# Summary
echo "=================================="
echo "Run './start.sh' to start all services"
echo "Run './stop.sh' to stop all services"
