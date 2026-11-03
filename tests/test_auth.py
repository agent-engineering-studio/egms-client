from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from egms_client import EgmsError, ServiceKey, assertion, parse_token, token_request
from egms_client.auth import GRANT_TYPE

FIXTURES = Path(__file__).parent / "fixtures"


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_the_assertion_is_an_rs256_jwt_signed_by_the_key(
    service_key: ServiceKey, rsa_key: rsa.RSAPrivateKey
) -> None:
    jwt = assertion(service_key, now=1_000)
    header, claims, signature = jwt.split(".")
    assert json.loads(_b64decode(header)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(_b64decode(claims)) == {
        "iss": "client-1",
        "sub": "user-1",
        "aud": "https://land.example/@@oauth2-token",
        "iat": 1_000,
        "exp": 4_600,
    }
    rsa_key.public_key().verify(
        _b64decode(signature),
        f"{header}.{claims}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assert "=" not in jwt


def test_token_request_is_a_jwt_bearer_grant(service_key: ServiceKey) -> None:
    body = token_request(service_key, now=1_000)
    assert body["grant_type"] == GRANT_TYPE
    assert body["assertion"].count(".") == 2


def test_a_granted_token_expires_after_expires_in() -> None:
    token = parse_token(
        200, b'{"access_token": "t", "expires_in": 3600, "token_type": "Bearer"}', now=10
    )
    assert token.access_token == "t"
    assert token.expires_at == 3610
    assert token.headers() == {"Authorization": "Bearer t", "Accept": "application/json"}
    assert repr(token) == "Token(access_token=…, expires_at=3610.0)"


def test_a_bad_assertion_is_a_500_not_a_401() -> None:
    body = (FIXTURES / "token_bad_assertion_500.json").read_bytes()
    with pytest.raises(EgmsError, match=r"HTTP 500\): Invalid header padding"):
        parse_token(500, body, now=0)


def test_a_non_json_refusal_is_quoted() -> None:
    with pytest.raises(EgmsError, match="HTTP 403"):
        parse_token(403, b"<html>forbidden</html>", now=0)


def test_the_key_reads_the_downloaded_json_and_hides_the_private_part(
    service_key: ServiceKey,
) -> None:
    assert service_key.client_id == "client-1"
    assert "PRIVATE" not in repr(service_key)


@pytest.mark.parametrize(
    "text",
    [
        '{"client_id": "c", "user_id": "u", "token_uri": "t"}',
        '{"client_id": "", "user_id": "u", "private_key": "p", "token_uri": "t"}',
    ],
)
def test_a_key_with_a_missing_field_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="without"):
        ServiceKey.from_json(text)


def test_a_key_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        ServiceKey.from_json("[]")


def test_a_non_rsa_key_is_refused() -> None:
    pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        .decode()
    )
    key = ServiceKey(client_id="c", user_id="u", private_key=pem, token_uri="t")
    with pytest.raises(ValueError, match="not an RSA key"):
        assertion(key, now=0)
