# GPU Cluster Setup for astraeus Ollama Profiles

**Date**: 2026-02-03  
**Context**: Extending astraeus capabilities with Linux cluster + GPU for ollama profiles  
**Current Environment**: Ubuntu 22.04.5 LTS (Jammy Jellyfish), no local GPU detected

---

## Overview

astraeus has **two ollama-based profiles** designed for GPU-equipped systems:

| Profile | Target | Cost Savings | Strategy |
|---------|--------|--------------|----------|
| **Hybrid-Cloud-Ollama** | Budget + GPU | 60-80% | GPT-5.2 (reasoning) + GPT-4o (quality) + Ollama (volume) |
| **Hybrid-Claude-Ollama** | Claude MAX + GPU | ~60% tokens | Claude Opus/Sonnet (quality) + Ollama (volume) |

Both profiles route **high-volume, low-criticality tasks** to local Ollama models:
- `explore` (codebase navigation)
- `build-error-resolver` (type errors, lint fixes)
- `document-writer` (documentation generation)
- `doc-updater` (doc sync)
- `refactor-cleaner` (dead code removal)
- `journalist` (journal keeping)

**Quality-critical work** (TDD, security review, code review) always uses cloud models, even in ollama profiles.

---

## Current Ollama Model Assignments

### Hybrid-Cloud-Ollama Profile

```json
{
  "explore": "ollama/ministral-3:14b-32k",           // 32K context, fast exploration
  "build-error-resolver": "ollama/qwen3-coder-32k", // Code-specialized, 32K context
  "document-writer": "ollama/lfm2.5-thinking:latest",
  "doc-updater": "ollama/lfm2.5-thinking:latest",
  "refactor-cleaner": "ollama/qwen3-coder-32k",
  "journalist": "ollama/lfm2.5-thinking:latest"
}
```

### Hybrid-Claude-Ollama Profile

Same model assignments as above.

**Key Configuration**:
- `"stream": false` — Required for reliable tool calling with ollama
- `"permission": { "webfetch": "deny" }` — Local models shouldn't hit external APIs
- Fallback chain: `ollama/* → google/gemini-2.5-flash` (if ollama unavailable)

---

## GPU Cluster Requirements

### 1. Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU** | NVIDIA GPU with 8GB VRAM | 16GB+ VRAM (RTX 4060 Ti, A4000, etc.) |
| **RAM** | 16GB | 32GB+ (models load into RAM) |
| **Disk** | 50GB free | 100GB+ (model storage) |
| **CPU** | 4 cores | 8+ cores |

**Why NVIDIA?**: Ollama uses CUDA for GPU acceleration. AMD ROCm support exists but is experimental.

### 2. Software Stack

```bash
# 1. NVIDIA Driver (if not installed)
ubuntu-drivers devices
sudo ubuntu-drivers autoinstall
# OR manually: sudo apt install nvidia-driver-535

# 2. NVIDIA Container Toolkit (for Docker deployment)
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# 3. Ollama Installation
curl -fsSL https://ollama.com/install.sh | sh

# 4. Verify GPU Access
nvidia-smi
ollama list
```

### 3. Required Models

Pull the three models used by ollama profiles:

```bash
# Model 1: ministral-3 (14B, 32K context) - for exploration
ollama pull ministral-3:14b-32k

# Model 2: qwen3-coder (32K context) - for code tasks
ollama pull qwen3-coder-32k

# Model 3: lfm2.5-thinking - for documentation/writing
ollama pull lfm2.5-thinking:latest
```

**Disk Usage**: ~30-40GB total for all three models.

---

## Cluster Deployment Architectures

### Option A: Single-Node Setup (Simplest)

```
┌─────────────────────────────────────┐
│  Linux Cluster Node                 │
│  ┌───────────────────────────────┐  │
│  │ astraeus (OpenCode CLI)       │  │
│  │ ↓                             │  │
│  │ Ollama Server (localhost:11434)│ │
│  │ ↓                             │  │
│  │ GPU (CUDA)                    │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

**Setup**:
1. Install ollama on the cluster node
2. Run `ollama serve` (starts on `localhost:11434`)
3. Deploy astraeus: `python3 tools/astraeus load --target ~/my-project --profile hybrid-cloud-ollama`
4. OpenCode CLI automatically detects ollama at `localhost:11434`

**Pros**: Zero network overhead, simplest setup  
**Cons**: Single point of failure, no load balancing

---

### Option B: Remote Ollama Server (Recommended for Multi-User)

```
┌──────────────────┐          ┌──────────────────────────┐
│ User Workstation │          │ GPU Cluster Node         │
│                  │          │                          │
│ astraeus         │  HTTP    │ Ollama Server            │
│ (OpenCode CLI)   ├─────────>│ (0.0.0.0:11434)          │
│                  │          │   ↓                      │
│                  │          │ GPU Pool (CUDA)          │
└──────────────────┘          └──────────────────────────┘
```

**Setup**:

1. **On GPU cluster node**:
```bash
# Start ollama with network binding
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# OR use systemd (persistent)
sudo systemctl edit ollama
# Add:
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl restart ollama
```

2. **On user workstation**:
```bash
# Configure ollama endpoint
export OLLAMA_HOST=http://cluster-gpu-node:11434

# Verify connection
ollama list
```

3. **In astraeus profiles**: No changes needed — ollama SDK auto-detects `OLLAMA_HOST` env var.

**Pros**: Centralized GPU resources, multi-user support  
**Cons**: Network latency (typically <50ms on LAN), requires firewall rules

---

### Option C: Kubernetes Deployment (Enterprise)

```yaml
# ollama-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama-server
spec:
  replicas: 3  # Multiple replicas for load balancing
  template:
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        resources:
          limits:
            nvidia.com/gpu: 1  # 1 GPU per pod
        env:
        - name: OLLAMA_HOST
          value: "0.0.0.0:11434"
---
apiVersion: v1
kind: Service
metadata:
  name: ollama-service
spec:
  type: LoadBalancer
  ports:
  - port: 11434
    targetPort: 11434
```

**Deploy**:
```bash
kubectl apply -f ollama-deployment.yaml
export OLLAMA_HOST=http://ollama-service.default.svc.cluster.local:11434
```

**Pros**: Auto-scaling, high availability, GPU pooling  
**Cons**: Complex setup, requires K8s + GPU operator

---

## Performance Tuning

### 1. Concurrent Request Limits

In `.opencode/profiles/*.json`:

```json
{
  "background": {
    "max_concurrent": 12,
    "provider_limits": {
      "ollama": 10  // Max parallel ollama requests
    },
    "model_limits": {
      "ollama/ministral-3:14b-32k": 6,
      "ollama/qwen3-coder-32k": 4,
      "ollama/lfm2.5-thinking:latest": 6
    }
  }
}
```

**Tuning Guide**:
- **Single GPU (8GB VRAM)**: `ollama: 2-4` (models compete for VRAM)
- **Single GPU (16GB VRAM)**: `ollama: 4-8`
- **Multi-GPU cluster**: `ollama: 10+` (scale with GPU count)

### 2. Model Context Windows

| Model | Context | Use Case |
|-------|---------|----------|
| ministral-3:14b-32k | 32K | Large codebases, multi-file exploration |
| qwen3-coder-32k | 32K | Complex refactoring, build errors across files |
| lfm2.5-thinking | 8K | Short docs, journal entries |

**If hitting context limits**: Switch to cloud fallback (Gemini Flash has 1M context).

### 3. GPU Memory Management

```bash
# Monitor GPU usage
watch -n 1 nvidia-smi

# If OOM errors occur:
# 1. Reduce concurrent ollama requests
# 2. Use smaller quantization (e.g., ministral-3:14b-q4 instead of 14b-32k)
# 3. Offload one model to cloud
```

---

## Verification & Testing

### 1. Ollama Health Check

```bash
# Check ollama is running
curl http://localhost:11434/api/tags

# Test model inference
curl http://localhost:11434/api/generate -d '{
  "model": "ministral-3:14b-32k",
  "prompt": "Hello, world!",
  "stream": false
}'
```

### 2. astraeus Integration Test

```bash
cd ~/my-project

# Switch to ollama profile
opencode /init-local  # or /init-hybrid-claude-ollama

# Test explore agent (uses ollama)
opencode "Find all TypeScript files in src/"

# Monitor ollama logs
journalctl -u ollama -f
```

### 3. Smoke Test Command

astraeus has a built-in smoke test:

```bash
opencode /local-smoke
```

This command:
- Checks ollama is reachable
- Verifies all three required models are pulled
- Tests GPU availability (`nvidia-smi`)
- Runs sample inference on each model
- Reports latency and VRAM usage

---

## Fallback Strategy

**Critical**: Ollama profiles ALWAYS fall back to cloud if local models fail.

```
ollama/ministral-3:14b-32k
  ↓ (connection timeout / OOM)
google/gemini-2.5-flash
  ↓ (rate limit)
google/gemini-2.5-pro
```

**Failure scenarios**:
- Ollama server down → Gemini Flash
- GPU OOM → Gemini Flash
- Model not pulled → Gemini Flash
- Network unreachable → Gemini Flash

**No manual intervention required** — oh-my-opencode handles fallback automatically.

---

## Cost Analysis

### Hybrid-Cloud-Ollama Profile (Current)

**Baseline (Cloud-Only)**:
- GPT-5.2: $15/1M input tokens
- GPT-4o: $5/1M input tokens
- Gemini Flash: $0.075/1M input tokens
- **Typical monthly cost**: $30-50

**With Ollama (5 agents local)**:
- 60-70% of volume tasks → FREE (local GPU)
- Remaining 30-40% → Cloud
- **Estimated monthly cost**: $10-20 (60-80% savings)

### Hybrid-Claude-Ollama Profile

**Baseline (Claude MAX)**:
- Claude MAX: $20/month (unlimited Opus/Sonnet)
- **Typical token usage**: 5-10M tokens/month

**With Ollama**:
- Claude MAX: $20/month (still unlimited)
- 60% token savings (explore, build, docs local)
- Effective token capacity: 12-25M tokens/month
- **Net cost**: $20/month, but 2.5x more capacity

---

## Security Considerations

### 1. Network Exposure

If running ollama on `0.0.0.0`:

```bash
# Restrict to LAN only (firewall)
sudo ufw allow from 192.168.1.0/24 to any port 11434
sudo ufw deny 11434

# OR use SSH tunnel
ssh -L 11434:localhost:11434 user@cluster-node
export OLLAMA_HOST=http://localhost:11434
```

### 2. Model Permissions

Ollama agents have restricted permissions in profiles:

```json
{
  "explore": {
    "permission": {
      "webfetch": "deny",  // No external network access
      "edit": "deny",      // Read-only for exploration
      "write": "deny"
    }
  }
}
```

**Never grant ollama agents**:
- `webfetch: allow` (models could leak data)
- Full filesystem write access
- Access to secrets/credentials

### 3. Model Provenance

All three models are from trusted sources:
- **ministral-3**: Mistral AI (official)
- **qwen3-coder**: Alibaba Cloud (official)
- **lfm2.5-thinking**: LFM (community, 5K+ downloads)

**Verify checksums**:
```bash
ollama show ministral-3:14b-32k --modelfile
```

---

## Troubleshooting

### Problem: "ollama: connection refused"

**Solution**:
```bash
# Check ollama is running
systemctl status ollama

# Restart if needed
sudo systemctl restart ollama

# Check port
ss -tlnp | grep 11434
```

### Problem: "CUDA out of memory"

**Solution**:
```bash
# 1. Check current VRAM usage
nvidia-smi

# 2. Reduce concurrent requests in profile
# Edit .opencode/oh-my-opencode.json:
"provider_limits": { "ollama": 2 }  # Lower from 10

# 3. Use smaller quantization
ollama pull ministral-3:14b-q4  # 4-bit quantization (less VRAM)
```

### Problem: "Model not found"

**Solution**:
```bash
# Pull missing models
ollama pull ministral-3:14b-32k
ollama pull qwen3-coder-32k
ollama pull lfm2.5-thinking:latest

# Verify
ollama list
```

### Problem: Slow inference (>10s per request)

**Causes**:
- CPU-only mode (no GPU detected)
- Swapping to disk (insufficient RAM)
- Network latency (remote ollama)

**Solution**:
```bash
# Check GPU is used
nvidia-smi  # Should show ollama process

# Check RAM usage
free -h

# Test local vs remote latency
time curl http://localhost:11434/api/tags
time curl http://cluster-node:11434/api/tags
```

---

## Next Steps

### Immediate Actions

1. **Install ollama** on GPU cluster node:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. **Pull required models**:
   ```bash
   ollama pull ministral-3:14b-32k
   ollama pull qwen3-coder-32k
   ollama pull lfm2.5-thinking:latest
   ```

3. **Test inference**:
   ```bash
   ollama run ministral-3:14b-32k "Hello, test"
   ```

4. **Deploy astraeus** with ollama profile:
   ```bash
   cd ~/my-project
   python3 /path/to/astraeus/tools/astraeus load --target . --profile hybrid-cloud-ollama
   ```

5. **Run smoke test**:
   ```bash
   opencode /local-smoke
   ```

### Future Enhancements

- [ ] **Multi-GPU support**: Load balance across GPU pool
- [ ] **Model caching**: Pre-load models into VRAM
- [ ] **Custom models**: Fine-tune qwen3-coder on project codebase
- [ ] **Metrics dashboard**: Track ollama vs cloud usage, cost savings
- [ ] **Auto-scaling**: Spin up ollama instances on demand (K8s)

---

## References

- [Ollama Documentation](https://github.com/ollama/ollama/blob/main/docs/README.md)
- [NVIDIA CUDA Installation Guide](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/)
- [astraeus Profile System](../../docs/guides/profile-comparison.md)
- [oh-my-opencode Routing](https://github.com/code-yeongyu/oh-my-opencode)

---

**Questions?** Open an issue or contact the astraeus team.
