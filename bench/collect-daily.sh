#!/bin/sh
# Daily conversation metrics on this machine (ours only; see docs/knowledge/SAVINGS_PLAN.md).
#   sh bench/collect-daily.sh install     a LaunchAgent runs `bench/metrics.py collect` every day at 12:00 (and at login)
#   sh bench/collect-daily.sh uninstall   removes it
set -eu
LABEL=dev.ai-baton.metrics
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT="$(cd "$(dirname "$0")" && pwd)/metrics.py"
LOG="$HOME/.cache/ai-baton/metrics/collect.log"
case "${1:-}" in
  install)
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$SCRIPT</string><string>collect</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PLIST
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "installed: $PLIST (log: $LOG)";;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed";;
  *) echo "usage: sh bench/collect-daily.sh install|uninstall"; exit 2;;
esac
