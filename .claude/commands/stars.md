---
name: /stars
description: Organize GitHub star lists - add repos, sync assignments, audit orphans
agent: star-curator
deployable: true
source: project
---

## /stars Command

Manages GitHub star list organization through `tools/galaxy/stars.json`.

### Usage

```
/stars <repo-url>     Add repo to stars, auto-categorize, apply to GitHub
/stars sync           Apply all assignments from stars.json to GitHub
/stars list           Show current config as markdown table
/stars audit          Find starred repos not in config, suggest categories
```

### Arguments

The command accepts a single argument after `/stars`:

- **A GitHub URL or `owner/name`**: Triggers add+categorize flow
- **`sync`**: Triggers full sync
- **`list`**: Triggers config display
- **`audit`**: Triggers orphan detection

### Prerequisites

- `gh` CLI authenticated with `user` scope: `gh auth refresh -s user`
- `tools/galaxy/stars-sync.sh` must be executable

### Flow

1. Star Curator agent reads `tools/galaxy/stars.json`
2. For single repo: fetches metadata, matches keywords, assigns lists, applies via `stars-sync.sh apply`
3. For sync: applies all assignments via `stars-sync.sh sync`
4. Updates `stars.json` as needed (add only, never remove without approval)
