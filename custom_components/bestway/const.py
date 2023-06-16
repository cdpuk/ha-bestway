"""Constants for the bestway integration."""

from enum import Enum

DOMAIN = "bestway"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_API_ROOT = "apiroot"
CONF_API_ROOT_EU = "https://euapi.gizwits.com"
CONF_API_ROOT_US = "https://usapi.gizwits.com"
CONF_USER_TOKEN = "user_token"
CONF_USER_TOKEN_EXPIRY = "user_token_expiry"


class Icon(str, Enum):
    """Icon styles."""

    HARDWARE = "mdi:chip"
    SOFTWARE = "mdi:application-braces"
    PROTOCOL = "mdi:protocol"
