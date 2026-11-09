"""钉钉回调加解密：签名校验 + AES-CBC（PKCS7，32 字节块填充）加解密。

钉钉回调协议：
- encodingAesKey 为 43 字符，补 "=" 后 base64 解码得到 32 字节 AES 密钥；
- IV 取密钥前 16 字节；
- 明文 = 16 字节随机串 + 4 字节大端消息长度 + 消息体 + corpId，
  PKCS7 填充到 32 字节的倍数；
- 签名 = sha1(token + timestamp + nonce 按字典序拼接)。
"""

import base64
import hashlib
import random
import string

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def aes_key_from_encoding(encoding_aes_key: str) -> bytes:
    return base64.b64decode(encoding_aes_key + "=")


def verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    raw = "".join(sorted([token, timestamp, nonce]))
    expected = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return expected == signature


def _pad(raw: bytes) -> bytes:
    padder = padding.PKCS7(32 * 8).padder()
    return padder.update(raw) + padder.finalize()


def _unpad(data: bytes) -> bytes:
    unpadder = padding.PKCS7(32 * 8).unpadder()
    return unpadder.update(data) + unpadder.finalize()


def decrypt_message(encoding_aes_key: str, encrypted: str) -> str:
    """解密回调消息体，返回 JSON 字符串（不含 corpId）。"""
    key = aes_key_from_encoding(encoding_aes_key)
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    decryptor = cipher.decryptor()
    data = decryptor.update(base64.b64decode(encrypted)) + decryptor.finalize()
    data = _unpad(data)
    # 前 16 字节为随机串，其后 4 字节大端为消息长度，末尾为 corpId
    msg_len = int.from_bytes(data[16:20], "big")
    return data[20 : 20 + msg_len].decode("utf-8")


def encrypt_message(encoding_aes_key: str, message: str) -> str:
    """加密回调应答，返回 base64 密文。"""
    key = aes_key_from_encoding(encoding_aes_key)
    raw = message.encode("utf-8")
    base = (
        "".join(random.choices(string.ascii_letters + string.digits, k=16)).encode(
            "ascii"
        )
        + len(raw).to_bytes(4, "big")
        + raw
    )
    plaintext = _pad(base)
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    encryptor = cipher.encryptor()
    data = encryptor.update(plaintext) + encryptor.finalize()
    return base64.b64encode(data).decode("ascii")


__all__ = [
    "aes_key_from_encoding",
    "verify_signature",
    "decrypt_message",
    "encrypt_message",
]
