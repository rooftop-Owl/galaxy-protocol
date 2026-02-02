# Quick Reference: astraeus GPU Cluster

## One-Liner Setup

```bash
./setup-ollama-cluster.sh && opencode /init-local
```

---

## Essential Commands

```bash
# Setup
./setup-ollama-cluster.sh                    # Local GPU setup
./setup-ollama-cluster.sh --remote-host GPU  # Remote GPU setup

# Profile Switching
opencode /init-local                         # → Hybrid-Cloud-Ollama
opencode /init-hybrid-claude-ollama          # → Hybrid-Claude-Ollama
opencode /init-cloud                         # → Cloud-only (no GPU)

# Verification
opencode /local-smoke                        # Health check
opencode /routing-smoke                      # Model routing test
nvidia-smi                                   # GPU status

# Monitoring
watch -n 1 nvidia-smi                        # Real-time GPU
journalctl -u ollama -f                      # Ollama logs
ollama ps                                    # Running models
```

---

## Model Quick Facts

| Model | Size | Context | Use |
|-------|------|---------|-----|
| ministral-3:14b-32k | 14B | 32K | Explore |
| qwen3-coder-32k | 7B | 32K | Build/Refactor |
| lfm2.5-thinking | 7B | 8K | Docs |

**Total disk**: ~35GB  
**Min VRAM**: 8GB (2 concurrent)  
**Recommended VRAM**: 16GB (4-6 concurrent)

---

## Agent Routing (Hybrid-Cloud-Ollama)

| Agent | Where | Cost |
|-------|-------|------|
| explore | 🖥️ GPU | FREE |
| build-error-resolver | 🖥️ GPU | FREE |
| document-writer | 🖥️ GPU | FREE |
| doc-updater | 🖥️ GPU | FREE |
| refactor-cleaner | 🖥️ GPU | FREE |
| journalist | 🖥️ GPU | FREE |
| tdd-guide | ☁️ Cloud | $$$ |
| code-reviewer | ☁️ Cloud | $$$ |
| oracle | ☁️ Cloud | $$$ |
| sisyphus | ☁️ Cloud | $$$ |

---

## Troubleshooting

```bash
# Ollama not running
sudo systemctl restart ollama

# Model not found
ollama pull ministral-3:14b-32k

# GPU not detected
nvidia-smi  # Should show GPU info

# Connection refused (remote)
ssh GPU-HOST "sudo ufw allow from YOUR_IP to any port 11434"

# Out of memory
# Edit .opencode/oh-my-opencode.json:
"provider_limits": { "ollama": 2 }  # Reduce from 10
```

---

## Cost Comparison

| Profile | Monthly Cost | GPU Required |
|---------|--------------|--------------|
| Cloud-only | $30-50 | ❌ |
| Hybrid-Cloud-Ollama | $10-20 | ✅ 8GB+ |
| Hybrid-Claude-Ollama | $20 (MAX) | ✅ 8GB+ |

**Savings**: 60-80% on volume tasks

---

## Remote Setup (Two-Machine)

**On GPU server**:
```bash
./setup-ollama-cluster.sh
sudo ufw allow from YOUR_WORKSTATION_IP to any port 11434
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

**On workstation**:
```bash
export OLLAMA_HOST=http://GPU_SERVER_IP:11434
ollama list  # Verify connection
opencode /init-local
```

---

## Performance Tuning

**Single GPU (8GB)**:
```json
"provider_limits": { "ollama": 2 }
```

**Single GPU (16GB)**:
```json
"provider_limits": { "ollama": 6 }
```

**Multi-GPU**:
```json
"provider_limits": { "ollama": 10 }
```

Edit: `.opencode/oh-my-opencode.json`

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Quick start guide |
| [GPU_CLUSTER_SETUP.md](docs/GPU_CLUSTER_SETUP.md) | Comprehensive setup (MUST READ) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, deployment patterns |
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | This file |

---

## Support

**Issues**: Check [GPU_CLUSTER_SETUP.md](docs/GPU_CLUSTER_SETUP.md) troubleshooting section  
**Questions**: Open GitHub issue on parent astraeus repo
