"""Mint the Google refresh token this service runs on. Run once, locally.

The club mailbox is a consumer Gmail account, so a service account is not an
option (domain-wide delegation needs Google Workspace). The service therefore
authenticates as a user, with a long-lived refresh token stored in Secret
Manager.

Before running:

1. In the Google Cloud project that owns the OAuth client (the CBT account's
   project, the same client n8n uses), add ``http://localhost:8765/`` to the
   client's Authorised redirect URIs. This is additive — leave the n8n callback
   in place.
2. Export the client credentials:

       export GOOGLE_OAUTH_CLIENT_ID=...
       export GOOGLE_OAUTH_CLIENT_SECRET=...

Then:

    uv run python scripts/mint_refresh_token.py

**Sign in as cb.toastmasters.d95@gmail.com**, not a personal account. If you are
signed into both in the same browser, Google will happily authorise the wrong
one and everything will appear to work until the club needs access. Use a
private window if unsure — the script prints the account it ended up with.

The app is published rather than in testing, so the resulting refresh token does
not expire on the 7-day clock. That matters more here than it did in n8n: there
is no UI to click "reconnect" on Cloud Run.
"""

from __future__ import annotations

import os
import sys

import httpx
from google_auth_oauthlib.flow import InstalledAppFlow

# Exactly the scopes the workflow needs, and no more. gmail.compose is a
# restricted scope; note that Google documents it as "Manage drafts and send
# emails", so it does permit sending. The service cannot send because
# integrations/gmail.py has no send code path, not because of this scope.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.compose",
]

REDIRECT_PORT = 8765


def main() -> int:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print(
            "set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET first",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [f"http://localhost:{REDIRECT_PORT}/"],
            }
        },
        scopes=SCOPES,
    )

    print("Opening a browser. Sign in as the CBT account, not your personal one.\n")
    credentials = flow.run_local_server(
        port=REDIRECT_PORT,
        # access_type=offline is what produces a refresh token at all;
        # prompt=consent forces a fresh one even if you have authorised before.
        access_type="offline",
        prompt="consent",
    )

    if not credentials.refresh_token:
        print(
            "Google returned no refresh token. Revoke the app's access at "
            "https://myaccount.google.com/permissions and run this again.",
            file=sys.stderr,
        )
        return 1

    # Confirm which account was actually authorised, and which scopes it granted.
    info = httpx.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"access_token": credentials.token},
        timeout=10.0,
    ).json()
    granted = sorted(info.get("scope", "").split())

    print("\n--- authorised ---")
    print(f"account: {info.get('email', 'unknown')}")
    print(f"scopes:  {granted}")
    if set(granted) != set(SCOPES):
        print("\nWARNING: granted scopes differ from the requested set.")
        print("The service asserts the exact scope set at run time and will refuse")
        print("to start with anything broader. Re-run and grant only these.")

    print("\n--- store this in Secret Manager as cbt-google-oauth-refresh-token ---")
    print(credentials.refresh_token)
    print("\nDo not commit it, and do not paste it into a chat window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
