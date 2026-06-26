#!/bin/bash
# GigaEvo Memory Module - Full Startup Script

set -e

echo "🚀 GigaEvo Memory Module - Starting..."
echo "========================================"
echo ""

# Configuration
PROJECT_DIR="/Users/glazkov/Development/gigaevo-memory"
API_PORT=8000
UI_PORT=7860
DB_NAME="gigaevo"
DB_USER="gigaevo"
DB_PASSWORD="gigaevo"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Start PostgreSQL
echo "📦 Starting PostgreSQL..."
if [ "$(docker ps -q -f name=postgres-gigaevo)" ]; then
    echo "✅ PostgreSQL already running"
else
    if [ "$(docker ps -aq -f name=postgres-gigaevo)" ]; then
        docker start postgres-gigaevo
        echo "✅ PostgreSQL started"
    else
        docker run -d \
            --name postgres-gigaevo \
            -e POSTGRES_DB=$DB_NAME \
            -e POSTGRES_USER=$DB_USER \
            -e POSTGRES_PASSWORD=$DB_PASSWORD \
            -p 5432:5432 \
            postgres:15-alpine
        echo "✅ PostgreSQL created and started"
    fi
fi

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL..."
sleep 3
for i in {1..30}; do
    if docker exec postgres-gigaevo pg_isready -U $DB_USER > /dev/null 2>&1; then
        echo "✅ PostgreSQL is ready"
        break
    fi
    sleep 1
done

# Start Redis (optional)
echo "📦 Starting Redis..."
if [ "$(docker ps -q -f name=redis-gigaevo)" ]; then
    echo "✅ Redis already running"
else
    if [ "$(docker ps -aq -f name=redis-gigaevo)" ]; then
        docker start redis-gigaevo
        echo "✅ Redis started"
    else
        docker run -d \
            --name redis-gigaevo \
            -p 6379:6379 \
            redis:7-alpine
        echo "✅ Redis created and started"
    fi
fi

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
cd "$PROJECT_DIR"

if [ ! -d "api/.venv" ]; then
    echo "Creating API venv..."
    python3 -m venv api/.venv
fi

if [ ! -d "web_ui/.venv" ]; then
    echo "Creating Web UI venv..."
    python3 -m venv web_ui/.venv
fi

echo "Installing dependencies from workspace..."
uv sync --no-dev

# Run migrations
echo ""
echo "🔄 Running database migrations..."
cd "$PROJECT_DIR/api"
if [ -f "alembic.ini" ]; then
    uv run alembic upgrade head
    echo "✅ Migrations completed"
else
    echo "⚠️  No migrations found, skipping"
fi

# Start API
echo ""
echo "🌐 Starting API server..."
cd "$PROJECT_DIR/api"
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port $API_PORT > ../logs/api.log 2>&1 &
API_PID=$!
echo "✅ API started (PID: $API_PID)"

# Wait for API to be ready
echo "⏳ Waiting for API..."
sleep 3
for i in {1..30}; do
    if curl -s http://localhost:$API_PORT/health > /dev/null 2>&1; then
        echo "✅ API is ready"
        break
    fi
    sleep 1
done

# Start Web UI
echo ""
echo "🎨 Starting Web UI..."
cd "$PROJECT_DIR/web_ui"
export MEMORY_API_URL=http://localhost:$API_PORT
uv run python -m app.main > ../logs/ui.log 2>&1 &
UI_PID=$!
echo "✅ Web UI started (PID: $UI_PID)"

# Summary
echo ""
echo "========================================"
echo "✅ GigaEvo Memory Module is running!"
echo "========================================"
echo ""
echo "📊 Services:"
echo "  PostgreSQL: localhost:5432 (docker: postgres-gigaevo)"
echo "  Redis:      localhost:6379 (docker: redis-gigaevo)"
echo "  API:        http://localhost:$API_PORT"
echo "  Web UI:     http://localhost:$UI_PORT"
echo "  API Docs:   http://localhost:$API_PORT/docs"
echo ""
echo "📝 Logs:"
echo "  API: $PROJECT_DIR/logs/api.log"
echo "  UI:  $PROJECT_DIR/logs/ui.log"
echo ""
echo "🛑 To stop:"
echo "  kill $API_PID $UI_PID"
echo "  docker stop postgres-gigaevo redis-gigaevo"
echo ""
echo "🔍 Health check:"
echo "  curl http://localhost:$API_PORT/health"
echo ""

# Open browser
echo "🌐 Opening Web UI in browser..."
sleep 2
open "http://localhost:$UI_PORT" 2>/dev/null || echo "Please open http://localhost:$UI_PORT manually"

# Keep script running
echo ""
echo "Press Ctrl+C to stop all services..."
trap "echo ''; echo '🛑 Stopping services...'; kill $API_PID $UI_PID 2>/dev/null; docker stop postgres-gigaevo redis-gigaevo 2>/dev/null; echo '✅ Services stopped'; exit 0" INT TERM

# Wait
wait
