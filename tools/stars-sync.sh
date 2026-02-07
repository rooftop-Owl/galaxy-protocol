#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
STARS_JSON="$SCRIPT_DIR/../../.sisyphus/stars.json"

if [ ! -f "$STARS_JSON" ]; then
  echo "❌ stars.json not found at $STARS_JSON"
  exit 1
fi

if ! gh api graphql -f query='{ viewer { lists(first: 1) { nodes { id } } } }' --jq '.data.viewer.lists.nodes[0].id' 2>/dev/null | grep -q "^UL_"; then
  echo "❌ Cannot access star lists. Run: gh auth refresh -s user"
  exit 1
fi

resolve_list_id() {
  local list_name="$1"
  gh api graphql -f query='{ viewer { lists(first: 50) { nodes { name id } } } }' \
    --jq ".data.viewer.lists.nodes[] | select(.name == \"$list_name\") | .id" 2>/dev/null
}

get_repo_id() {
  local owner name
  owner=$(echo "$1" | cut -d'/' -f1)
  name=$(echo "$1" | cut -d'/' -f2)
  gh api graphql -f query="{ repository(owner: \"$owner\", name: \"$name\") { id } }" \
    --jq '.data.repository.id' 2>/dev/null
}

assign_repo() {
  local repo="$1"
  shift
  local list_ids=("$@")

  local repo_id
  repo_id=$(get_repo_id "$repo")
  if [ -z "$repo_id" ]; then
    echo "  ❌ $repo (repo not found)"
    return 1
  fi

  local list_json=""
  for lid in "${list_ids[@]}"; do
    [ -n "$list_json" ] && list_json+=", "
    list_json+="\"$lid\""
  done

  gh api graphql -f query="mutation { updateUserListsForItem(input: { itemId: \"$repo_id\", listIds: [$list_json] }) { user { login } } }" \
    2>/dev/null
  echo "  ✅ $repo"
}

ensure_lists_exist() {
  local list_names
  list_names=$(jq -r '.lists | keys[]' "$STARS_JSON")
  while IFS= read -r name; do
    gh api graphql -f query="mutation { createUserList(input: { name: \"$name\" }) { list { id name } } }" \
      >/dev/null 2>&1 || true
  done <<< "$list_names"
}

build_list_id_map() {
  declare -gA LIST_IDS
  local list_names
  list_names=$(jq -r '.lists | keys[]' "$STARS_JSON")
  local failed=0
  while IFS= read -r name; do
    local id
    id=$(resolve_list_id "$name")
    if [ -z "$id" ]; then
      echo "❌ Failed to resolve: $name"
      failed=1
    else
      LIST_IDS["$name"]="$id"
    fi
  done <<< "$list_names"
  if [ "$failed" -ne 0 ]; then
    echo "Some lists failed to resolve."
    exit 1
  fi
}

sync_all() {
  echo "=== Ensuring all lists exist ==="
  ensure_lists_exist

  echo "=== Resolving list IDs ==="
  build_list_id_map

  echo "=== Syncing all repos ==="
  local success=0 fail=0
  local repos
  repos=$(jq -r '.repos | keys[]' "$STARS_JSON")
  while IFS= read -r repo; do
    local list_names_json
    list_names_json=$(jq -r --arg r "$repo" '.repos[$r][]' "$STARS_JSON")

    local ids=()
    while IFS= read -r lname; do
      if [ -n "${LIST_IDS[$lname]+x}" ]; then
        ids+=("${LIST_IDS[$lname]}")
      else
        echo "  ⚠️  $repo: unknown list '$lname'"
      fi
    done <<< "$list_names_json"

    if [ ${#ids[@]} -gt 0 ]; then
      if assign_repo "$repo" "${ids[@]}"; then
        ((success++))
      else
        ((fail++))
      fi
    fi
  done <<< "$repos"

  echo "=== Done: $success succeeded, $fail failed ==="
}

apply_one() {
  local target="$1"
  target="${target#https://github.com/}"
  target="${target%.git}"

  local list_names_json
  list_names_json=$(jq -r --arg r "$target" '.repos[$r] // empty | .[]' "$STARS_JSON")
  if [ -z "$list_names_json" ]; then
    echo "❌ $target not found in stars.json"
    exit 1
  fi

  echo "=== Ensuring lists exist ==="
  ensure_lists_exist

  echo "=== Resolving list IDs ==="
  build_list_id_map

  echo "=== Applying: $target ==="
  local ids=()
  while IFS= read -r lname; do
    if [ -n "${LIST_IDS[$lname]+x}" ]; then
      ids+=("${LIST_IDS[$lname]}")
    fi
  done <<< "$list_names_json"

  if [ ${#ids[@]} -gt 0 ]; then
    assign_repo "$target" "${ids[@]}"
  else
    echo "❌ No valid list IDs resolved for $target"
    exit 1
  fi
}

case "${1:-help}" in
  sync)
    sync_all
    ;;
  apply)
    if [ -z "${2:-}" ]; then
      echo "Usage: stars-sync.sh apply <owner/name>"
      exit 1
    fi
    apply_one "$2"
    ;;
  *)
    echo "Usage: stars-sync.sh <sync|apply <owner/name>>"
    exit 1
    ;;
esac
