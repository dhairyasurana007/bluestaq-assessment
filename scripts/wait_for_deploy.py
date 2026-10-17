"""Poll <url>/health until it reports the expected commit. Usage: wait_for_deploy.py URL [SHA]."""

import json
import subprocess
import sys
import time
import urllib.request


def main() -> int:
    url = sys.argv[1].rstrip("/") + "/health"
    if len(sys.argv) > 2:
        sha = sys.argv[2]
    else:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                live = json.load(resp).get("commit")
            if live == sha:
                print(f"Deploy verified: {sha} is live at {url}")
                return 0
            print(f"Live commit is {live}; waiting for {sha}...", flush=True)
        except Exception as exc:  # cold start, deploy in progress, DNS
            print(f"Not reachable yet: {exc}", flush=True)
        time.sleep(20)
    print("Timed out waiting for deploy. Check the Render dashboard → Events / Logs.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
