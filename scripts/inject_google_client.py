"""Write the Google OAuth client into google_config.json at build time.

GigaMail's Google client (a "Desktop app" OAuth client) travels inside the
package, like the Azure client id in ms_config.json: a desktop client's
secret is not confidential (Google documents it as such) and the loopback
login cannot run without it. It still does not belong in a public
repository: GitHub's secret scanner would flag it and git history is
forever. So google_config.json is committed empty, and this script fills
it in CI from two repository secrets, right before the wheel and the
installers are built.

Usage:
    python scripts/inject_google_client.py [path/to/google_config.json]

Environment:
    GOOGLE_OAUTH_CLIENT_ID      e.g. 1234-abcd.apps.googleusercontent.com
    GOOGLE_OAUTH_CLIENT_SECRET  e.g. GOCSPX-...

Exit status 1, with a ::error:: annotation for the job log, when the pair
is missing, half-missing or malformed. A release that silently ships
Google switched off is exactly the failure this script exists to prevent:
until October 2026 every downloaded copy answered "Google not configured"
because the file was empty and nothing noticed.

The secret is never printed.
"""

import json
import os
import sys
from pathlib import Path

ID_SUFFIX = ".apps.googleusercontent.com"
SECRET_PREFIX = "GOCSPX-"
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "src" / "gigamail" / "core" / "google_config.json"


def _error(msg: str) -> int:
    print(f"::error::{msg}")
    return 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    target = Path(argv[0]) if argv else DEFAULT_PATH

    client_id = (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    secret = (os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()

    if not client_id and not secret:
        return _error(
            "Google OAuth client missing: set the repository secrets "
            "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
            "(Settings > Secrets and variables > Actions). Without them the "
            "release would ship with Google calendar and Drive switched off."
        )
    if not client_id or not secret:
        # Half a pair is the one mistake worse than none: an id with the
        # wrong secret yields invalid_client and nothing else to go on.
        return _error(
            "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be "
            "set together; only one of them is."
        )
    if not client_id.endswith(ID_SUFFIX) or not secret.startswith(SECRET_PREFIX):
        return _error(
            f"Google OAuth client malformed: the id must end with {ID_SUFFIX} "
            f"and the secret must start with {SECRET_PREFIX}. Are the two "
            "secrets swapped?"
        )

    try:
        current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    except json.JSONDecodeError as e:
        return _error(f"{target} is not valid JSON: {e}")
    if not isinstance(current, dict):
        current = {}

    current["client_id"] = client_id
    current["client_secret"] = secret
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")

    print(f"Google OAuth client written to {target}")
    print(f"  client_id: {client_id}")
    print(f"  secret:    {len(secret)} characters, not shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
