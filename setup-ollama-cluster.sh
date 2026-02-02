#!/bin/bash
# GPU Cluster Setup Script for astraeus Ollama Profiles
# Usage: ./setup-ollama-cluster.sh [--remote-host HOSTNAME]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

REMOTE_HOST=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --remote-host)
      REMOTE_HOST="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--remote-host HOSTNAME]"
      exit 1
      ;;
  esac
done

echo -e "${GREEN}=== astraeus Ollama Cluster Setup ===${NC}\n"

# Function to run command locally or remotely
run_cmd() {
  if [[ -z "$REMOTE_HOST" ]]; then
    eval "$1"
  else
    ssh "$REMOTE_HOST" "$1"
  fi
}

# 1. Check NVIDIA GPU
echo -e "${YELLOW}[1/6] Checking NVIDIA GPU...${NC}"
if run_cmd "nvidia-smi &>/dev/null"; then
  echo -e "${GREEN}✓ NVIDIA GPU detected${NC}"
  run_cmd "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"
else
  echo -e "${RED}✗ No NVIDIA GPU detected${NC}"
  echo "Ollama will run in CPU mode (slow). Consider using cloud-only profile."
  read -p "Continue anyway? (y/N) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
  fi
fi

# 2. Check/Install Ollama
echo -e "\n${YELLOW}[2/6] Installing Ollama...${NC}"
if run_cmd "command -v ollama &>/dev/null"; then
  echo -e "${GREEN}✓ Ollama already installed${NC}"
  run_cmd "ollama --version"
else
  echo "Installing Ollama..."
  if [[ -z "$REMOTE_HOST" ]]; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    ssh "$REMOTE_HOST" "curl -fsSL https://ollama.com/install.sh | sh"
  fi
  echo -e "${GREEN}✓ Ollama installed${NC}"
fi

# 3. Start Ollama service
echo -e "\n${YELLOW}[3/6] Starting Ollama service...${NC}"
if run_cmd "systemctl is-active --quiet ollama"; then
  echo -e "${GREEN}✓ Ollama service already running${NC}"
else
  if [[ -z "$REMOTE_HOST" ]]; then
    sudo systemctl enable ollama
    sudo systemctl start ollama
  else
    ssh "$REMOTE_HOST" "sudo systemctl enable ollama && sudo systemctl start ollama"
  fi
  sleep 2
  echo -e "${GREEN}✓ Ollama service started${NC}"
fi

# 4. Pull required models
echo -e "\n${YELLOW}[4/6] Pulling required models (this may take 10-20 minutes)...${NC}"

MODELS=(
  "ministral-3:14b-32k"
  "qwen3-coder-32k"
  "lfm2.5-thinking:latest"
)

for model in "${MODELS[@]}"; do
  echo -e "\nPulling ${model}..."
  if run_cmd "ollama list | grep -q '${model%%:*}'"; then
    echo -e "${GREEN}✓ ${model} already exists${NC}"
  else
    run_cmd "ollama pull ${model}"
    echo -e "${GREEN}✓ ${model} pulled${NC}"
  fi
done

# 5. Test inference
echo -e "\n${YELLOW}[5/6] Testing model inference...${NC}"
if run_cmd "ollama run ministral-3:14b-32k 'Hello, test inference' --verbose 2>&1 | head -5"; then
  echo -e "${GREEN}✓ Inference test passed${NC}"
else
  echo -e "${RED}✗ Inference test failed${NC}"
  exit 1
fi

# 6. Configure environment
echo -e "\n${YELLOW}[6/6] Configuring environment...${NC}"

if [[ -n "$REMOTE_HOST" ]]; then
  OLLAMA_HOST="http://${REMOTE_HOST}:11434"
  
  echo -e "\nRemote setup detected. Add this to your ~/.bashrc or ~/.zshrc:"
  echo -e "${GREEN}export OLLAMA_HOST=${OLLAMA_HOST}${NC}"
  
  # Test connection
  if curl -s "${OLLAMA_HOST}/api/tags" &>/dev/null; then
    echo -e "${GREEN}✓ Remote connection successful${NC}"
  else
    echo -e "${RED}✗ Cannot reach ${OLLAMA_HOST}${NC}"
    echo "Make sure port 11434 is open on the remote host:"
    echo "  sudo ufw allow from YOUR_IP to any port 11434"
  fi
else
  echo -e "${GREEN}✓ Local setup complete${NC}"
  echo "Ollama is running on localhost:11434"
fi

# Summary
echo -e "\n${GREEN}=== Setup Complete ===${NC}\n"
echo "Models installed:"
run_cmd "ollama list"

echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Deploy astraeus with ollama profile:"
echo "   cd ~/my-project"
echo "   python3 /path/to/astraeus/tools/astraeus load --target . --profile hybrid-cloud-ollama"
echo ""
echo "2. Switch to ollama profile in existing project:"
echo "   opencode /init-local"
echo ""
echo "3. Run smoke test:"
echo "   opencode /local-smoke"
echo ""
echo "4. Monitor GPU usage:"
echo "   watch -n 1 nvidia-smi"

if [[ -n "$REMOTE_HOST" ]]; then
  echo -e "\n${YELLOW}Remote setup:${NC}"
  echo "Don't forget to set OLLAMA_HOST in your shell:"
  echo "  export OLLAMA_HOST=http://${REMOTE_HOST}:11434"
fi

echo -e "\n${GREEN}Documentation: galaxy-backend/docs/GPU_CLUSTER_SETUP.md${NC}"
