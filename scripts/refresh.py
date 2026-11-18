"""Trigger a Cloudflare Pages rebuild when the deployed package catalog changes."""
import os
import re
import sys
from urllib.request import Request, urlopen

from catalog import DIGEST_PATH, digest, fetch, load_catalog


def refresh(site, deploy_hook):
    upstream = digest(load_catalog())
    deployed = fetch(site.rstrip("/") + DIGEST_PATH, limit=256).decode("ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", deployed):
        raise ValueError("The deployed catalog digest is invalid")
    if deployed == upstream:
        print("The deployed package catalog is up to date")
        return
    if not deploy_hook:
        raise ValueError("Set the CLOUDFLARE_PAGES_DEPLOY_HOOK Actions secret")
    try:
        with urlopen(Request(deploy_hook, method="POST"), timeout=20) as response:
            if not 200 <= response.status < 300:
                raise ValueError(f"HTTP {response.status}")
    except OSError as error:
        # The hook URL is a credential and must stay out of Actions logs.
        code = getattr(error, "code", None)
        status = f"HTTP {code}" if code else type(error).__name__
        raise ValueError(f"Cloudflare Pages deploy hook failed ({status})") from None
    print("Cloudflare Pages accepted the catalog refresh")


if __name__ == "__main__":
    try:
        refresh(
            os.getenv("SITE_ORIGIN", "https://pkgs.uflinux.org"),
            os.getenv("CLOUDFLARE_PAGES_DEPLOY_HOOK"),
        )
    except (OSError, ValueError) as error:
        sys.exit(str(error))
