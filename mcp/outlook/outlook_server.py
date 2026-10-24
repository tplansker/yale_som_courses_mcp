"""Outlook MCP server — send email from a Yale Microsoft 365 account.

Uses Microsoft Graph with a single delegated scope, Mail.Send. It cannot
read, move, or delete mail; the only tool is send_email.

Settings come from the project .env (see .env.example):
    OUTLOOK_CLIENT_ID   Application (client) ID of your Entra app registration
    OUTLOOK_TENANT_ID   Tenant ID or domain (default: "organizations")

Sign in once from a terminal (device-code flow, token cached locally):
    python outlook_server.py --login
Run (stdio, what Claude Code uses):
    python outlook_server.py
Sign out (delete the cached token):
    python outlook_server.py --logout
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import msal
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for env_file in (ROOT / ".env", ROOT.parent / ".env"):
    if env_file.exists():
        load_dotenv(env_file, override=False)

CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID", "").strip()
TENANT_ID = os.getenv("OUTLOOK_TENANT_ID", "organizations").strip() or "organizations"
TOKEN_CACHE_PATH = HERE / ".token_cache.json"
SCOPES = ["Mail.Send"]
GRAPH = "https://graph.microsoft.com/v1.0"

mcp = FastMCP("outlook")


# --- Auth --------------------------------------------------------------------


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize())
        TOKEN_CACHE_PATH.chmod(0o600)


def _app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    if not CLIENT_ID:
        raise ToolError(
            "OUTLOOK_CLIENT_ID is not set. Add it to the project .env "
            "(see .env.example and the README)."
        )
    return msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )


def _access_token() -> str:
    cache = _load_cache()
    app = _app(cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    _save_cache(cache)
    if not result or "access_token" not in result:
        raise ToolError(
            "Not signed in to Outlook. In a terminal, run: "
            "mcp/outlook/.venv/bin/python mcp/outlook/outlook_server.py --login"
        )
    return result["access_token"]


def login() -> None:
    cache = _load_cache()
    app = _app(cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        sys.exit(f"Could not start sign-in: {flow.get('error_description', flow)}")
    print(flow["message"], flush=True)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        sys.exit(f"Sign-in failed: {result.get('error_description', result.get('error'))}")
    _save_cache(cache)
    name = result.get("id_token_claims", {}).get("preferred_username", "your account")
    print(f"Signed in as {name}. Token cached in {TOKEN_CACHE_PATH.name}.")


def logout() -> None:
    TOKEN_CACHE_PATH.unlink(missing_ok=True)
    print("Signed out; cached token removed.")


# --- Tools -------------------------------------------------------------------


@mcp.tool
def send_email(to: str, subject: str, body: str) -> dict:
    """Send a plain-text email from the signed-in Outlook account.

    to: one recipient address, e.g. someone@yale.edu
    subject: the subject line
    body: the message text
    """
    to = to.strip()
    if "@" not in to or " " in to:
        raise ToolError(f"{to!r} doesn't look like an email address.")
    if not subject.strip() and not body.strip():
        raise ToolError("Give a subject or a message body.")

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    resp = requests.post(
        f"{GRAPH}/me/sendMail",
        json=payload,
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=30,
    )
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {})
            detail = f"{err.get('code', '')}: {err.get('message', '')}"
        except ValueError:
            detail = resp.reason
        raise ToolError(f"Microsoft Graph returned {resp.status_code} ({detail})")
    return {"status": "sent", "to": to, "subject": subject}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Outlook (Microsoft 365) MCP server, send-only")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--login", action="store_true", help="Sign in with a device code")
    group.add_argument("--logout", action="store_true", help="Delete the cached token")
    args = parser.parse_args()
    if args.login:
        login()
    elif args.logout:
        logout()
    else:
        mcp.run()
