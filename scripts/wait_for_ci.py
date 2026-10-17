"""Wait for all GitHub Actions runs for HEAD to finish.

Exit 0 = all succeeded, 1 = failure, 2 = timeout.
"""

import json
import subprocess
import sys
import time


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    sha = sh("git", "rev-parse", "HEAD")
    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        out = sh(
            "gh",
            "run",
            "list",
            "--commit",
            sha,
            "--json",
            "databaseId,status,conclusion,workflowName",
        )
        runs = json.loads(out or "[]")
        if runs and all(r["status"] == "completed" for r in runs):
            for r in runs:
                print(f"{r['workflowName']}: {r['conclusion']} (run {r['databaseId']})")
            failed = [r for r in runs if r["conclusion"] != "success"]
            if failed:
                print(f"Inspect: gh run view {failed[0]['databaseId']} --log-failed")
                return 1
            return 0
        print("CI running..." if runs else "No run registered for HEAD yet...", flush=True)
        time.sleep(15)
    print("Timed out waiting for CI")
    return 2


if __name__ == "__main__":
    sys.exit(main())
