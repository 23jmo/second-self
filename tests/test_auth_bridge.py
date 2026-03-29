"""Tests for utils.auth_bridge — Auth0 → Firebase token bridge."""

import pytest
from unittest.mock import MagicMock, patch

# Patch env vars before importing the module under test
import os

os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://api.secondself.app")

from utils.auth_bridge import (
    AuthBridgeError,
    _get_jwks_client,
    get_firebase_token,
    get_user_id,
    verify_auth0_token,
)
import utils.auth_bridge as bridge_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CLAIMS = {
    "sub": "auth0|64f3a2b1c9e",
    "email": "vin@example.com",
    "name": "Vin",
    "iss": "https://test.auth0.com/",
    "aud": "https://api.secondself.app",
    "exp": 9999999999,
}


@pytest.fixture(autouse=True)
def _reset_jwks_client():
    """Reset the module-level JWKS client singleton between tests."""
    bridge_mod._jwks_client = None
    yield
    bridge_mod._jwks_client = None


# ---------------------------------------------------------------------------
# _get_jwks_client
# ---------------------------------------------------------------------------

class TestGetJwksClient:
    def test_creates_client_when_domain_set(self):
        bridge_mod._AUTH0_DOMAIN = "test.auth0.com"
        client = _get_jwks_client()
        assert client is not None

    def test_raises_when_domain_empty(self):
        bridge_mod._AUTH0_DOMAIN = ""
        with pytest.raises(ValueError, match="AUTH0_DOMAIN"):
            _get_jwks_client()

    def test_returns_same_instance_on_second_call(self):
        bridge_mod._AUTH0_DOMAIN = "test.auth0.com"
        c1 = _get_jwks_client()
        c2 = _get_jwks_client()
        assert c1 is c2


# ---------------------------------------------------------------------------
# verify_auth0_token
# ---------------------------------------------------------------------------

class TestVerifyAuth0Token:
    @patch("utils.auth_bridge.jwt.decode")
    @patch("utils.auth_bridge._get_jwks_client")
    def test_valid_token(self, mock_client_fn, mock_decode):
        mock_key = MagicMock()
        mock_key.key = "rsa-public-key"
        mock_client_fn.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = dict(SAMPLE_CLAIMS)

        result = verify_auth0_token("valid.jwt.token")

        assert result["sub"] == "auth0|64f3a2b1c9e"
        assert result["email"] == "vin@example.com"

    @patch("utils.auth_bridge.jwt.decode")
    @patch("utils.auth_bridge._get_jwks_client")
    def test_expired_token(self, mock_client_fn, mock_decode):
        import jwt as pyjwt

        mock_key = MagicMock()
        mock_key.key = "rsa-public-key"
        mock_client_fn.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.side_effect = pyjwt.ExpiredSignatureError("expired")

        with pytest.raises(AuthBridgeError, match="expired"):
            verify_auth0_token("expired.jwt.token")

    @patch("utils.auth_bridge.jwt.decode")
    @patch("utils.auth_bridge._get_jwks_client")
    def test_invalid_audience(self, mock_client_fn, mock_decode):
        import jwt as pyjwt

        mock_key = MagicMock()
        mock_key.key = "rsa-public-key"
        mock_client_fn.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.side_effect = pyjwt.InvalidAudienceError("bad aud")

        with pytest.raises(AuthBridgeError, match="audience"):
            verify_auth0_token("bad-aud.jwt.token")

    @patch("utils.auth_bridge.jwt.decode")
    @patch("utils.auth_bridge._get_jwks_client")
    def test_invalid_issuer(self, mock_client_fn, mock_decode):
        import jwt as pyjwt

        mock_key = MagicMock()
        mock_key.key = "rsa-public-key"
        mock_client_fn.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.side_effect = pyjwt.InvalidIssuerError("bad iss")

        with pytest.raises(AuthBridgeError, match="issuer"):
            verify_auth0_token("bad-iss.jwt.token")

    @patch("utils.auth_bridge._get_jwks_client")
    def test_jwks_fetch_failure(self, mock_client_fn):
        import jwt as pyjwt

        mock_client_fn.return_value.get_signing_key_from_jwt.side_effect = (
            pyjwt.PyJWKClientError("connection refused")
        )

        with pytest.raises(AuthBridgeError, match="JWKS"):
            verify_auth0_token("any.jwt.token")

    @patch("utils.auth_bridge.jwt.decode")
    @patch("utils.auth_bridge._get_jwks_client")
    def test_generic_jwt_error(self, mock_client_fn, mock_decode):
        import jwt as pyjwt

        mock_key = MagicMock()
        mock_key.key = "rsa-public-key"
        mock_client_fn.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.side_effect = pyjwt.PyJWTError("something weird")

        with pytest.raises(AuthBridgeError, match="verification failed"):
            verify_auth0_token("weird.jwt.token")

    @patch("utils.auth_bridge.jwt.decode")
    @patch("utils.auth_bridge._get_jwks_client")
    def test_returns_dict_copy(self, mock_client_fn, mock_decode):
        """Returned claims should be a plain dict (not the same object)."""
        original = dict(SAMPLE_CLAIMS)
        mock_key = MagicMock()
        mock_key.key = "rsa-public-key"
        mock_client_fn.return_value.get_signing_key_from_jwt.return_value = mock_key
        mock_decode.return_value = original

        result = verify_auth0_token("valid.jwt.token")
        assert result is not original
        assert result == original


# ---------------------------------------------------------------------------
# get_user_id
# ---------------------------------------------------------------------------

class TestGetUserId:
    @patch("utils.auth_bridge.verify_auth0_token")
    def test_returns_sub(self, mock_verify):
        mock_verify.return_value = dict(SAMPLE_CLAIMS)
        assert get_user_id("valid.jwt") == "auth0|64f3a2b1c9e"

    @patch("utils.auth_bridge.verify_auth0_token")
    def test_missing_sub(self, mock_verify):
        mock_verify.return_value = {"email": "vin@example.com"}
        with pytest.raises(AuthBridgeError, match="sub"):
            get_user_id("no-sub.jwt")

    @patch("utils.auth_bridge.verify_auth0_token")
    def test_empty_sub(self, mock_verify):
        mock_verify.return_value = {"sub": ""}
        with pytest.raises(AuthBridgeError, match="sub"):
            get_user_id("empty-sub.jwt")

    @patch("utils.auth_bridge.verify_auth0_token")
    def test_propagates_verification_error(self, mock_verify):
        mock_verify.side_effect = AuthBridgeError("Token has expired")
        with pytest.raises(AuthBridgeError, match="expired"):
            get_user_id("expired.jwt")


# ---------------------------------------------------------------------------
# get_firebase_token
# ---------------------------------------------------------------------------

class TestGetFirebaseToken:
    @patch("utils.auth_bridge.verify_auth0_token")
    def test_valid_token(self, mock_verify):
        mock_verify.return_value = dict(SAMPLE_CLAIMS)

        import firebase_admin.auth  # force submodule load before patching

        with patch("firebase_admin.auth.create_custom_token", return_value=b"firebase-custom-token-bytes") as mock_create, \
             patch("src.db.firestore_client._ensure_firebase_initialized", return_value=True):

            result = get_firebase_token("valid.jwt")
            assert result == "firebase-custom-token-bytes"
            mock_create.assert_called_once_with("auth0|64f3a2b1c9e")

    @patch("utils.auth_bridge.verify_auth0_token")
    def test_propagates_verification_error(self, mock_verify):
        mock_verify.side_effect = AuthBridgeError("Token has expired")
        with pytest.raises(AuthBridgeError, match="expired"):
            get_firebase_token("expired.jwt")

    @patch("utils.auth_bridge.verify_auth0_token")
    def test_missing_sub(self, mock_verify):
        mock_verify.return_value = {"email": "vin@example.com"}
        with pytest.raises(AuthBridgeError, match="sub"):
            get_firebase_token("no-sub.jwt")

    @patch("utils.auth_bridge.verify_auth0_token")
    def test_firebase_not_initialized(self, mock_verify):
        mock_verify.return_value = dict(SAMPLE_CLAIMS)

        with patch("src.db.firestore_client._ensure_firebase_initialized", return_value=False):
            with pytest.raises(AuthBridgeError, match="Firebase not initialized"):
                get_firebase_token("valid.jwt")

    @patch("utils.auth_bridge.verify_auth0_token")
    def test_firebase_create_token_fails(self, mock_verify):
        mock_verify.return_value = dict(SAMPLE_CLAIMS)

        import firebase_admin.auth  # force submodule load before patching

        with patch("firebase_admin.auth.create_custom_token", side_effect=Exception("service account missing")), \
             patch("src.db.firestore_client._ensure_firebase_initialized", return_value=True):

            with pytest.raises(AuthBridgeError, match="Failed to create Firebase token"):
                get_firebase_token("valid.jwt")
