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

import time
import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List
from hashlib import sha256

from . import bech32
from .message_type import ClientMessageType
from .key import PublicKey, PrivateKey


class EventKind(IntEnum):
    SET_METADATA = 0
    TEXT_NOTE = 1
    RECOMMEND_RELAY = 2
    CONTACTS = 3
    ENCRYPTED_DIRECT_MESSAGE = 4
    DELETE = 5


@dataclass
class Event:
    content: str
    public_key: str
    created_at: int
    kind: int = EventKind.TEXT_NOTE
    # Dataclasses require special handling when the default value is a mutable type
    tags: List[List[str]] = field(default_factory=list)
    signature: str | None = None

    def __post_init__(self):
        if self.content is not None and not isinstance(self.content, str):
            # DMs initialize content to None but all other kinds should pass in a str
            raise TypeError("Argument 'content' must be of type str")

        if self.created_at is None:
            self.created_at = int(time.time())

    @staticmethod
    def from_json(data: dict):
        return Event(
            data["content"],
            data["pubkey"],
            data["created_at"],
            data["kind"],
            data.get("tags", []),
            data.get("sig"),
        )

    @staticmethod
    def serialize(public_key: str, created_at: int, kind: int, tags: List[List[str]], content: str) -> bytes:
        data = [0, public_key, created_at, kind, tags, content]
        data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        return data_str.encode()

    @staticmethod
    def compute_id(public_key: str, created_at: int, kind: int, tags: List[List[str]], content: str):
        return sha256(Event.serialize(public_key, created_at, kind, tags, content)).digest()

    @property
    def id(self) -> str:
        # Always recompute the id to reflect the up-to-date state of the Event
        return self.id_bytes.hex()

    @property
    def id_bytes(self):
        # Always recompute the id to reflect the up-to-date state of the Event
        return Event.compute_id(self.public_key, self.created_at, self.kind, self.tags, self.content)

    @property
    def note_id(self) -> str:
        converted_bits = bech32.convertbits(bytes.fromhex(self.id), 8, 5)
        return bech32.bech32_encode("note", converted_bits, bech32.Encoding.BECH32)

    def add_pubkey_ref(self, pubkey: str):
        """ Adds a reference to a pubkey as a 'p' tag """
        self.tags.append(['p', pubkey])

    def add_event_ref(self, event_id: str):
        """ Adds a reference to an event_id as an 'e' tag """
        self.tags.append(['e', event_id])

    def sign(self, seckey: str | PrivateKey):
        if isinstance(seckey, str):
            seckey = PrivateKey(bytes.fromhex(seckey))
        if self.kind == EventKind.ENCRYPTED_DIRECT_MESSAGE and self.content is None:
            raise NotImplementedError()
        if self.public_key is None:
            self.public_key = seckey.public_key.hex()
        self.signature = seckey.sign_message_hash(self.id_bytes)

    def verify(self) -> bool:
        if self.signature is None:
            return False
        pub_key = PublicKey(bytes.fromhex(self.public_key))
        return pub_key.verify_signed_message_hash(self.id, self.signature)

    def to_message(self) -> str:
        return json.dumps(
            [
                ClientMessageType.EVENT,
                {
                    "id": self.id,
                    "pubkey": self.public_key,
                    "created_at": self.created_at,
                    "kind": self.kind,
                    "tags": self.tags,
                    "content": self.content,
                    "sig": self.signature
                }
            ],
            ensure_ascii=False,
        )


# @dataclass
# class EncryptedDirectMessage(Event):
#     recipient_pubkey: str
#     cleartext_content: str
#     reference_event_id: str

#     def __post_init__(self):
#         if self.content is not None:
#             self.cleartext_content = self.content
#             self.content = ""

#         if self.recipient_pubkey is None:
#             raise Exception("Must specify a recipient_pubkey.")

#         self.kind = EventKind.ENCRYPTED_DIRECT_MESSAGE
#         super().__post_init__()

#         # Must specify the DM recipient's pubkey in a 'p' tag
#         self.add_pubkey_ref(self.recipient_pubkey)

#         # Optionally specify a reference event (DM) this is a reply to
#         if self.reference_event_id is not None:
#             self.add_event_ref(self.reference_event_id)

#     @property
#     def id(self) -> str:
#         if self.content is None:
#             raise Exception(
#                 "EncryptedDirectMessage `id` is undefined until its message is encrypted and stored in the `content` field")
#         return super().id
