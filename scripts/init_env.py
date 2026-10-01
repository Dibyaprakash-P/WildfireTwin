"""Create a local DEVELOPMENT .env from .env.example with a freshly generated JWT secret.

Usage: python -m scripts.init_env   (refuses to overwrite an existing .env)
"""

from __future__ import annotations

import secrets

from geo.registry import REPO_ROOT


def main() -> None:
    dst = REPO_ROOT / ".env"
    if dst.exists():
        print(".env already exists - not overwritten")
        return
    text = (REPO_ROOT / ".env.example").read_text()
    text = text.replace("JWT_SECRET=                         # REQUIRED",
                        f"JWT_SECRET={secrets.token_urlsafe(48)}  # generated for local development;")
    dst.write_text(text)
    print("wrote .env (development settings)")


if __name__ == "__main__":
    main()
