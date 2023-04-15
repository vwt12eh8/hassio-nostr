from asyncio import create_task
from typing import Any, AsyncIterable, Callable, Coroutine, Optional, TypeVar

from aiohttp import ClientWebSocketResponse, WSMessage, WSMsgType
from reactivex import Observable, abc, compose
from reactivex import operators as ops
from reactivex.disposable import Disposable

_T = TypeVar("_T")


class ObservableWebsocket:
    def __init__(self, connect: Callable[[], Coroutine[Any, Any, ClientWebSocketResponse]]) -> None:
        super().__init__()
        self._connect = connect

    async def __aenter__(self, *_):
        self.ws = await self._connect()
        self.received = create_receiver(self.ws).pipe(ops.share())
        return self

    async def __aexit__(self, *_):
        await self.ws.close()


def create_receiver(ws: ClientWebSocketResponse):
    return from_async_iterable(ws)


def filter_text():
    def _filter(x: WSMessage):
        return x == WSMsgType.TEXT

    def _map(x: WSMessage) -> str:
        return x.data

    return compose(
        ops.filter(_filter),
        ops.map(_map),
    )


def from_async_iterable(iterable: AsyncIterable[_T]) -> Observable[_T]:
    def subscribe(
        observer: abc.ObserverBase[_T], scheduler_: Optional[abc.SchedulerBase] = None
    ) -> abc.DisposableBase:
        iterator = aiter(iterable)
        disposed = False

        async def action() -> None:
            nonlocal disposed

            try:
                while not disposed:
                    value = await anext(iterator)
                    observer.on_next(value)
            except StopIteration:
                observer.on_completed()
            except Exception as error:  # pylint: disable=broad-except
                observer.on_error(error)

        def dispose() -> None:
            nonlocal disposed
            disposed = True
            task.cancel()

        task = create_task(action())
        return Disposable(dispose)

    return Observable(subscribe)
