"""Submit a bundle as soon as the daily submission allowance resets; stop after one success.

Usage: python scripts/submit_when_allowed.py submissions/out/<name>/submission.zip "message" [max_hours]
Retries only on the "daily Submission allowance" refusal; any other error ends the script.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["KAGGLE_API_TOKEN"] = str(ROOT / "kaggle/access_token")
from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: E402

COMP = "gemma-4-developer-agent"


def main():
    zip_path, msg = sys.argv[1], sys.argv[2]
    stop = time.time() + 3600 * float(sys.argv[3] if len(sys.argv) > 3 else 8)
    api = KaggleApi()
    api.authenticate()
    while time.time() < stop:
        try:
            api.competition_submit(zip_path, msg, COMP, quiet=True)
            print(time.strftime("%H:%M"), "SUBMITTED", zip_path, flush=True)
            return 0
        except Exception as e:
            resp = getattr(e, "response", None)
            body = getattr(resp, "text", "") or str(e)
            transient = resp is None or getattr(resp, "status_code", 0) >= 500  # network trouble, Kaggle 5xx
            if not transient and "daily Submission allowance" not in body and "pending" not in body.lower():
                print(time.strftime("%H:%M"), "FAILED", body[:300], flush=True)
                return 1
        time.sleep(600)
    print("gave up: still not allowed", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
