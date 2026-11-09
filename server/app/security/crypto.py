"""파일 암호화 (AES-256-GCM, 봉투 암호화).

- 공간마다 무작위 데이터 키(DEK, 32바이트)를 만든다.
- DEK는 YEOUN_MASTER_KEY에서 유도한 키로 감싸(wrap) spaces.wrapped_key에 저장한다.
- 파일은 DEK로 암호화하고, 저장소 키를 AAD로 묶어 다른 위치로 옮겨 붙이는 것을 막는다.
- 공간을 지우면 wrapped_key도 사라지므로, 저장소에 사본이 남더라도 복호화할 수 없다(crypto-shredding).

암호문 형식: b"YE1" + nonce(12) + ciphertext||tag(16)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

log = logging.getLogger("yeoun.crypto")

MAGIC = b"YE1"
NONCE_LEN = 12


class MasterKeyMissing(RuntimeError):
    pass


def _decode_key_material(raw: str) -> bytes:
    raw = raw.strip()
    for decoder in (base64.b64decode, base64.urlsafe_b64decode, bytes.fromhex):
        try:
            data = decoder(raw)  # type: ignore[operator]
            if len(data) == 32:
                return data
        except Exception:  # noqa: S112 - 다음 디코더 시도
            continue
    # 32바이트가 아닌 임의 문자열이면 HKDF로 32바이트 키를 유도한다
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"yeoun-master", info=b"v1").derive(raw.encode())


@lru_cache
def master_key() -> bytes:
    s = get_settings()
    if s.master_key is not None and s.master_key.get_secret_value().strip():
        return _decode_key_material(s.master_key.get_secret_value())
    if not s.is_dev_like:
        raise MasterKeyMissing("YEOUN_MASTER_KEY가 필요합니다 (staging/production)")
    # 개발용: .data/master.key를 만들어 쓴다 (커밋 금지, .gitignore에 있음)
    path = s.data_dir / "master.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(base64.b64encode(secrets.token_bytes(32)).decode())
        os.chmod(path, 0o600)
        log.warning("개발용 마스터 키를 새로 만들었습니다 (.data/master.key)")
    return _decode_key_material(path.read_text())


def _kek() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"yeoun-kek", info=b"wrap-v1").derive(master_key())


@lru_cache
def signing_key() -> bytes:
    """서명 URL·쿠키용 HMAC 키. YEOUN_SESSION_SECRET이 있으면 그것을, 없으면 마스터 키에서 유도."""
    s = get_settings()
    if s.session_secret is not None and s.session_secret.get_secret_value().strip():
        material = s.session_secret.get_secret_value().encode()
    else:
        material = master_key()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"yeoun-sign", info=b"v1").derive(material)


def reset_key_cache() -> None:
    master_key.cache_clear()
    signing_key.cache_clear()


def new_data_key() -> bytes:
    return secrets.token_bytes(32)


def wrap_key(dek: bytes, space_id: str) -> bytes:
    nonce = secrets.token_bytes(NONCE_LEN)
    return MAGIC + nonce + AESGCM(_kek()).encrypt(nonce, dek, f"space:{space_id}".encode())


def unwrap_key(wrapped: bytes, space_id: str) -> bytes:
    if not wrapped.startswith(MAGIC):
        raise ValueError("알 수 없는 키 형식")
    nonce = wrapped[len(MAGIC) : len(MAGIC) + NONCE_LEN]
    return AESGCM(_kek()).decrypt(nonce, wrapped[len(MAGIC) + NONCE_LEN :], f"space:{space_id}".encode())


def encrypt_bytes(dek: bytes, plaintext: bytes, aad: str) -> bytes:
    nonce = secrets.token_bytes(NONCE_LEN)
    return MAGIC + nonce + AESGCM(dek).encrypt(nonce, plaintext, aad.encode())


def decrypt_bytes(dek: bytes, blob: bytes, aad: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("암호화되지 않은 데이터")
    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_LEN]
    return AESGCM(dek).decrypt(nonce, blob[len(MAGIC) + NONCE_LEN :], aad.encode())


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hmac_sign(message: str) -> str:
    mac = hmac.new(signing_key(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:24]).decode().rstrip("=")


def hmac_verify(message: str, signature: str) -> bool:
    return hmac.compare_digest(hmac_sign(message), signature)
