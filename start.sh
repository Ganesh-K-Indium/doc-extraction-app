#!/usr/bin/env bash
#
# One command to get the app running: checks what is installed, installs what is missing, and starts the backend
# and the frontend, both with reload (edit a .py file or a .tsx file and the running app picks it up).
#
#   ./start.sh                  check everything, install what is missing, start both
#   ./start.sh --check          only report what is installed and what is not; change nothing, start nothing
#   ./start.sh --ocr            also install the optional local OCR engines (RapidOCR, PaddleOCR, docTR: about 1.2 GB) and download their models
#   ./start.sh --ocr rapidocr   or only some of them (rapidocr, paddleocr, doctr)
#   ./start.sh --models         download the models of the OCR engines that are installed (so the first upload does not wait for them)
#   ./start.sh --yes            do not ask before installing system packages (Tesseract)
#   ./start.sh --backend-only | --frontend-only
#   ./start.sh --api-port 8000 --web-port 5173      (or API_PORT / WEB_PORT in the environment)
#   ./start.sh --reinstall      ignore the "already installed" stamps and install again
#
# Safe to run again and again: each step is skipped when nothing it depends on has changed. Ctrl-C stops both servers.
# Needs bash, so on Windows use WSL or Git Bash.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$ROOT/.venv"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
CHECK_ONLY=0; YES=0; REINSTALL=0; MODELS=0; OCR=0; OCR_LIST=""; RUN_BACKEND=1; RUN_FRONTEND=1

while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --yes|-y) YES=1 ;;
    --reinstall) REINSTALL=1 ;;
    --models) MODELS=1 ;;
    --ocr) OCR=1; MODELS=1
           if [ $# -gt 1 ] && [[ "$2" != --* ]]; then OCR_LIST="$2"; shift; fi ;;
    --backend-only) RUN_FRONTEND=0 ;;
    --frontend-only) RUN_BACKEND=0 ;;
    --api-port) API_PORT="$2"; shift ;;
    --web-port) WEB_PORT="$2"; shift ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

# ---- output ----------------------------------------------------------------------------------------------------------
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'; else B=; G=; Y=; R=; D=; N=; fi
step() { printf '\n%s%s%s\n' "$B" "$*" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
note() { printf '  %s•%s %s\n' "$D" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '  %s✗%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
WARNINGS=0

confirm() {                       # confirm "question" -> 0 for yes. With --yes always yes; with no terminal always no.
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  local a; read -r -p "  $1 [y/N] " a; [[ "$a" =~ ^[Yy] ]]
}

hash_of() { cat "$@" 2>/dev/null | (shasum -a 256 2>/dev/null || sha256sum) | cut -c1-16; }

# A step's stamp records what it was last run against; the step runs again only when that changes.
stale() { [ "$REINSTALL" = 1 ] || [ ! -f "$1" ] || [ "$(cat "$1")" != "$2" ]; }

# ---- 1. system tools -------------------------------------------------------------------------------------------------
step "1. System tools"

pick_python() {
  local c p
  for c in python3.13 python3.12 python3.11 python3; do      # newest first, but 3.14 is last: some OCR wheels do not exist for it yet
    p="$(command -v "$c" 2>/dev/null)" || continue
    "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null && { echo "$p"; return 0; }
  done
  return 1
}

if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  BASE_PY=""
  ok "Python $("$VENV/bin/python" -c 'import platform; print(platform.python_version())') (virtual environment at .venv)"
else
  BASE_PY="$(pick_python)" || fail "Python 3.11 or newer is needed. Install it (macOS: brew install python@3.13; Debian/Ubuntu: sudo apt install python3 python3-venv) and run this again."
  ok "Python $("$BASE_PY" -c 'import platform; print(platform.python_version())') ($BASE_PY)"
fi

if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$NODE_MAJOR" -ge 18 ] || fail "Node 18 or newer is needed (found $(node --version)). Install it from https://nodejs.org or with your package manager."
  ok "Node $(node --version), npm $(npm --version)"
elif [ "$RUN_FRONTEND" = 1 ]; then
  fail "Node 18 or newer (with npm) is needed for the web app. Install it from https://nodejs.org, or run with --backend-only."
fi

install_tesseract() {
  if command -v brew >/dev/null 2>&1; then brew install tesseract
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y tesseract-ocr
  elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y tesseract
  else return 1; fi
}
if command -v "${TESSERACT_CMD:-tesseract}" >/dev/null 2>&1; then
  TESS="${TESSERACT_CMD:-tesseract}"
  if "$TESS" --list-langs 2>/dev/null | grep -qx "${TESSERACT_LANG:-eng}"; then
    ok "Tesseract $("$TESS" --version 2>&1 | head -1 | awk '{print $2}') (the built-in local OCR; gives scans their text layer)"
  else
    warn "Tesseract is installed but its language data for '${TESSERACT_LANG:-eng}' is not (install tesseract-ocr-eng or the language pack)."
  fi
elif [ "$CHECK_ONLY" = 1 ]; then
  warn "Tesseract is not installed: digital PDFs work, scans and photos will not be read. macOS: brew install tesseract"
elif confirm "Tesseract (local OCR for scans and photos) is not installed. Install it now?"; then
  install_tesseract && ok "Tesseract installed" || warn "Could not install Tesseract automatically. Install it by hand: https://github.com/tesseract-ocr/tesseract"
else
  warn "Tesseract is not installed: digital PDFs work, scans and photos will not be read. macOS: brew install tesseract   Debian: sudo apt install tesseract-ocr"
fi

# ---- 2. backend: virtual environment and packages --------------------------------------------------------------------
if [ "$RUN_BACKEND" = 1 ]; then
  step "2. Backend (Python packages)"
  PY="$VENV/bin/python"

  if [ ! -x "$PY" ]; then
    [ "$CHECK_ONLY" = 1 ] && { warn "No virtual environment yet (.venv): it will be created on the first run."; PY=""; } || {
      note "creating .venv"
      "$BASE_PY" -m venv "$VENV" || fail "Could not create the virtual environment. On Debian/Ubuntu: sudo apt install python3-venv"
      "$PY" -m pip install -q --upgrade pip
    }
  fi

  if [ -n "$PY" ]; then
    CORE_STAMP="$VENV/.stamp-core"
    CORE_NOW="$(hash_of "$BACKEND/requirements.txt")-$("$PY" -c 'import sys; print(sys.version_info[:2])')"
    CORE_IMPORTS='import fastapi, uvicorn, multipart, pydantic, sqlalchemy, dotenv, pymupdf, PIL, openai, cryptography, yaml, httpx'
    if [ ! -f "$CORE_STAMP" ] && [ "$REINSTALL" = 0 ] && "$PY" -c "$CORE_IMPORTS" 2>/dev/null; then
      [ "$CHECK_ONLY" = 1 ] || echo "$CORE_NOW" > "$CORE_STAMP"          # installed before this script existed: adopt it
      ok "backend packages are installed"
    elif stale "$CORE_STAMP" "$CORE_NOW" || ! "$PY" -c "$CORE_IMPORTS" 2>/dev/null; then
      if [ "$CHECK_ONLY" = 1 ]; then warn "Backend packages are missing or out of date: run ./start.sh to install them."
      else
        note "installing backend/requirements.txt"
        "$PY" -m pip install -q -r "$BACKEND/requirements.txt" || fail "pip could not install the backend packages (see the message above)."
        "$PY" -c "$CORE_IMPORTS" 2>/dev/null || fail "The backend packages installed, but importing them failed."
        echo "$CORE_NOW" > "$CORE_STAMP"
        ok "backend packages installed"
      fi
    else
      ok "backend packages are up to date"
    fi
  fi

  # ---- 3. optional local OCR engines and their models ---------------------------------------------------------------
  step "3. Local OCR engines (optional)"
  if [ -n "$PY" ]; then
    pip_for() {                    # engine id -> pip arguments
      case "$1" in
        rapidocr) echo "rapidocr-onnxruntime>=1.2.3" ;;
        paddleocr) echo "paddlepaddle>=3.0.0 paddleocr>=3.0.0" ;;
        doctr) echo "python-doctr[torch]>=0.9.0" ;;
      esac
    }
    if [ "$OCR" = 1 ] && [ "$CHECK_ONLY" = 0 ]; then
      WANT="${OCR_LIST:-rapidocr paddleocr doctr}"; WANT="${WANT//,/ }"
      if "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)'; then
        warn "This Python is 3.14: PaddleOCR and docTR (PyTorch) may have no wheels for it yet. Python 3.13 is the safe choice (brew install python@3.13, then delete .venv)."
      fi
      for e in $WANT; do
        args="$(pip_for "$e")"; [ -n "$args" ] || { warn "Unknown engine '$e' (use rapidocr, paddleocr or doctr)"; continue; }
        note "installing $e (this can take a few minutes)"
        # shellcheck disable=SC2086
        "$PY" -m pip install -q $args && ok "$e installed" || warn "$e could not be installed; the app works without it"
      done
    fi
    ( cd "$BACKEND" && "$PY" -m app.engines.warmup --status 2>/dev/null ) | sed 's/^/ /' || warn "Could not read the engine status."
    if [ "$MODELS" = 1 ] && [ "$CHECK_ONLY" = 0 ]; then
      note "checking the installed engines and downloading their models"
      ( cd "$BACKEND" && "$PY" -m app.engines.warmup ) || warn "At least one engine failed its check (see above); the others still work."
    elif [ "$CHECK_ONLY" = 0 ]; then
      note "Only Tesseract is needed. For RapidOCR, PaddleOCR and docTR: ./start.sh --ocr"
    fi
  else
    note "skipped until the virtual environment exists"
  fi
fi

# ---- 4. configuration files ------------------------------------------------------------------------------------------
step "4. Configuration"
for pair in "backend:$BACKEND" "frontend:$FRONTEND"; do
  name="${pair%%:*}"; dir="${pair#*:}"
  if [ "$name" = backend ] && [ "$RUN_BACKEND" = 0 ]; then continue; fi
  if [ "$name" = frontend ] && [ "$RUN_FRONTEND" = 0 ]; then continue; fi
  if [ -f "$dir/.env" ]; then ok "$name/.env exists"
  elif [ -f "$dir/.env.example" ]; then
    if [ "$CHECK_ONLY" = 1 ]; then note "$name/.env will be created from $name/.env.example"
    else cp "$dir/.env.example" "$dir/.env"; ok "created $name/.env from the example"; fi
  fi
done
if [ "$RUN_BACKEND" = 1 ]; then
  if [ -n "${OPENAI_API_KEY:-}${ANTHROPIC_API_KEY:-}${GEMINI_API_KEY:-}${OLLAMA_BASE_URL:-}" ] || grep -Eq '^(OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY|OLLAMA_BASE_URL)=.+' "$BACKEND/.env" 2>/dev/null; then
    ok "a model provider is configured"
  else
    note "no model key in backend/.env: digital PDFs and local OCR work; connect a model on the Settings page for vision reading"
  fi
fi

# ---- 5. frontend packages --------------------------------------------------------------------------------------------
if [ "$RUN_FRONTEND" = 1 ]; then
  step "5. Frontend (npm packages)"
  WEB_STAMP="$FRONTEND/node_modules/.stamp-deps"
  WEB_NOW="$(hash_of "$FRONTEND/package.json" "$FRONTEND/package-lock.json")"
  if [ -d "$FRONTEND/node_modules/.bin" ] && [ ! -f "$WEB_STAMP" ] && [ "$REINSTALL" = 0 ]; then
    [ "$CHECK_ONLY" = 1 ] || echo "$WEB_NOW" > "$WEB_STAMP"                # installed before this script existed: adopt it
    ok "frontend packages are installed"
  elif [ ! -d "$FRONTEND/node_modules" ] || stale "$WEB_STAMP" "$WEB_NOW"; then
    if [ "$CHECK_ONLY" = 1 ]; then warn "Frontend packages are missing or out of date: run ./start.sh to install them."
    else
      note "installing frontend packages"
      if [ -f "$FRONTEND/package-lock.json" ] && [ ! -d "$FRONTEND/node_modules" ]; then ( cd "$FRONTEND" && npm ci --no-audit --no-fund --loglevel=error )
      else ( cd "$FRONTEND" && npm install --no-audit --no-fund --loglevel=error ); fi || fail "npm could not install the frontend packages (see the message above)."
      echo "$WEB_NOW" > "$WEB_STAMP"
      ok "frontend packages installed"
    fi
  else
    ok "frontend packages are up to date"
  fi
fi

# ---- 6. ports --------------------------------------------------------------------------------------------------------
port_busy() { ( exec 3<>"/dev/tcp/127.0.0.1/$1" ) 2>/dev/null; }
who_uses() { command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1" (pid "$2")"}'; }
if [ "$CHECK_ONLY" = 0 ]; then
  step "6. Ports"
  [ "$RUN_BACKEND" = 1 ] && port_busy "$API_PORT" && fail "Port $API_PORT is already in use by $(who_uses "$API_PORT"). Stop it, or use --api-port."
  [ "$RUN_FRONTEND" = 1 ] && port_busy "$WEB_PORT" && fail "Port $WEB_PORT is already in use by $(who_uses "$WEB_PORT"). Stop it, or use --web-port."
  ok "ports $( [ "$RUN_BACKEND" = 1 ] && echo "$API_PORT" ) $( [ "$RUN_FRONTEND" = 1 ] && echo "$WEB_PORT" ) are free"
fi

if [ "$CHECK_ONLY" = 1 ]; then
  printf '\n%sCheck finished%s: %s\n' "$B" "$N" "$( [ "$WARNINGS" = 0 ] && echo "everything is in place" || echo "$WARNINGS thing(s) to look at, above" )"
  exit 0
fi

# ---- 7. run both, with reload ----------------------------------------------------------------------------------------
step "7. Starting"
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  printf '\n%sStopping...%s\n' "$D" "$N"
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  sleep 1
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill -9 "$p" 2>/dev/null || true; done
}
trap cleanup INT TERM EXIT

tag() { awk -v t="$1" -v c="$2" -v n="$N" '{ print c t n " " $0; fflush() }'; }   # prefix every log line with its server's name

if [ "$RUN_BACKEND" = 1 ]; then
  # --reload-dir app: only code changes restart it, not the uploads and database it writes under backend/data
  ( cd "$BACKEND" && CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT}" \
      exec "$VENV/bin/python" -m uvicorn app.main:app --reload --reload-dir app --reload-include '*.yaml' --reload-include '*.json' \
      --host 127.0.0.1 --port "$API_PORT" ) > >(tag "[api]" "$B$G") 2>&1 &
  API_PID=$!; PIDS+=("$API_PID")
fi
if [ "$RUN_FRONTEND" = 1 ]; then
  # --strictPort: the backend only allows the origin it was told about, so a silent hop to another port would break every call
  ( cd "$FRONTEND" && VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://localhost:$API_PORT}" \
      exec ./node_modules/.bin/vite --port "$WEB_PORT" --strictPort ) > >(tag "[web]" "$B$Y") 2>&1 &
  WEB_PID=$!; PIDS+=("$WEB_PID")
fi

wait_for() {                      # wait_for url name pid
  local i
  for i in $(seq 1 90); do
    curl -fsS -o /dev/null "$1" 2>/dev/null && return 0
    kill -0 "$3" 2>/dev/null || return 1
    sleep 1
  done
  return 1
}
if [ "$RUN_BACKEND" = 1 ]; then
  wait_for "http://127.0.0.1:$API_PORT/health" backend "$API_PID" && ok "backend is up      http://localhost:$API_PORT" || fail "The backend did not start (see its log above)."
fi
if [ "$RUN_FRONTEND" = 1 ]; then
  wait_for "http://localhost:$WEB_PORT/" frontend "$WEB_PID" && ok "web app is up      http://localhost:$WEB_PORT" || fail "The web app did not start (see its log above)."
fi
printf '\n  %sOpen http://localhost:%s%s   (Ctrl-C stops both; code changes reload on their own)\n\n' "$B" "$WEB_PORT" "$N"

# stay until either server stops, then stop the other one too
while :; do
  for p in "${PIDS[@]}"; do
    kill -0 "$p" 2>/dev/null || { printf '\n%sA server stopped on its own; stopping the other.%s\n' "$R" "$N"; exit 1; }
  done
  sleep 1
done
