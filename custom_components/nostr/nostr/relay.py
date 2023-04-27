import json
from asyncio import Task, create_task, gather, get_running_loop, sleep
from logging import getLogger
from typing import Iterable

from aiohttp import ClientSession, WSMsgType
from reactivex import Observable, Subject, compose
from reactivex import operators as ops
from reactivex.abc import ObserverBase
from reactivex.disposable import CompositeDisposable, Disposable

from .event import Event
from .filter import Filter

_LOGGER = getLogger(__name__)


class Relay:
    def __init__(self, session: ClientSession, url: str) -> None:
        self._session = session
        self.url = url
        self._subid = 0
        self._filters = dict[str, dict]()
        self.received_unverify = Subject[list]()
        self.received = self.received_unverify.pipe(
            _verify_event(),
            ops.share(),
        )
        self.reconnected = Subject()

    async def send_json(self, data):
        await self.send_str(json.dumps(data, ensure_ascii=False))

    async def send_str(self, data: str):
        _LOGGER.debug(data)
        await self._ws.send_str(data)

    def subscribe(self, filter: Filter):
        def f(obs: ObserverBase[list], sched):
            fjson = filter.to_json_object()
            subid = f"{self._subid:x}"
            self._subid += 1

            def req(arg=None):
                _LOGGER.debug(f"sub {subid}")
                create_task(self.send_json(["REQ", subid, fjson]))

            def recv(x: list):
                if x[0] != "EVENT":
                    return
                fjson["since"] = max(fjson.get("since", 0), x[2].created_at)

            def dispose():
                _LOGGER.debug(f"unsub {subid}")
                create_task(self._send_close(subid))

            req()
            dis = CompositeDisposable()
            dis.add(Disposable(dispose))
            dis.add(self.reconnected.subscribe(req))
            dis.add(self.received.pipe(
                ops.filter(lambda x: x[0] in ("EVENT", "EOSE")),
                ops.filter(lambda x: x[1] == subid),
                ops.do_action(recv),
            ).subscribe(obs))
            return dis
        return Observable[list](f).pipe(ops.share())

    async def _loop(self):
        loop = get_running_loop()
        while True:
            _LOGGER.debug("connected " + self.url)
            try:
                while True:
                    msg = await self._ws.receive()
                    if msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                        break
                    _LOGGER.debug(msg.data)
                    if msg.type != WSMsgType.TEXT:
                        continue
                    obj = json.loads(msg.data)
                    if not isinstance(obj, list):
                        continue
                    loop.call_soon(self.received_unverify.on_next, obj)
            except Exception as ex:
                _LOGGER.debug(ex, stack_info=True)
            finally:
                _LOGGER.debug("disconnected " + self.url)
                await self._ws.close()
            await sleep(1)
            self._ws = await self._session.ws_connect(self.url)
            self.reconnected.on_next(None)

    async def _send_close(self, subid: str):
        if self._ws.closed:
            return
        try:
            await self.send_json(["CLOSE", subid])
        except:
            pass

    async def __aenter__(self, *args):
        self._ws = await self._session.ws_connect(self.url)
        self._task = create_task(self._loop())
        return self

    async def __aexit__(self, *args):
        try:
            self._task.cancel()
            await self._task
            self.received_unverify.on_completed()
            self.reconnected.on_completed()
        except:
            pass


class RelayClient:
    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._relays = dict[str, Task[Relay]]()

    async def get(self, url: str):
        task = self._relays.get(url)
        if not task:
            task = create_task(self._connect(url))
            self._relays[url] = task
        try:
            return await task
        except BaseException as ex:
            self._relays.pop(url, None)
            raise ex

    async def post_event(self, event: Event, urls: Iterable[str]):
        msg = event.to_message()
        tasks = list[Task]()
        for url in urls:
            tasks.append(create_task(self._send_str(url, msg)))
        return [x for x in await gather(*tasks, return_exceptions=True) if isinstance(x, BaseException)]

    async def _connect(self, url: str):
        relay = Relay(self._session, url)
        await relay.__aenter__()
        return relay

    async def _send_str(self, url: str, msg: str):
        relay = await self.get(url)
        await relay.send_str(msg)


def _verify_event():
    def _map(x: list):
        if x[0] == "EVENT":
            e: dict = x[2]
            event = Event(
                e.get("content", ""),
                e.get("pubkey", ""),
                e.get("created_at", 0),
                e.get("kind", 0),
                e.get("tags", []),
                e.get("sig", None),
            )
            if not event.verify():
                event = None
            return x[:2] + [event]
        return x
    return compose(
        ops.map(_map),
        ops.filter(lambda x: not (
            x[0] == "EVENT" and x[2] is None)),
    )
