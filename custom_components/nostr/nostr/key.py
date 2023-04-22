# Copyright (c) 2022 Jeff Thibault

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import base64
import secrets

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from ecdsa import ECDH, SECP256k1, SigningKey

from . import bech32
from .schnorr_lib import pubkey_gen_from_int, schnorr_sign, schnorr_verify


class PublicKey:
    def __init__(self, raw_bytes: bytes) -> None:
        self.raw_bytes = raw_bytes

    def bech32(self) -> str:
        converted_bits = bech32.convertbits(self.raw_bytes, 8, 5)
        return bech32.bech32_encode("npub", converted_bits, bech32.Encoding.BECH32)

    def hex(self) -> str:
        return self.raw_bytes.hex()

    def verify_signed_message_hash(self, hash: str | bytes, sig: str | bytes) -> bool:
        if isinstance(hash, str):
            hash = bytes.fromhex(hash)
        if isinstance(sig, str):
            sig = bytes.fromhex(sig)
        return schnorr_verify(hash, self.raw_bytes, sig)

    @classmethod
    def from_npub(cls, npub: str):
        """ Load a PublicKey from its bech32/npub form """
        hrp, data, spec = bech32.bech32_decode(npub)
        if data is None:
            raise ValueError()
        raw_public_key = bech32.convertbits(data, 5, 8)
        if raw_public_key is None:
            raise ValueError()
        raw_public_key = raw_public_key[:-1]
        return cls(bytes(raw_public_key))


class PrivateKey:
    def __init__(self, raw_secret: bytes) -> None:
        self.raw_secret = raw_secret

        self.public_key = PublicKey(pubkey_gen_from_int(
            int.from_bytes(raw_secret, "big")))

    @classmethod
    def from_nsec(cls, nsec: str):
        """ Load a PrivateKey from its bech32/nsec form """
        hrp, data, spec = bech32.bech32_decode(nsec)
        raw_secret = bech32.convertbits(data, 5, 8)
        if raw_secret is None:
            raise ValueError()
        raw_secret = raw_secret[:-1]
        return cls(bytes(raw_secret))

    @classmethod
    def generate(cls):
        return cls(secrets.token_bytes(32))

    def bech32(self) -> str:
        converted_bits = bech32.convertbits(self.raw_secret, 8, 5)
        return bech32.bech32_encode("nsec", converted_bits, bech32.Encoding.BECH32)

    def hex(self) -> str:
        return self.raw_secret.hex()

    def compute_shared_secret(self, public_key_hex: str) -> bytes:
        sk = SigningKey.from_string(self.raw_secret, SECP256k1)
        ecdh = ECDH(SECP256k1, sk, sk.verifying_key)
        return ecdh.generate_sharedsecret_bytes()

    def encrypt_message(self, message: str, public_key_hex: str) -> str:
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(message.encode()) + padder.finalize()

        iv = secrets.token_bytes(16)
        cipher = Cipher(algorithms.AES(
            self.compute_shared_secret(public_key_hex)), modes.CBC(iv))

        encryptor = cipher.encryptor()
        encrypted_message = encryptor.update(
            padded_data) + encryptor.finalize()

        return f"{base64.b64encode(encrypted_message).decode()}?iv={base64.b64encode(iv).decode()}"

    def decrypt_message(self, encoded_message: str, public_key_hex: str) -> str:
        encoded_data = encoded_message.split('?iv=')
        encoded_content, encoded_iv = encoded_data[0], encoded_data[1]

        iv = base64.b64decode(encoded_iv)
        cipher = Cipher(algorithms.AES(
            self.compute_shared_secret(public_key_hex)), modes.CBC(iv))
        encrypted_content = base64.b64decode(encoded_content)

        decryptor = cipher.decryptor()
        decrypted_message = decryptor.update(
            encrypted_content) + decryptor.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        unpadded_data = unpadder.update(
            decrypted_message) + unpadder.finalize()

        return unpadded_data.decode()

    def sign_message_hash(self, hash: bytes) -> str:
        return schnorr_sign(hash, self.raw_secret.hex()).hex()

    def __eq__(self, other):
        return self.raw_secret == other.raw_secret
