import json

from reactivex import Observable, Subject
from reactivex import operators as ops
from reactivex.abc import ObserverBase

from .event import Event


class MetadataRegistory:
    def __init__(self) -> None:
        self.data = dict[bytes, tuple[int, dict]]()
        self.updated = Subject[tuple[bytes, int, dict]]()
        pass

    def get(self, pubkey: bytes):
        if pubkey in self.data:
            return self.data[pubkey][1]

    def update_verified(self, event: Event):
        if event.kind != 0:
            return
        if not isinstance(event.created_at, int):
            return
        pubkey = bytes.fromhex(event.public_key)
        if pubkey in self.data:
            created_at = self.data[pubkey][0]
            if created_at >= event.created_at:
                return
        data: dict = json.loads(event.content)
        self.data[pubkey] = (event.created_at, data)
        self.updated.on_next((pubkey, event.created_at, data))

    def subscribe(self, pubkey: bytes):
        def f(obs: ObserverBase[tuple[int, dict]], sched):
            if pubkey in self.data:
                obs.on_next(self.data[pubkey])
            return self.updated.pipe(
                ops.filter(lambda x: x[0] == pubkey),
                ops.map(lambda x: x[1:]),
            ).subscribe(obs)
        return Observable[tuple[int, dict]](f)
