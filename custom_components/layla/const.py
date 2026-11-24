"""Constants for the Layla integration."""

DOMAIN = "layla"

# Layla's cloud as Layla's own web app uses it: its REST API, and its sign-in (an AWS Cognito user pool with a
# public app client). Each can be replaced when the integration is added, in Home Assistant's advanced mode.
DEFAULT_API_URL = "https://api.laylaelectric.com/api"
DEFAULT_REGION = "eu-west-1"
DEFAULT_USER_POOL_ID = "eu-west-1_VmRA1i4Vy"
DEFAULT_CLIENT_ID = "258587iubfts9ho9eraona7g1l"

# Config entry data
CONF_REFRESH_TOKEN = "refresh_token"
CONF_API_URL = "api_url"
CONF_REGION = "region"
CONF_USER_POOL_ID = "user_pool_id"
CONF_CLIENT_ID = "client_id"

# Options (Settings → Devices & services → Layla → Configure)
CONF_UPDATE_MINUTES = "update_minutes"
CONF_ONLINE_MINUTES = "online_minutes"
CONF_PROPERTIES = "properties"
CONF_PROPERTY_IN_NAME = "property_in_name"
CONF_READINGS = "readings"
CONF_ALARMS = "alarms"
CONF_DEVICE_ALARMS = "device_alarms"

# How often readings are fetched by default, and the range allowed. Layla's sensors report about every 5 minutes;
# each update is one request for the account's settings, one for the properties, and one per property.
DEFAULT_UPDATE_MINUTES = 2
UPDATE_MINUTES_RANGE = (1, 60)
# Layla's answer has no connection status: a device that reported within this many minutes counts as online.
DEFAULT_ONLINE_MINUTES = 60
ONLINE_MINUTES_RANGE = (5, 1440)

MANUFACTURER = "LaylaElectric"
