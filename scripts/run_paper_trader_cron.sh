#!/usr/bin/env bash
# Daily paper trading run, meant to be fired by WSL cron (see README "Daily
# scheduling (WSL cron)"). Calls the Windows Python interpreter directly via
# WSL interop so it uses the same installed dependencies (alpaca-py,
# python-dotenv, etc.) already set up on the Windows side - no separate WSL
# Python environment needed.
set -euo pipefail

PROJECT_DIR="/mnt/c/Users/wyetw/llm-trading-system"
WIN_PYTHON="/mnt/c/Python314/python.exe"
LOG_DIR="$PROJECT_DIR/outputs"
LOG_FILE="$LOG_DIR/paper_trader_cron.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

{
  echo "=== $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  "$WIN_PYTHON" -m src.live.paper_trader \
    --tickers AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,AVGO,AMD,NFLX \
    --llm mock --strategy zero_shot
  echo "=== exit code: $? ==="
} >> "$LOG_FILE" 2>&1
