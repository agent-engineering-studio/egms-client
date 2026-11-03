"""Access tokens from a CLMS service key.

The EGMS archive answers ``{"status": false, "message": "Please log in to
perform archive API calls."}`` to every anonymous call, releases included.
The way in that needs no browser is a **service key** of the Copernicus Land
Monitoring Service: land.copernicus.eu, EU Login, profile → "API Tokens" →
"Create new token". It is a JSON document with ``client_id``, ``user_id``,
``private_key`` (RSA, PEM) and ``token_uri``, and it does not expire.

The key signs a short JWT (RS256), which the token endpoint exchanges for a
bearer token valid one hour (OAuth 2.0 JWT bearer grant, RFC 7523).

A malformed assertion is answered with **HTTP 500** and a ``DecodeError``,
not 401: a retry policy on 5xx will retry it pointlessly.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from egms_client.errors import EgmsError

#: Lifetime of the signed assertion, in seconds.
ASSERTION_LIFETIME = 3600
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"

_FIELDS = ("client_id", "user_id", "private_key", "token_uri")


@dataclass(frozen=True, slots=True)
class ServiceKey:
    """A CLMS service key, as downloaded from the land.copernicus.eu profile."""

    client_id: str
    user_id: str
    private_key: str
    token_uri: str

    @classmethod
    def from_json(cls, text: str) -> ServiceKey:
        """Parse the JSON document; raise ``ValueError`` if a field is missing or empty."""
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("a CLMS service key is a JSON object")
        missing = [f for f in _FIELDS if not data.get(f)]
        if missing:
            raise ValueError(f"CLMS service key without {', '.join(missing)}")
        return cls(**{f: str(data[f]) for f in _FIELDS})

    def __repr__(self) -> str:
        return f"ServiceKey(client_id={self.client_id!r}, user_id={self.user_id!r}, private_key=…)"


@dataclass(frozen=True, slots=True)
class Token:
    """A bearer token and the Unix time it expires at."""

    access_token: str
    expires_at: float

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    def __repr__(self) -> str:
        return f"Token(access_token=…, expires_at={self.expires_at})"


def assertion(key: ServiceKey, *, now: int, lifetime: int = ASSERTION_LIFETIME) -> str:
    """The RS256 JWT the service key signs to ask for a token."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(
        json.dumps(
            {
                "iss": key.client_id,
                "sub": key.user_id,
                "aud": key.token_uri,
                "iat": now,
                "exp": now + lifetime,
            }
        ).encode()
    )
    private = serialization.load_pem_private_key(key.private_key.encode(), password=None)
    if not isinstance(private, rsa.RSAPrivateKey):
        raise ValueError("the CLMS service key is not an RSA key")
    signature = _b64(private.sign(header + b"." + claims, padding.PKCS1v15(), hashes.SHA256()))
    return (header + b"." + claims + b"." + signature).decode()


def token_request(key: ServiceKey, *, now: int) -> dict[str, str]:
    """The form body to POST to ``key.token_uri``."""
    return {"grant_type": GRANT_TYPE, "assertion": assertion(key, now=now)}


def parse_token(status_code: int, body: bytes | str, *, now: float) -> Token:
    """The token from the endpoint's answer; :class:`EgmsError` if it was refused."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        data = None
    if status_code != 200 or not isinstance(data, dict) or "access_token" not in data:
        detail = data.get("message") if isinstance(data, dict) else str(body)[:200]
        raise EgmsError(f"CLMS token refused (HTTP {status_code}): {detail}")
    return Token(
        access_token=str(data["access_token"]),
        expires_at=now + float(data.get("expires_in", ASSERTION_LIFETIME)),
    )


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")
