#!/usr/bin/env bash
set -Eeuo pipefail

APP_REPO_URL="${APP_REPO_URL:-https://github.com/Underslumber/PoE2TradeHelper.git}"
APP_BRANCH="${APP_BRANCH:-main}"
APP_DIR="${APP_DIR:-/srv/poe2tradehelper/repo}"
APP_SERVICE="${APP_SERVICE:-poe2tradehelper.service}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
HEALTH_URL="${HEALTH_URL:-}"
APP_ENV_FILE="${APP_ENV_FILE:-$(dirname "$APP_DIR")/.env}"
WAKE_ON_DEPLOY_MARKER="${WAKE_ON_DEPLOY_MARKER:-$(dirname "$APP_DIR")/state/.wake-target-192.168.1.2.done}"

echo "Deploying PoE2TradeHelper branch $APP_BRANCH to $APP_DIR"

mkdir -p "$(dirname "$APP_DIR")"

if [ ! -d "$APP_DIR/.git" ]; then
    rm -rf "$APP_DIR"
    git clone --branch "$APP_BRANCH" "$APP_REPO_URL" "$APP_DIR"
else
    git -C "$APP_DIR" remote set-url origin "$APP_REPO_URL"
    git -C "$APP_DIR" fetch origin "$APP_BRANCH" --prune
    git -C "$APP_DIR" reset --hard "origin/$APP_BRANCH"
fi

cd "$APP_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt
"$VENV_DIR/bin/python" -m compileall mcp_server.py app
"$VENV_DIR/bin/python" -m pytest -q

# One-time emergency wake requested through the GitHub deployment path.
# Failure is reported in the Actions log but must not break the application deploy.
APP_ENV_FILE="$APP_ENV_FILE" \
WAKE_ON_DEPLOY_MARKER="$WAKE_ON_DEPLOY_MARKER" \
"$VENV_DIR/bin/python" scripts/wake_target_on_deploy.py || true

CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "Prepared commit $CURRENT_COMMIT"

if [ "$APP_SERVICE" != "none" ]; then
    $SYSTEMCTL restart "$APP_SERVICE"
    $SYSTEMCTL is-active --quiet "$APP_SERVICE"
    echo "Service $APP_SERVICE restarted"
else
    echo "APP_SERVICE=none, skipping service restart"
fi

if [ -n "$HEALTH_URL" ]; then
    curl --fail --silent --show-error --max-time 15 "$HEALTH_URL" >/dev/null
    echo "Health check passed: $HEALTH_URL"
fi
