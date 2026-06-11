"""Mint an HS256 service_role JWT for the local PostgREST container."""
import base64
import hashlib
import hmac
import json
import sys

SECRET = "local-dev-jwt-secret-at-least-32-chars-long"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
payload = b64url(json.dumps({"role": "service_role", "iss": "local-dev", "exp": 4102444800}).encode())
signature = b64url(hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
sys.stdout.write(f"{header}.{payload}.{signature}")
