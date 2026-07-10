#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# AgentGRIT 2.0 - Mac Quick Start
# For Apple Silicon Macs
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║            AgentGRIT 2.0 - Mac Quick Start                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: Run this from the AgentGRIT directory${NC}"
    exit 1
fi

# Step 1: Check Python
echo -e "${YELLOW}[1/5] Checking Python...${NC}"
if command -v python3.11 &> /dev/null; then
    PYTHON=python3.11
elif command -v python3 &> /dev/null; then
    PYTHON=python3
else
    echo -e "${RED}Python 3.11+ required. Install with: brew install python@3.11${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Found $PYTHON${NC}"

# Step 2: Create venv if needed
echo -e "${YELLOW}[2/5] Setting up virtual environment...${NC}"
if [ ! -d "venv" ]; then
    $PYTHON -m venv venv
    echo -e "${GREEN}✓ Created venv${NC}"
else
    echo -e "${GREEN}✓ venv exists${NC}"
fi
source venv/bin/activate

# Step 3: Install dependencies
echo -e "${YELLOW}[3/5] Installing dependencies...${NC}"
pip install --upgrade pip -q
pip install -e . -q 2>/dev/null || pip install \
    pydantic pydantic-settings python-dotenv \
    fastapi uvicorn httpx \
    aiogram \
    aiosqlite sqlalchemy \
    redis \
    anthropic openai \
    aiofiles rich structlog tenacity \
    -q
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Step 4: Check Ollama
echo -e "${YELLOW}[4/5] Checking Ollama...${NC}"
if command -v ollama &> /dev/null; then
    echo -e "${GREEN}✓ Ollama installed${NC}"
    
    # Check if Ollama is running
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Ollama is running${NC}"
    else
        echo -e "${YELLOW}Starting Ollama...${NC}"
        ollama serve &>/dev/null &
        sleep 2
    fi
    
    # Check for model
    if ollama list | grep -q "qwen3-coder"; then
        echo -e "${GREEN}✓ qwen3-coder model available${NC}"
    else
        echo -e "${YELLOW}Pulling qwen3-coder:30b (this may take a while)...${NC}"
        ollama pull qwen3-coder:30b
    fi
else
    echo -e "${YELLOW}! Ollama not installed. Install from: https://ollama.ai${NC}"
    echo -e "${YELLOW}  AgentGRIT will use cloud LLMs only${NC}"
fi

# Step 5: Check .env
echo -e "${YELLOW}[5/5] Checking configuration...${NC}"
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${YELLOW}! Created .env from template - please edit it${NC}"
    echo ""
    echo -e "${CYAN}Required: Add at least one of these to .env:${NC}"
    echo "  PPLX_API_KEY=pplx-xxx     (Perplexity - for research)"
    echo "  ANTHROPIC_API_KEY=sk-ant- (Claude - for complex tasks)"
    echo ""
    echo -e "${CYAN}Optional:${NC}"
    echo "  TELEGRAM_BOT_TOKEN=       (Get from @BotFather)"
    echo "  TELEGRAM_ADMIN_IDS=       (Your Telegram user ID)"
    echo ""
    echo -e "${YELLOW}Edit .env and run this script again${NC}"
    exit 0
else
    echo -e "${GREEN}✓ .env exists${NC}"
fi

# Create data directories
mkdir -p data logs

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Ready to start!                           ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Start options:"
echo ""
echo -e "  ${CYAN}./start.sh${NC}                    Full system (API + Telegram)"
echo -e "  ${CYAN}./start.sh --cli${NC}              Interactive CLI mode"
echo -e "  ${CYAN}./start.sh --api-only${NC}         API server only"
echo ""
echo -e "Or manually:"
echo -e "  ${CYAN}source venv/bin/activate${NC}"
echo -e "  ${CYAN}python -m src.main --cli${NC}"
echo ""
