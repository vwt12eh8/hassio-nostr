from asyncio import Task, create_task
from typing import Any, Callable, Generic, TypeVar, cast

_Key = TypeVar("_Key")
_Value = TypeVar("_Value")


class SharedFactory(Generic[_Key, _Value]):
    def __init__(self, create: Callable[[_Key], Any]) -> None:
        super().__init__()
        self._create = create
        self._ref = dict[_Key, int]()
        self._val = dict[_Key, Task[tuple[Any, _Value]]]()

    def get(self, key: _Key):
        return SharedFactoryItem(self, key)


class SharedFactoryItem(Generic[_Key, _Value]):
    def __init__(self, factory: SharedFactory[_Key, _Value], key: _Key) -> None:
        super().__init__()
        self._factory = factory
        self._key = key

    async def __aenter__(self, *_):
        if self._key not in self._factory._ref:
            self._factory._ref[self._key] = 1
            self._factory._val[self._key] = create_task(self._create())
        else:
            self._factory._ref[self._key] += 1
        try:
            return (await self._factory._val[self._key])[1]
        except BaseException as ex:
            ref = self._factory._ref[self._key] - 1
            if ref == 0:
                del self._factory._val[self._key]
                del self._factory._ref[self._key]
            raise ex

    async def __aexit__(self, *_):
        ref = self._factory._ref[self._key] - 1
        if ref == 0:
            create_task(self._destroy(self._factory._val.pop(self._key)))
            del self._factory._ref[self._key]
        else:
            self._factory._ref[self._key] = ref

    async def _create(self):
        value = self._factory._create(self._key)
        return (value, cast(_Value, await value.__aenter__()))

    async def _destroy(self, t: Task[tuple[Any, _Value]]):
        value = await t
        await value[0].__aexit__()
