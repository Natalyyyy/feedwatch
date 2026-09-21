# Source from a vault writer. Locks live outside the vault; inherited locks nest.
VAULT_GIT_HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/vault_git.py"
VAULT_LOCK_PATH="${VAULT_LOCK_PATH:-$HOME/.vault-git.lock}"
VAULT_LOCK_WAIT_SEC="${VAULT_LOCK_WAIT_SEC:-120}"
VAULT_PYTHON="${VAULT_PYTHON:-python3}"
[ ! -x /opt/homebrew/bin/python3.11 ] || VAULT_PYTHON=/opt/homebrew/bin/python3.11
VAULT_TX_DEPTH=0
VAULT_TX_OWN=0

vault_begin() {
  if [ "$VAULT_TX_DEPTH" -gt 0 ]; then
    VAULT_TX_DEPTH=$((VAULT_TX_DEPTH + 1)); return 0
  fi
  if [ -n "${VAULT_LOCK_FD:-}" ] && [ -e "/dev/fd/$VAULT_LOCK_FD" ]; then
    VAULT_TX_DEPTH=1; return 0
  fi
  exec 198>>"$VAULT_LOCK_PATH" || return 1
  if ! VAULT_LOCK_WAIT_SEC="$VAULT_LOCK_WAIT_SEC" "$VAULT_PYTHON" "$VAULT_GIT_HELPER" --vault . acquire-fd 198; then
    exec 198>&-
    return 1
  fi
  export VAULT_LOCK_FD=198 VAULT_LOCK_PATH
  VAULT_TX_DEPTH=1
  VAULT_TX_OWN=1
}

vault_end() {
  [ "$VAULT_TX_DEPTH" -gt 0 ] || return 0
  VAULT_TX_DEPTH=$((VAULT_TX_DEPTH - 1))
  if [ "$VAULT_TX_DEPTH" -eq 0 ] && [ "$VAULT_TX_OWN" -eq 1 ]; then
    exec 198>&-
    unset VAULT_LOCK_FD
    VAULT_TX_OWN=0
  fi
}

# Return codes pass through: 2 = unmerged index without rebase (autostash/merge),
# 1 = other failure. Quarantine backups are retained outside the vault.
vault_pull_safe() {
  "$VAULT_PYTHON" "$VAULT_GIT_HELPER" --vault "$1" pull
}

# Supply exact filenames, including deleted tracked files; directories and
# glob/magic pathspecs are errors. An unrelated staged change also blocks publish.
vault_publish_safe() {
  local root="$1" message="$2"; shift 2
  "$VAULT_PYTHON" "$VAULT_GIT_HELPER" --vault "$root" publish --message "$message" -- "$@"
}

# Same, but directories expand into their changed files (new, edited, deleted;
# ignored ones skipped) and missing paths are skipped. Nothing changed = success
# without a commit. For jobs that own a whole output directory in the vault.
vault_publish_changed() {
  local root="$1" message="$2"; shift 2
  "$VAULT_PYTHON" "$VAULT_GIT_HELPER" --vault "$root" publish-changed --message "$message" -- "$@"
}
