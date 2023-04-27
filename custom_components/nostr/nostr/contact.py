from reactivex import Observable
from reactivex import operators as ops
from reactivex.abc import ObserverBase
from reactivex.subject.subject import Subject

from .event import Event, EventKind


class ContactRegistory:
    def __init__(self) -> None:
        self.data = dict[bytes, Event]()
        self.updated = Subject[Event]()
        pass

    def get(self, pubkey: bytes):
        if pubkey in self.data:
            return self.data[pubkey]

    def get_followers(self, pubhex: str | bytes):
        if isinstance(pubhex, bytes):
            pubhex = pubhex.hex()
        values = list[str]()
        for event in self.data.values():
            for tag in event.tags:
                if tag[0] == "p" and tag[1] == pubhex:
                    values.append(event.public_key)
        return values

    def update_verified(self, event: Event):
        if event.kind != EventKind.CONTACTS:
            return
        if not isinstance(event.created_at, int):
            return
        pubkey = bytes.fromhex(event.public_key)
        if pubkey in self.data:
            created_at = self.data[pubkey].created_at
            if created_at >= event.created_at:
                return
        self.data[pubkey] = event
        self.updated.on_next(event)

    def subscribe(self, pubkey: bytes):
        pubhex = pubkey.hex()

        def f(obs: ObserverBase[Event], sched):
            if pubkey in self.data:
                obs.on_next(self.data[pubkey])
            return self.updated.pipe(
                ops.filter(lambda x: x.public_key == pubhex),
            ).subscribe(obs)
        return Observable[Event](f)
