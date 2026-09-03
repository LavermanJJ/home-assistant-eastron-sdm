"""Constants for the Eastron SDM integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "eastron_sdm"

MANUFACTURER: Final = "Eastron"

CONF_CONNECTION_TYPE: Final = "connection_type"
CONF_BAUDRATE: Final = "baudrate"
CONF_PARITY: Final = "parity"
CONF_STOPBITS: Final = "stopbits"
CONF_FRAMER: Final = "framer"
CONF_UNIT_ID: Final = "unit_id"

CONNECTION_SERIAL: Final = "serial"
CONNECTION_TCP: Final = "tcp"

# The SDM range supports 2400..38400; 1200 exists on the SDM120 only. Listed
# newest-first because 9600 is the SDM630 default and the usual choice.
BAUD_RATES: Final = [9600, 38400, 19200, 4800, 2400, 1200]
PARITIES: Final = ["N", "E", "O"]
STOPBITS: Final = [1, 2]

DEFAULT_BAUDRATE: Final = 9600
DEFAULT_PARITY: Final = "N"
DEFAULT_STOPBITS: Final = 1
DEFAULT_TCP_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 1

# A poll is four block reads per meter. At 2400 baud with a long daisy chain
# that is roughly a second per meter, and every meter on a port queues behind
# the others on one shared connection -- hence a floor well above what a
# single meter could sustain.
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600
