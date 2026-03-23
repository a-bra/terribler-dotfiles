#!/usr/bin/env python3
import sys
import json
import os
import urllib.request
import urllib.error
import subprocess
import platform
from time import sleep
from pathlib import Path
from datetime import datetime as dt, timezone
from zoneinfo import ZoneInfo

# ANSI colors
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
PURPLE = "\033[35m"
RESET = "\033[0m"

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_THRESHOLD_HIGH = 80
USAGE_THRESHOLD_MEDIUM = 50
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
CACHE_PATH = Path.home() / ".claude" / ".statusline_cache.json"
CACHE_TTL_SECONDS = int(os.environ.get("STATUSLINE_CACHE_TTL", "30"))


test_data = '''
{
  "cwd": "/current/working/directory",
  "session_id": "abc123...",
  "transcript_path": "/path/to/transcript.jsonl",
  "model": {
    "id": "claude-opus-4-6",
    "display_name": "Opus"
  },
  "workspace": {
    "current_dir": "/current/working/directory",
    "project_dir": "/original/project/directory"
  },
  "version": "1.0.80",
  "output_style": {
    "name": "default"
  },
  "cost": {
    "total_cost_usd": 0.01234,
    "total_duration_ms": 45000,
    "total_api_duration_ms": 2300,
    "total_lines_added": 156,
    "total_lines_removed": 23
  },
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
    "context_window_size": 200000,
    "used_percentage": 8,
    "remaining_percentage": 92,
    "current_usage": {
      "input_tokens": 8500,
      "output_tokens": 1200,
      "cache_creation_input_tokens": 5000,
      "cache_read_input_tokens": 2000
    }
  },
  "exceeds_200k_tokens": false,
  "rate_limits": {
    "five_hour": {
      "used_percentage": 23.5,
      "resets_at": 1788425600
    },
    "seven_day": {
      "used_percentage": 41.2,
      "resets_at": 1788857600
    }
  },
  "vim": {
    "mode": "NORMAL"
  },
  "agent": {
    "name": "security-reviewer"
  },
  "worktree": {
    "name": "my-feature",
    "path": "/path/to/.claude/worktrees/my-feature",
    "branch": "worktree-my-feature",
    "original_cwd": "/path/to/project",
    "original_branch": "main"
  }
}
'''

def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
        # data = json.loads(test_data)
    except Exception as e:
        print("statusline: no data")
        return

    # Extract fields
    current_directory = os.path.basename(data['workspace']['current_dir'])
    model = data.get("model", {}).get("display_name", "")
    git_status = get_git_status(data)

    usage_str = format_usage(data['rate_limits'])

    line = f"{BLUE}{model}{RESET} | {usage_str}"
    line2 = f"cwd: {CYAN}{current_directory}{RESET} | {git_status}"

    print(line)
    print(line2)

def format_usage(usage_data: dict) -> str:
    """Format usage data for statusline display."""
    if not usage_data:
        return f"{RED}Usage: N/A{RESET}"

    # Extract 5-hour and 7-day limits
    five_hour_usage = usage_data.get("five_hour", {})
    weekly_usage = usage_data.get("seven_day", {})

    five_hour_percentage = five_hour_usage.get("used_percentage", 0) or 0
    five_hour_reset = five_hour_usage.get("resets_at", '1738425600')
    weekly_percentage = weekly_usage.get("used_percentage", 0) or 0
    weekly_reset = weekly_usage.get("resets_at", '1738425600')

    five_hour_str = f"{get_usage_color(five_hour_percentage)}{five_hour_percentage:.0f}%{RESET}"
    five_hour_reset_str = f"{time_until_reset(five_hour_reset)}"
    weekly_str = f"{get_usage_color(weekly_percentage)}{weekly_percentage:.0f}%{RESET}"
    weekly_reset_str = f"{format_resets_at(weekly_reset)}"

    statusline = f"5h: {five_hour_str} ({five_hour_reset_str}) | 7d: {weekly_str} ({weekly_reset_str})"
    if usage_data.get('stale', False):
        statusline = statusline + ' | Stale data'

    return statusline

def format_resets_at(time_str):
    dtm = dt.fromtimestamp(time_str, timezone.utc)
    local_dtm = dtm.astimezone(ZoneInfo("Europe/Athens"))
    return local_dtm.strftime("%H:%M %d/%m")

def time_until_reset(time):
    target = dt.fromtimestamp(time, timezone.utc)
    now = dt.now(timezone.utc)
    delta = target - now

    if delta.total_seconds() > 0:
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return(f"{hours}h {minutes}m")
    else:
        return("N/A")

def get_usage_color(percentage: float) -> str:
    if percentage >= USAGE_THRESHOLD_HIGH:
        return RED
    elif percentage >= USAGE_THRESHOLD_MEDIUM:
        return YELLOW
    return GREEN

def get_git_status(data):
    try:
        subprocess.check_output(['git', 'rev-parse', '--git-dir'], stderr=subprocess.DEVNULL)
        branch = subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip()
        staged_output = subprocess.check_output(['git', 'diff', '--cached', '--numstat'], text=True).strip()
        modified_output = subprocess.check_output(['git', 'diff', '--numstat'], text=True).strip()
        staged = len(staged_output.split('\n')) if staged_output else 0
        modified = len(modified_output.split('\n')) if modified_output else 0

        git_status = f"{GREEN}+{staged}{RESET}" if staged else ""
        git_status += f"{YELLOW}~{modified}{RESET}" if modified else ""

        return f"{PURPLE} {branch}{RESET} {git_status}"
    except:
        return "no git info"

if __name__ == "__main__":
    main()
