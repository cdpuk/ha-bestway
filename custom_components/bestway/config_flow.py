"""Config flow for Bestway integration."""

from __future__ import annotations

import asyncio
from logging import getLogger

from typing import Any

from aiohttp import ClientConnectionError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
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
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_API_ROOT_US,
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
                                        label="V01 - Bestway Connect / Lay-Z-Spa WiFi (Gizwits)",
                                    ),
                                    selector.SelectOptionDict(
                                        value=BACKEND_AWS_IOT,
                                        label="V02 - Bestway Smart Spa app (AWS IoT)",
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
                                    selector.SelectOptionDict(value="EU", label="Europe"),
                                    selector.SelectOptionDict(value="US", label="United States"),
                                    selector.SelectOptionDict(value="CN", label="China"),
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
                                    selector.SelectOptionDict(value="EU", label="Europe"),
                                    selector.SelectOptionDict(value="US", label="United States"),
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
                token = await AwsIotApi.authenticate(session, visitor_id, api_base=api_base)

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
                token = await AwsIotApi.authenticate(session, visitor_id, api_base=api_base)

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
                                selector.SelectOptionDict(value="US", label="United States"),
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
