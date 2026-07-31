"""Config flow for Bestway integration."""

from __future__ import annotations

import asyncio
from logging import getLogger

from collections.abc import Mapping
from typing import Any

from aiohttp import ClientConnectionError
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .aws_iot.api import AwsIotAuthException
from .bestway.api import (
    BestwayApi,
    BestwayIncorrectPasswordException,
    BestwayUserDoesNotExistException,
)
from .const import (
    BACKEND_AWS_IOT,
    BACKEND_GIZWITS,
    BUBBLES_MODE_3WAY,
    BUBBLES_MODE_DEFAULT,
    BUBBLES_MODE_ONOFF,
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_API_ROOT_US,
    CONF_BUBBLES_MODE,
    CONF_PASSWORD,
    CONF_UID,
    CONF_USER_TOKEN,
    CONF_USER_TOKEN_EXPIRY,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = getLogger(__name__)
_STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_API_ROOT): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=CONF_API_ROOT_EU, label="EU"),
                    selector.SelectOptionDict(value=CONF_API_ROOT_US, label="US"),
                ]
            )
        ),
    }
)


async def validate_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Returns data to be stored in the config entry.
    """
    username = user_input[CONF_USERNAME]
    api_root = user_input[CONF_API_ROOT]
    session = async_get_clientsession(hass)
    async with asyncio.timeout(10):
        token = await BestwayApi.get_user_token(
            session, username, user_input[CONF_PASSWORD], api_root
        )

    config_entry_data = dict(user_input)
    config_entry_data[CONF_USER_TOKEN] = token.user_token
    config_entry_data[CONF_USER_TOKEN_EXPIRY] = token.expiry
    config_entry_data[CONF_UID] = token.user_id
    return config_entry_data


class BestwayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for bestway."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize config flow."""
        super().__init__()
        self._backend: str | None = None
        self._reauth_data: Mapping[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler.

        The framework injects ``config_entry`` onto the returned flow as
        a property, so we don't pass it through the constructor.
        """
        return BestwayOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - backend selection."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("backend"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value=BACKEND_GIZWITS,
                                        label="V01 - Bestway Smart Hub (Gizwits)",
                                    ),
                                    selector.SelectOptionDict(
                                        value=BACKEND_AWS_IOT,
                                        label="V02 - Bestway Connect (AWS IoT)",
                                    ),
                                ]
                            )
                        ),
                    }
                ),
            )

        # Store backend choice and route to appropriate auth flow
        self._backend = user_input["backend"]

        if self._backend == BACKEND_GIZWITS:
            return await self.async_step_gizwits_auth()
        else:
            return await self.async_step_aws_iot_auth()

    async def async_step_gizwits_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Gizwits authentication (V01 backend)."""
        if user_input is None:
            return self.async_show_form(
                step_id="gizwits_auth", data_schema=_STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            config_entry_data = await validate_input(self.hass, user_input)
        except BestwayUserDoesNotExistException:
            errors["base"] = "user_does_not_exist"
        except BestwayIncorrectPasswordException:
            errors["base"] = "incorrect_password"
        except ClientConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown_connection_error"
        else:
            # Add backend field for Gizwits
            config_entry_data["backend"] = BACKEND_GIZWITS
            return self.async_create_entry(
                title=user_input[CONF_USERNAME], data=config_entry_data
            )

        return self.async_show_form(
            step_id="gizwits_auth", data_schema=_STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_aws_iot_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle AWS IoT authentication (V02 backend) - QR code OR visitor_id."""
        if user_input is None:
            return self.async_show_form(
                step_id="aws_iot_auth",
                data_schema=vol.Schema(
                    {
                        vol.Required("region", default="EU"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value="EU", label="Europe"
                                    ),
                                    selector.SelectOptionDict(
                                        value="US", label="United States"
                                    ),
                                    selector.SelectOptionDict(
                                        value="CN", label="China"
                                    ),
                                ]
                            )
                        ),
                        vol.Optional("visitor_id"): str,
                        vol.Optional("qr_code"): str,
                    }
                ),
                description_placeholders={
                    "qr_help": "Scan QR from app Settings → Device Sharing",
                    "visitor_help": "OR enter visitor_id from existing account",
                },
            )

        errors = {}
        region = user_input.get("region", "EU")
        qr_code = user_input.get("qr_code", "").strip()
        visitor_id_input = user_input.get("visitor_id", "").strip()

        # Require one or the other
        if not qr_code and not visitor_id_input:
            errors["base"] = "qr_or_visitor_required"
            return self.async_show_form(
                step_id="aws_iot_auth",
                data_schema=vol.Schema(
                    {
                        vol.Required("region", default=region): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value="EU", label="Europe"
                                    ),
                                    selector.SelectOptionDict(
                                        value="US", label="United States"
                                    ),
                                    selector.SelectOptionDict(
                                        value="CN", label="China"
                                    ),
                                ]
                            )
                        ),
                        vol.Optional("visitor_id"): str,
                        vol.Optional("qr_code"): str,
                    }
                ),
                errors=errors,
            )

        try:
            from .aws_iot.api import AwsIotApi, API_ENDPOINTS

            session = async_get_clientsession(self.hass)

            # Map region to API endpoint
            api_base = API_ENDPOINTS.get(region, API_ENDPOINTS["EU"])

            # Determine visitor_id
            if qr_code:
                # Validate QR format
                if not qr_code.startswith("RW_Share_"):
                    errors["qr_code"] = "invalid_qr_format"
                    return self.async_show_form(
                        step_id="aws_iot_auth",
                        data_schema=vol.Schema(
                            {
                                vol.Optional("qr_code"): str,
                                vol.Optional("visitor_id"): str,
                            }
                        ),
                        errors=errors,
                    )

                # Generate visitor_id for new account
                visitor_id = AwsIotApi.generate_visitor_id()

                # Authenticate to get token
                token = await AwsIotApi.authenticate(
                    session, visitor_id, api_base=api_base
                )

                # Bind QR code to visitor account
                try:
                    device_info = await AwsIotApi.bind_qr_code(
                        session, qr_code, visitor_id, token, api_base=api_base
                    )
                    if not device_info:
                        errors["qr_code"] = "binding_failed"
                        return self.async_show_form(
                            step_id="aws_iot_auth",
                            data_schema=vol.Schema(
                                {
                                    vol.Optional("qr_code"): str,
                                    vol.Optional("visitor_id"): str,
                                }
                            ),
                            errors=errors,
                        )
                except Exception as bind_err:
                    _LOGGER.error("QR binding failed: %s", bind_err)
                    errors["qr_code"] = "binding_failed"
                    return self.async_show_form(
                        step_id="aws_iot_auth",
                        data_schema=vol.Schema(
                            {
                                vol.Optional("qr_code"): str,
                                vol.Optional("visitor_id"): str,
                            }
                        ),
                        errors=errors,
                    )
            else:
                # Use provided visitor_id
                visitor_id = visitor_id_input

                # Authenticate to get token
                token = await AwsIotApi.authenticate(
                    session, visitor_id, api_base=api_base
                )

            # Test by discovering devices
            api = AwsIotApi(
                session=session,
                visitor_id=visitor_id,
                token=token,
                api_base=api_base,
            )

            async with asyncio.timeout(10):
                await api.refresh_bindings()

            # Verify at least one device found
            if not api.devices:
                errors["base"] = "no_devices_found"
            else:
                # Create entry with AWS IoT backend (no device_id - multi-device!)
                return self.async_create_entry(
                    title=f"Bestway Spa (V02 - {region})",
                    data={
                        "backend": BACKEND_AWS_IOT,
                        "visitor_id": visitor_id,
                        "token": token,
                        "location": "GB",  # Legacy field
                        "region": region,
                        "api_base": api_base,
                    },
                )

        except AwsIotAuthException as auth_err:
            _LOGGER.error("AWS IoT authentication failed: %s", auth_err)
            errors["base"] = "auth_failed"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("AWS IoT setup failed")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="aws_iot_auth",
            data_schema=vol.Schema(
                {
                    vol.Required("region", default=region): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value="EU", label="Europe"),
                                selector.SelectOptionDict(
                                    value="US", label="United States"
                                ),
                                selector.SelectOptionDict(value="CN", label="China"),
                            ]
                        )
                    ),
                    vol.Optional("visitor_id"): str,
                    vol.Optional("qr_code"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a reauthentication flow.

        Triggered when the coordinator can no longer refresh the auth
        token automatically (e.g. the account password changed, or the
        AWS IoT visitor_id was revoked). Normal token expiry - which cloud
        tokens do silently, every few days - is now handled transparently
        by the coordinator/websocket clients and never reaches this step.
        """
        self._reauth_data = entry_data
        backend = entry_data.get("backend", BACKEND_GIZWITS)
        if backend == BACKEND_AWS_IOT:
            return await self.async_step_reauth_aws_iot()
        return await self.async_step_reauth_gizwits()

    async def async_step_reauth_gizwits(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication for the Gizwits (V01) backend."""
        assert self._reauth_data is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                config_entry_data = await validate_input(
                    self.hass,
                    {
                        CONF_USERNAME: self._reauth_data[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_API_ROOT: self._reauth_data[CONF_API_ROOT],
                    },
                )
            except BestwayUserDoesNotExistException:
                errors["base"] = "user_does_not_exist"
            except BestwayIncorrectPasswordException:
                errors["base"] = "incorrect_password"
            except ClientConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown_connection_error"
            else:
                reauth_entry = self._get_reauth_entry_or_none()
                if reauth_entry is None:
                    return self.async_abort(reason="reauth_entry_not_found")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**self._reauth_data, **config_entry_data},
                )

        return self.async_show_form(
            step_id="reauth_gizwits",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={
                "username": str(self._reauth_data.get(CONF_USERNAME, ""))
            },
            errors=errors,
        )

    async def async_step_reauth_aws_iot(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication for the AWS IoT (V02) backend.

        The visitor_id itself rarely goes bad - only the token does, and
        that refresh is now handled automatically during normal operation.
        This step only runs once that automatic refresh has already failed,
        so first retry it here in case the failure was transient, then fall
        back to letting the user supply a new visitor_id/QR code.
        """
        assert self._reauth_data is not None
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)

        from .aws_iot.api import API_ENDPOINTS, AwsIotApi

        visitor_id = str(self._reauth_data.get("visitor_id", ""))
        location = self._reauth_data.get("location", "GB")
        region = self._reauth_data.get("region", "EU")
        api_base = self._reauth_data.get("api_base") or API_ENDPOINTS.get(
            region, API_ENDPOINTS["EU"]
        )

        if user_input is None and visitor_id:
            # Retry with the existing visitor_id before asking the user for one
            try:
                token = await AwsIotApi.authenticate(
                    session, visitor_id, location, api_base
                )
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.warning(
                    "Automatic AWS IoT reauth failed, asking for a new visitor ID: %s",
                    ex,
                )
            else:
                reauth_entry = self._get_reauth_entry_or_none()
                if reauth_entry is None:
                    return self.async_abort(reason="reauth_entry_not_found")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**self._reauth_data, "token": token},
                )

        if user_input is not None:
            qr_code = user_input.get("qr_code", "").strip()
            visitor_id_input = user_input.get("visitor_id", "").strip()
            token: str | None = None

            if not qr_code and not visitor_id_input:
                errors["base"] = "qr_or_visitor_required"
            else:
                try:
                    if qr_code:
                        if not qr_code.startswith("RW_Share_"):
                            errors["qr_code"] = "invalid_qr_format"
                        else:
                            new_visitor_id = AwsIotApi.generate_visitor_id()
                            token = await AwsIotApi.authenticate(
                                session, new_visitor_id, api_base=api_base
                            )
                            device_info = await AwsIotApi.bind_qr_code(
                                session,
                                qr_code,
                                new_visitor_id,
                                token,
                                api_base=api_base,
                            )
                            if not device_info:
                                errors["qr_code"] = "binding_failed"
                            else:
                                visitor_id = new_visitor_id
                    else:
                        visitor_id = visitor_id_input
                        token = await AwsIotApi.authenticate(
                            session, visitor_id, api_base=api_base
                        )
                except AwsIotAuthException as auth_err:
                    _LOGGER.error("AWS IoT reauth failed: %s", auth_err)
                    errors["base"] = "auth_failed"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("AWS IoT reauth failed")
                    errors["base"] = "unknown"

                if not errors and token:
                    reauth_entry = self._get_reauth_entry_or_none()
                    if reauth_entry is None:
                        return self.async_abort(reason="reauth_entry_not_found")
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data={
                            **self._reauth_data,
                            "visitor_id": visitor_id,
                            "token": token,
                        },
                    )

        return self.async_show_form(
            step_id="reauth_aws_iot",
            data_schema=vol.Schema(
                {
                    vol.Optional("visitor_id"): str,
                    vol.Optional("qr_code"): str,
                }
            ),
            errors=errors,
        )

    def _get_reauth_entry_or_none(self) -> ConfigEntry | None:
        """Return the config entry being reauthenticated, if it still exists."""
        entry_id = self.context.get("entry_id")
        if entry_id is None:
            return None
        return self.hass.config_entries.async_get_entry(entry_id)


class BestwayOptionsFlowHandler(OptionsFlow):
    """Handle options for an existing Bestway config entry.

    In modern Home Assistant ``self.config_entry`` is a read-only
    property injected by the framework, so we don't override
    ``__init__`` or assign to it here.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_mode = self.config_entry.options.get(
            CONF_BUBBLES_MODE, BUBBLES_MODE_DEFAULT
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BUBBLES_MODE, default=current_mode
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=BUBBLES_MODE_3WAY,
                                    label="3 levels (Off / Medium / Max)",
                                ),
                                selector.SelectOptionDict(
                                    value=BUBBLES_MODE_ONOFF,
                                    label="On / Off only",
                                ),
                            ]
                        )
                    ),
                }
            ),
        )
