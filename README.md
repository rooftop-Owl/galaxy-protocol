# galaxy-backend

## GPU Cluster Extension for astraeus

This repository contains documentation and tooling for extending astraeus capabilities with GPU cluster support for ollama-based profiles.

### Quick Start

```bash
# Local GPU setup (single node)
./setup-ollama-cluster.sh

# Remote GPU cluster setup
./setup-ollama-cluster.sh --remote-host gpu-cluster-node

# Verify setup
opencode /local-smoke
```

### Documentation

- **[GPU_CLUSTER_SETUP.md](docs/GPU_CLUSTER_SETUP.md)** — Comprehensive guide for:
  - Hardware requirements (GPU, RAM, disk)
  - Software stack (NVIDIA drivers, ollama, models)
  - Deployment architectures (single-node, remote, Kubernetes)
  - Performance tuning and cost analysis
  - Troubleshooting common issues

### What This Enables

astraeus has two ollama profiles that leverage local GPUs for **60-80% cost savings**:

| Profile | Target | Strategy |
|---------|--------|----------|
| **Hybrid-Cloud-Ollama** | Budget + GPU | GPT-5.2 + GPT-4o + Ollama (volume) |
| **Hybrid-Claude-Ollama** | Claude MAX + GPU | Claude Opus/Sonnet + Ollama (volume) |

**Volume tasks run locally** (FREE):
- Codebase exploration (`explore` agent)
- Build/type error fixes (`build-error-resolver`)
- Documentation generation (`document-writer`, `doc-updater`)
- Dead code cleanup (`refactor-cleaner`)
- Journal keeping (`journalist`)

**Quality-critical tasks stay in cloud**:
- Test-driven development (`tdd-guide`)
- Code review (`code-reviewer`)
- Security auditing (`security-reviewer`)
- Deep reasoning (`oracle`, `architect`)

### Requirements

- **GPU**: NVIDIA with 8GB+ VRAM (16GB+ recommended)
- **RAM**: 16GB+ (32GB+ recommended)
- **Disk**: 50GB+ free space
- **OS**: Ubuntu 22.04+ or compatible Linux

### Models Used

Three ollama models (total ~30-40GB):
1. **ministral-3:14b-32k** — Fast exploration, 32K context
2. **qwen3-coder-32k** — Code-specialized, 32K context
3. **lfm2.5-thinking** — Documentation/writing

### Git Repository

This is a **separate git repository** inside the main astraeus project.

```bash
# Commit changes inside galaxy-backend
cd galaxy-backend
git add docs/ setup-ollama-cluster.sh README.md
git commit -m "Add GPU cluster setup documentation"
git push origin main

# Changes here do NOT affect parent astraeus repo
```

---

**Parent Project**: [astraeus](../) — Deploy AI agent teams to any project
