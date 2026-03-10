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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# ANSI colors
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_THRESHOLD_HIGH = 80
USAGE_THRESHOLD_MEDIUM = 50
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
CACHE_PATH = Path.home() / ".claude" / ".statusline_cache.json"
CACHE_TTL_SECONDS = int(os.environ.get("STATUSLINE_CACHE_TTL", "15"))


test_data = '''
{
  "workspace": {
    "current_dir": "/home/abravakis/dev"
  },
  "five_hour": {
    "utilization": 56.0,
    "resets_at": "2026-03-06T18:00:01.145640+00:00"
  },
  "seven_day": {
    "utilization": 8.0,
    "resets_at": "2026-03-13T13:00:01.145662+00:00"
  },
  "seven_day_oauth_apps": null,
  "seven_day_opus": null,
  "seven_day_sonnet": null,
  "seven_day_cowork": null,
  "iguana_necktie": null,
  "extra_usage": {
    "is_enabled": true,
    "monthly_limit": 2000,
    "used_credits": 0.0,
    "utilization": null
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
    print(str(current_directory))
    model = data.get("model", {}).get("display_name", "")
    git_status = get_git_status(data)

    # Fetch usage from API
    access_token = get_access_token()

    if access_token:
        usage_data = fetch_usage(access_token)
        usage_str = format_usage(usage_data)
    else:
        usage_str = f"{RED}No credentials{RESET}"

    line = f"{BLUE}{model}{RESET} | {usage_str}"
    line2 = f"cwd: {current_directory} | {git_status}"

    print(line)
    print(line2)


def get_access_token() -> str | None:
    """Retrieve the access token based on the platform."""
    system = platform.system()

    if system == "Darwin":  # macOS
        return get_access_token_macos()
    elif system == "Linux":
        return get_access_token_linux()
    else:
        return None # Windows not supported


def get_access_token_macos() -> str | None:
    """Retrieve access token from macOS Keychain."""
    try:
        result = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True,
                text=True,
                timeout=2,
                check=True
                )
        credentials = result.stdout.strip()
        if credentials:
            creds = json.loads(credentials)
            return creds.get("claudeAiOauth", {}).get("accessToken")
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return None


def get_access_token_linux() -> str | None:
    """Read access token from credentials file on Linux."""
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def read_cache() -> dict | None:
    """Read cached usage data if it exists and hasn't expired."""
    try:
        with open(CACHE_PATH) as f:
            cache = json.load(f)
        cached_at = cache.get("cached_at", 0)
        now = datetime.now(timezone.utc).timestamp()
        data = cache.get("data")
        if now - cached_at > CACHE_TTL_SECONDS:
            data['stale'] = True

        return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def write_cache(data: dict) -> None:
    """Write usage data to cache with current timestamp."""
    cache = {
            "cached_at": datetime.now(timezone.utc).timestamp(),
            "data": data,
            }
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except OSError:
        pass


def fetch_usage(access_token: str) -> dict | None:
    """Fetch usage data from Anthropic API, using a file cache to avoid rate limits."""
    cached = read_cache()
    if cached is not None:
        if cached.get('stale', False) == False:
            return cached

    try:
        req = urllib.request.Request(
                USAGE_API_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "anthropic-beta": "oauth-2025-04-20",
                    },
                )
        with urllib.request.urlopen(req, timeout=5) as resp:
            sleep(3)
            data = json.loads(resp.read().decode())
        write_cache(data)
        return data
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        return cached


def format_usage(usage_data: dict) -> str:
    """Format usage data for statusline display."""
    if not usage_data:
        return f"{RED}Usage: N/A{RESET}"

    # Extract 5-hour and 7-day limits
    five_hour_usage = usage_data.get("five_hour", {})
    weekly_usage = usage_data.get("seven_day", {})

    five_hour_percentage = five_hour_usage.get("utilization", 0) or 0
    five_hour_reset = five_hour_usage.get("resets_at", '2000-01-01T00:00:00.065788+00:00')
    weekly_percentage = weekly_usage.get("utilization", 0) or 0
    weekly_reset = weekly_usage.get("resets_at", '2000-01-01T00:00:00.065788+00:00')

    five_hour_str = f"{get_usage_color(five_hour_percentage)}{five_hour_percentage:.0f}%{RESET}"
    five_hour_reset_str = f"{time_until_reset(five_hour_reset)}"
    weekly_str = f"{get_usage_color(weekly_percentage)}{weekly_percentage:.0f}%{RESET}"
    weekly_reset_str = f"{format_resets_at(weekly_reset)}"

    statusline = f"5h: {five_hour_str} ({five_hour_reset_str}) | 7d: {weekly_str} ({weekly_reset_str})"
    if usage_data.get('stale', False):
        statusline = statusline + ' | Stale data'

    return statusline

def format_resets_at(time_str):
    dt = datetime.fromisoformat(time_str)
    local_dt = dt.astimezone(ZoneInfo("Europe/Athens"))
    return local_dt.strftime("%H:%M %d/%m")

def time_until_reset(time):
    target = datetime.fromisoformat(time)
    now = datetime.now(timezone.utc)
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

        return f"{branch} {git_status}"
    except:
        return "no git info"

if __name__ == "__main__":
    main()
