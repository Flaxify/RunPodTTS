from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status


def make_api_key_dependency(expected_api_key: str):
    async def require_api_key(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> None:
        supplied = x_api_key
        if authorization and authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()

        if supplied is None or not hmac.compare_digest(supplied, expected_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_api_key
