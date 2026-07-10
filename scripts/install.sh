#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# AgentGRIT 2.0 - Installation Script
# Run: curl -fsSL https://raw.githubusercontent.com/you/agentgrit/main/install.sh | bash
# Or:  ./install.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Banner
echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              AgentGRIT 2.0 - Installation                    ║"
echo "║         Self-governing AI agent orchestration                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Python version
echo -e "${YELLOW}Checking Python version...${NC}"
if command -v python3.11 &> /dev/null; then
    PYTHON=python3.11
elif command -v python3 &> /dev/null; then
    PYTHON=python3
    version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [[ $(echo "$version < 3.11" | bc -l) -eq 1 ]]; then
        echo -e "${RED}Error: Python 3.11+ required. Found: $version${NC}"
        exit 1
    fi
else
    echo -e "${RED}Error: Python 3 not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Using $PYTHON${NC}"

# Create directory
INSTALL_DIR="${AGENTGRIT_DIR:-$HOME/AgentGRIT}"
echo -e "${YELLOW}Installing to: $INSTALL_DIR${NC}"

if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Directory exists. Backing up...${NC}"
    mv "$INSTALL_DIR" "${INSTALL_DIR}.backup.$(date +%Y%m%d%H%M%S)"
fi

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
$PYTHON -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel > /dev/null

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install \
    pydantic pydantic-settings python-dotenv \
    fastapi uvicorn httpx \
    aiogram \
    aiosqlite sqlalchemy \
    redis \
    anthropic openai \
    aiofiles rich structlog tenacity cryptography \
    > /dev/null

echo -e "${GREEN}✓ Dependencies installed${NC}"

# Create directory structure
echo -e "${YELLOW}Creating project structure...${NC}"
mkdir -p src/{bot,governance,execution,context,api,agents}
mkdir -p bylaws/templates
mkdir -p tests scripts data logs

# Create .env file if not exists
if [ ! -f .env ]; then
    cat > .env << 'EOF'
# AgentGRIT Configuration
# Fill in your values below

# Required: At least one AI backend
ANTHROPIC_API_KEY=

# Optional: Ollama fallback (set to true to enable)
OLLAMA_ENABLED=false
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-coder:30b

# Telegram Bot (get from @BotFather)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_IDS=

# Server
API_PORT=8000
LOG_LEVEL=INFO
EOF
    echo -e "${GREEN}✓ Created .env file (edit with your API keys)${NC}"
fi

# Create quick start script
cat > start.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
python -m src.main
EOF
chmod +x start.sh

# Summary
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Installation Complete!                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Installation directory: ${CYAN}$INSTALL_DIR${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Edit .env file with your API keys:"
echo "   ${CYAN}cd $INSTALL_DIR && nano .env${NC}"
echo ""
echo "2. Add your Anthropic API key:"
echo "   ${CYAN}ANTHROPIC_API_KEY=sk-ant-...${NC}"
echo ""
echo "3. (Optional) Set up Telegram bot:"
echo "   - Message @BotFather on Telegram"
echo "   - Create new bot, get token"
echo "   - Add token to TELEGRAM_BOT_TOKEN"
echo "   - Get your user ID from @userinfobot"
echo "   - Add to TELEGRAM_ADMIN_IDS"
echo ""
echo "4. Start AgentGRIT:"
echo "   ${CYAN}./start.sh${NC}"
echo ""
echo -e "${GREEN}Happy coding! 🚀${NC}"
