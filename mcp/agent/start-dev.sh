#!/bin/bash

# Phantom Next.js Agent Development Startup Script

echo "🚀 Starting Phantom Next.js Agent (Development Mode)"
echo ""

# Check if .env.local exists
if [ ! -f ".env.local" ]; then
    echo "⚠️  .env.local not found!"
    echo "   Creating from .env.local.example..."
    cp .env.local.example .env.local
    echo "   ✅ Created .env.local"
    echo ""
    echo "   📝 Please edit .env.local and add your GEMINI_API_KEY"
    echo "   Then run this script again."
    exit 1
fi

# Check if GEMINI_API_KEY is set (or GOOGLE_APPLICATION_CREDENTIALS)
# Allow local UI-only testing without keys unless REQUIRE_LLM_KEY=1
if ! grep -q "GEMINI_API_KEY=" .env.local && ! grep -q "GOOGLE_APPLICATION_CREDENTIALS=" .env.local; then
    if [ "${REQUIRE_LLM_KEY}" = "1" ]; then
        echo "⚠️  GEMINI_API_KEY not configured in .env.local"
        echo "   Please add your Gemini API key to .env.local"
        exit 1
    else
        echo "⚠️  No LLM credentials configured; continuing for UI-only testing."
    fi
fi

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
    echo "   ✅ Dependencies installed"
    echo ""
fi

# Check if MCP server is running
echo "🔍 Checking MCP server connection..."
MCP_URL=$(grep MCP_URL .env.local | cut -d '=' -f2)
MCP_URL=${MCP_URL:-http://localhost:8080/api/v1/stream/mcp}

# Extract just the host and port for connectivity check
MCP_HOST=$(echo $MCP_URL | sed -E 's|http://([^:/]+).*|\1|')
MCP_PORT=$(echo $MCP_URL | sed -E 's|.*:([0-9]+)/.*|\1|')

if command -v nc &> /dev/null; then
    if nc -z $MCP_HOST $MCP_PORT 2>/dev/null; then
        echo "   ✅ MCP server is accessible at $MCP_URL"
    else
        echo "   ⚠️  Cannot reach MCP server at $MCP_URL"
        echo "   Make sure the MCP server is running:"
        echo "   docker-compose up phantom-mcp"
    fi
else
    echo "   ⚠️  'nc' command not found, skipping connectivity check"
fi

echo ""
echo "🎯 Starting Next.js development server..."
echo "   URL: http://localhost:3000"
echo "   MCP: $MCP_URL"
echo ""
echo "   Press Ctrl+C to stop"
echo ""

npm run dev
