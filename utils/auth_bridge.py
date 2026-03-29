"""Auth0 -> Firebase token bridge.

Verifies Auth0 JWTs via JWKS and mints Firebase custom tokens so that
Firestore security rules can authorize requests from Auth0-authenticated users.
"""

import json
import logging
import os
import sys
from typing import Any

import jwt  # PyJWT

log = logging.getLogger("second-self")

_AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "")
_AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "")

_jwks_client: jwt.PyJWKClient | None = None


class AuthBridgeError(Exception):
    """Raised for any auth-bridge verification or minting failure."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_jwks_client() -> jwt.PyJWKClient:
    """Return a cached PyJWKClient for the configured Auth0 domain."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client

    domain = _AUTH0_DOMAIN
    if not domain:
        raise ValueError("AUTH0_DOMAIN environment variable is not set")

    uri = f"https://{domain}/.well-known/jwks.json"
    _jwks_client = jwt.PyJWKClient(uri, cache_keys=True, lifespan=300)
    return _jwks_client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_auth0_token(jwt_token: str) -> dict[str, Any]:
    """Verify an Auth0 JWT and return the decoded claims.

    Fetches the RS256 signing key from the Auth0 JWKS endpoint,
    validates signature, expiry, audience, and issuer.
    """
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(jwt_token)
    except jwt.PyJWKClientError as exc:
        raise AuthBridgeError(f"Failed to fetch JWKS signing key: {exc}") from exc
    except ValueError:
        raise

    issuer = f"https://{_AUTH0_DOMAIN}/"

    decode_kwargs: dict[str, Any] = {
        "key": signing_key.key,
        "algorithms": ["RS256"],
        "issuer": issuer,
    }
    if _AUTH0_AUDIENCE:
        decode_kwargs["audience"] = _AUTH0_AUDIENCE

    try:
        decoded = jwt.decode(jwt_token, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise AuthBridgeError("Token has expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthBridgeError("Invalid audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthBridgeError("Invalid issuer") from exc
    except jwt.PyJWTError as exc:
        raise AuthBridgeError(f"Token verification failed: {exc}") from exc

    return dict(decoded)


def get_firebase_token(auth0_jwt: str) -> str:
    """Validate an Auth0 JWT and return a Firebase custom token.

    Requires Firebase Admin SDK initialized with a service account.
    """
    claims = verify_auth0_token(auth0_jwt)
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise AuthBridgeError("Auth0 token missing 'sub' claim")

    try:
        from src.db.firestore_client import _ensure_firebase_initialized
        import firebase_admin.auth as fb_auth

        if not _ensure_firebase_initialized():
            raise AuthBridgeError(
                "Firebase not initialized. "
                "Set FIREBASE_SERVICE_ACCOUNT_PATH in .env"
            )

        token_bytes = fb_auth.create_custom_token(sub)
        return token_bytes.decode("utf-8") if isinstance(token_bytes, bytes) else str(token_bytes)
    except AuthBridgeError:
        raise
    except Exception as exc:
        raise AuthBridgeError(f"Failed to create Firebase token: {exc}") from exc


def get_user_id(auth0_jwt: str) -> str:
    """Validate an Auth0 JWT and return the 'sub' claim as the user ID.

    The sub looks like ``"auth0|64f3a2b1c9e"`` and is used as the
    canonical user_id throughout the codebase.
    """
    claims = verify_auth0_token(auth0_jwt)
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise AuthBridgeError("Auth0 token missing 'sub' claim")
    return sub


# ---------------------------------------------------------------------------
# CLI test helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    # Re-read env after dotenv
    _AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "")
    _AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "")

    token = sys.argv[1] if len(sys.argv) > 1 else input("Paste JWT: ").strip()
    if not token:
        print("No token provided.", file=sys.stderr)
        sys.exit(1)

    try:
        payload = verify_auth0_token(token)
        print(json.dumps(payload, indent=2, default=str))
    except AuthBridgeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)
