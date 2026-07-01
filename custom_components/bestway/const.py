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
CONF_UID = "uid"
GIZWITS_APP_ID = "98754e684ec045528b073876c34c7348"

# Backend types
BACKEND_GIZWITS = "gizwits"
BACKEND_AWS_IOT = "aws_iot"

# Fix B - delay (seconds) before re-fetching the reported shadow to confirm a
# command converged. Longer than the entity optimistic window (~8s) so the check
# runs after it, short enough to be actionable.
COMMAND_CONVERGENCE_DELAY_S = 10

# Fix B - event fired on the HA bus when a command does not converge, so
# automations (e.g. spa Tier C ready-by / away-setback) can alert instead of
# trusting an optimistic tile. Event data: {"device_id", "unconverged"}.
EVENT_COMMAND_UNCONVERGED = "bestway_command_unconverged"

# Bubble UI mode (Airjet V02). Some V02 hardware (e.g. T53NN8 batches)
# only has on/off bubbles physically, while others support 3 levels.
# The product_id doesn't distinguish them, so the user picks.
CONF_BUBBLES_MODE = "bubbles_mode"
BUBBLES_MODE_3WAY = "three_way"
BUBBLES_MODE_ONOFF = "on_off"
BUBBLES_MODE_DEFAULT = BUBBLES_MODE_3WAY


class Icon(str, Enum):
    """Icon styles."""

    BUBBLES = "mdi:chart-bubble"
    FILTER = "mdi:image-filter-tilt-shift"
    HARDWARE = "mdi:chip"
    JETS = "mdi:turbine"
    LOCK = "mdi:lock"
    POWER = "mdi:power"
    PROTOCOL = "mdi:protocol"
    SOFTWARE = "mdi:application-braces"
