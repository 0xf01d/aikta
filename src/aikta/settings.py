from os import environ, getenv
from pathlib import Path
LASTFM_API_KEY = environ["AIKTA_LASTFM_API_KEY"]
CHANNELS = environ["AIKTA_CHANNELS"].split(",")
NICK = getenv("AIKTA_NICK", "aikta")
SERVER = getenv("AIKTA_SERVER", "irc.hackint.org")
PORT = int(getenv("AIKTA_PORT", "6697"))
DATA_DIR = Path(getenv("AIKTA_DATA_DIR", "/data"))
# per-channel command policy: "on" = everything enabled unless disabled per channel,
# "off" = everything disabled unless enabled per channel
CMD_DEFAULT_ON = getenv("AIKTA_CMD_DEFAULT", "on").lower() != "off"
# nick allowed to toggle commands anywhere (channel ops can always)
ADMIN = getenv("AIKTA_ADMIN", "")
