# Shared helpers for scripts/*.sh (sourced, not executed).
# Git Bash on Windows rewrites arguments like /opt/... into Windows paths; disable that
# so container paths passed to `docker compose exec` stay intact.
export MSYS_NO_PATHCONV=1

# Picks the project virtualenv's Python on Windows (Git Bash) or POSIX.
if [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi
export PY

wait_for_url() {  # wait_for_url <url> <timeout_s>
  local url=$1 timeout=${2:-180} start
  start=$(date +%s)
  until curl -fsS "$url" >/dev/null 2>&1; do
    if (( $(date +%s) - start > timeout )); then echo "timeout waiting for $url" >&2; return 1; fi
    sleep 3
  done
}
