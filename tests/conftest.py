from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from egms_client import ServiceKey

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def service_key(rsa_key: rsa.RSAPrivateKey) -> ServiceKey:
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return ServiceKey.from_json(
        json.dumps(
            {
                "client_id": "client-1",
                "user_id": "user-1",
                "private_key": pem,
                "token_uri": "https://land.example/@@oauth2-token",
                "key_id": "ignored",
            }
        )
    )
