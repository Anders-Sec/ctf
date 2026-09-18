#!/usr/bin/env bash
#
# Everything CI used to run, run here instead.
#
# CI now only runs the suites a change can affect (see .github/workflows/ci.yml),
# which takes a UI tweak from twelve minutes to about four. The trade is that
# **this** is where a change gets proved, before it is pushed — so run it.
#
#   scripts/verify.sh              # everything
#   scripts/verify.sh frontend     # just the frontend (~20s)
#   scripts/verify.sh backend      # just the backend (~10min)
#   scripts/verify.sh changed      # whatever git says you touched
#
# Exits non-zero on the first failure, and says what failed rather than leaving
# you to find it in the scrollback.
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; DIM=$'\033[2m'; OFF=$'\033[0m'
FAILED=()
SKIPPED=()

# The backend venv is uv-managed and `uv` is not always on PATH on Windows, so
# call its python directly when it is there.
BACKEND_PY="$ROOT/backend/.venv/Scripts/python.exe"
[ -x "$BACKEND_PY" ] || BACKEND_PY="$ROOT/backend/.venv/bin/python"
[ -x "$BACKEND_PY" ] || BACKEND_PY="python"

step() {
  local label=$1; shift
  printf '%s\n' "${BOLD}==> ${label}${OFF}"
  local started=$SECONDS
  if "$@"; then
    printf '%s\n\n' "${GREEN}    ok${OFF} ${DIM}($((SECONDS - started))s)${OFF}"
  else
    printf '%s\n\n' "${RED}    FAILED${OFF} ${DIM}($((SECONDS - started))s)${OFF}"
    FAILED+=("$label")
  fi
}

run_backend() {
  cd "$ROOT/backend" || return 1
  step "backend · ruff check"   "$BACKEND_PY" -m ruff check .
  step "backend · ruff format"  "$BACKEND_PY" -m ruff format --check .
  step "backend · pytest"       "$BACKEND_PY" -m pytest -q
  cd "$ROOT" || return 1
}

run_frontend() {
  cd "$ROOT/frontend" || return 1
  # Same order as CI: the cheapest failure reports first.
  step "frontend · colours"   npm run --silent lint:colours
  step "frontend · typecheck" npm run --silent typecheck
  step "frontend · tests"     npm test --silent
  step "frontend · build"     npx vite build
  cd "$ROOT" || return 1
}

run_instances() {
  # These need pytest and flask (plus pyjwt for the registry) at the versions
  # the image pins, which most machines here will not have.
  #
  # A missing dependency is reported as **skipped, not passed and not failed**.
  # Two permanent reds would train you to ignore red, and a green would be a
  # pass nobody earned. CI runs these whenever deploy/instances/ changes, which
  # is rarely.
  if ! python -c "import pytest, flask" >/dev/null 2>&1; then
    printf '%s\n\n' "${DIM}==> instances · skipped (no pytest/flask in this python).
    CI runs them on any change under deploy/instances/.
    To run them here: pip install 'flask==3.0.3' 'pyjwt==2.9.0' pytest${OFF}"
    SKIPPED+=("instances")
    return 0
  fi

  for image in web-apothecary web-registry; do
    local dir="$ROOT/deploy/instances/$image"
    [ -d "$dir" ] || continue
    cd "$dir" || return 1
    step "instances · $image" python -m pytest -q
    cd "$ROOT" || return 1
  done
}

# What did you actually touch? Same question CI asks, answered the same way.
changed_targets() {
  local base files
  base=$(git merge-base HEAD origin/main 2>/dev/null || echo "HEAD~1")
  files=$(git diff --name-only "$base" HEAD; git diff --name-only; git ls-files --others --exclude-standard)
  echo "$files" | grep -q '^backend/'          && echo backend
  echo "$files" | grep -q '^frontend/'         && echo frontend
  echo "$files" | grep -q '^deploy/instances/' && echo instances
}

TARGETS=${1:-all}
if [ "$TARGETS" = "changed" ]; then
  TARGETS=$(changed_targets | sort -u | tr '\n' ' ')
  if [ -z "${TARGETS// }" ]; then
    echo "Nothing to check — no changes under backend/, frontend/ or deploy/instances/."
    exit 0
  fi
  echo "${DIM}Changed: ${TARGETS}${OFF}"
  echo
fi

for target in $TARGETS; do
  case "$target" in
    all)       run_backend; run_frontend; run_instances ;;
    backend)   run_backend ;;
    frontend)  run_frontend ;;
    instances) run_instances ;;
    *) echo "Unknown target: $target (expected: all, backend, frontend, instances, changed)"; exit 2 ;;
  esac
done

if [ ${#FAILED[@]} -eq 0 ]; then
  if [ ${#SKIPPED[@]} -eq 0 ]; then
    printf '%s
' "${GREEN}${BOLD}All green.${OFF}"
  else
    # Not "all green": something did not run, and saying it did would be the
    # kind of small lie that gets believed.
    printf '%s
' "${GREEN}${BOLD}Green${OFF}, with ${SKIPPED[*]} skipped."
  fi
  exit 0
fi

printf '%s\n' "${RED}${BOLD}Failed:${OFF}"
printf '  %s\n' "${FAILED[@]}"
exit 1
