from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from voluptuous import Optional, Required, Schema

from . import (CONF_PRIVATE_KEY, CONF_READ_RELAYS, CONF_WRITE_RELAYS, DOMAIN,
               decode_relays, encode_relays)
from .nostr.key import PrivateKey, PublicKey


class MyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input:
            data = {}
            key = user_input[CONF_PRIVATE_KEY]
            assert isinstance(key, str)
            if key.startswith("nsec"):
                key = PrivateKey.from_nsec(user_input[CONF_PRIVATE_KEY])
                data[CONF_PRIVATE_KEY] = key.hex()
                pubhex = key.public_key.hex()
                npub = key.public_key.bech32()
            else:
                key = PublicKey.from_npub(key)
                pubhex = key.hex()
                npub = key.bech32()
            await self.async_set_unique_id(pubhex)
            return self.async_create_entry(
                title=user_input.get(CONF_NAME) or npub,
                data=data,
                options={
                    CONF_READ_RELAYS: encode_relays(user_input.get(CONF_READ_RELAYS)),
                    CONF_WRITE_RELAYS: encode_relays(user_input.get(CONF_WRITE_RELAYS)),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=Schema({
                Required(CONF_PRIVATE_KEY): str,
                Optional(CONF_READ_RELAYS): SelectSelector(SelectSelectorConfig(options=[], multiple=True, custom_value=True)),
                Optional(CONF_WRITE_RELAYS): SelectSelector(SelectSelectorConfig(options=[], multiple=True, custom_value=True)),
                Optional(CONF_NAME): str,
            }),
            last_step=True,
        )

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry):
        return MyOptionsFlow(entry)


class MyOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry):
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input:
            return self.async_create_entry(
                data={
                    CONF_READ_RELAYS: encode_relays(user_input.get(CONF_READ_RELAYS)),
                    CONF_WRITE_RELAYS: encode_relays(user_input.get(CONF_WRITE_RELAYS)),
                },
            )
        else:
            options = self.entry.options
            reads = decode_relays(options.get(CONF_READ_RELAYS))
            writes = decode_relays(options.get(CONF_WRITE_RELAYS))
            urls = list(set[str](reads + writes))
            return self.async_show_form(
                step_id="init",
                data_schema=Schema({
                    Optional(CONF_READ_RELAYS, default=reads): SelectSelector(SelectSelectorConfig(options=urls, multiple=True, custom_value=True)),
                    Optional(CONF_WRITE_RELAYS, default=writes): SelectSelector(SelectSelectorConfig(options=urls, multiple=True, custom_value=True)),
                }),
                last_step=True,
            )
