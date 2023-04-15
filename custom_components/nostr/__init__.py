import json
from asyncio import gather
from datetime import datetime
from logging import getLogger
from typing import Any, Callable, Iterable, cast

from aioesphomeapi import TypeVar
from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import (DeviceEntryType,
                                                   DeviceRegistry)
from nostr.event import Event as NEvent
from nostr.event import EventKind
from nostr.filter import Filter
from nostr.key import PrivateKey
from nostr.message_type import RelayMessageType
from reactivex import compose
from reactivex import operators as ops

from .rxws import ObservableWebsocket, filter_text
from .shared.factory import SharedFactory, SharedFactoryItem

ATTR_CONTENT = "content"
ATTR_CREATED_AT = "created_at"
ATTR_KIND = "kind"
ATTR_PUBKEY = "pubkey"
ATTR_TAGS = "tags"
CONF_PRIVATE_KEY = "private_key"
CONF_WRITE_RELAYS = "write_relays"
DOMAIN = "nostr"

_PLATFORMS = {
    Platform.TEXT,
}
_LOGGER = getLogger(__name__)

_T = TypeVar("_T")


class Relay:
    def __init__(self, client: ClientSession, url: str) -> None:
        self.url = url
        self.ws = ObservableWebsocket(lambda: client.ws_connect(url))

    async def __aenter__(self, *args):
        await self.ws.__aenter__(*args)
        self.received = self.ws.received.pipe(
            filter_text(),
            ops.map(lambda x: x.strip("\n")),
            ops.filter(lambda x: bool(x) and x[0] == "[" and x[-1] == "]"),
            ops.map(lambda x: cast(list, json.loads(x))),
            _verify_event(),
            ops.share(),
        )
        return self

    async def __aexit__(self, *args):
        del self.received
        await self.ws.__aexit__(*args)


class RelaysConnector:
    def __init__(self, factory: SharedFactory[str, Relay], *urls: str) -> None:
        self._factory = factory
        self._relays = list[SharedFactoryItem[str, Relay]]()
        for url in set(urls):
            self._relays.append(factory.get(url))

    async def __aenter__(self, *args):
        rollbacks = list[SharedFactoryItem[str, Relay]]()
        relays = list[Relay]()
        try:
            for fi in self._relays:
                relays.append(await fi.__aenter__(*args))
                rollbacks.append(fi)
            return RelaysConnection(relays)
        except BaseException as ex:
            for fi in rollbacks:
                await fi.__aexit__()
            raise ex

    async def __aexit__(self, *args):
        for fi in self._relays:
            await fi.__aexit__(*args)


class RelaysConnection:
    def __init__(self, relays: list[Relay]) -> None:
        self.relays = relays

    async def publish(self, data: str, urls: Iterable[str] | None = None):
        await gather(*[x.ws.ws.send_str(data) for x in self.relays if not urls or x.url in urls])


async def async_setup(hass: HomeAssistant, config):
    client = async_get_clientsession(hass)
    relays = SharedFactory[str, Relay](lambda url: Relay(client, url))
    hass.data[DOMAIN] = relays

    async def _service_post_event(call: ServiceCall):
        entries = hass.config_entries.async_entries(DOMAIN)
        dr = device_registry.async_get(hass)
        keys = list[ConfigEntry]()
        for pubkey in call.data[ATTR_PUBKEY]:
            if entry := _device_to_config_entry(dr, entries, pubkey):
                keys.append(entry)

        events = list[tuple[str, list[str]]]()
        all_urls = set[str]()
        for entry in keys:
            key = PrivateKey.from_nsec(entry.data[CONF_PRIVATE_KEY])
            created_at: Any = _parse_or_none(call.data.get(
                ATTR_CREATED_AT, None), lambda x: int(datetime.fromisoformat(x).timestamp()))
            event = NEvent(
                key.public_key.hex(),
                call.data.get(ATTR_CONTENT, ""),
                created_at,
                int(call.data[ATTR_KIND]),
                call.data.get(ATTR_TAGS, []),
            )
            key.sign_event(event)
            message = event.to_message()
            _LOGGER.debug(message)
            write_urls = [
                x for x in entry.options[CONF_WRITE_RELAYS].split("\n") if x]
            events.append((message, write_urls))
            all_urls.update(write_urls)

        async with RelaysConnector(relays, *all_urls) as rl:
            await gather(*[rl.publish(*x) for x in events])

    hass.services.async_register(DOMAIN, "post_event", _service_post_event)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    key = PrivateKey.from_nsec(entry.data[CONF_PRIVATE_KEY])
    npub = key.public_key.bech32()
    dr = device_registry.async_get(hass)
    dr.async_get_or_create(
        config_entry_id=entry.entry_id,
        configuration_url=f"nostr:{npub}",
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, npub)},
        name=entry.title,
    )
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


def _device_to_config_entry(dr: DeviceRegistry, entries: list[ConfigEntry], device_id: str):
    if device_id.startswith("npub"):
        npub = device_id
    else:
        if not (device := dr.async_get(device_id)):
            return
        if not (npub := next((x[1] for x in device.identifiers if x[0] == DOMAIN), None)):
            return
    return next((x for x in entries if x.unique_id == npub), None)


def _parse_or_none(value: str | None, parse: Callable[[str], _T]) -> _T | None:
    if value is None:
        return None
    return parse(value)


def _verify_event():
    def _map(x: list):
        if x[0] == RelayMessageType.EVENT:
            e: dict = x[2]
            event = NEvent(
                e.get("pubkey", ""),
                e.get("content", ""),
                e.get("created_at", 0),
                e.get("kind", 0),
                e.get("tags", []),
                e.get("id", None),
                e.get("sig", None),
            )
            if not event.verify():
                event = None
            return x[:2] + [event]
        return x
    return compose(
        ops.map(_map),
        ops.filter(lambda x: not (
            x[0] == RelayMessageType.EVENT and x[2] is None)),
    )
