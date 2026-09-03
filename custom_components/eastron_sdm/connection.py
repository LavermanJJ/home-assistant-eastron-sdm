"""Turn stored config-entry data into Modbus connection parameters.

Shared by setup and the config flow so a meter is always addressed the same
way whether it is being probed or polled -- which matters more than it looks:
the shared connection manager keys on these parameters, and two callers that
build them differently would be handed two different connections to the same
port.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT
from modbus_connection import ModbusSerialParams, ModbusTcpParams

from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION_TYPE,
    CONF_FRAMER,
    CONF_PARITY,
    CONF_STOPBITS,
    CONNECTION_SERIAL,
    DEFAULT_BAUDRATE,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DEFAULT_TCP_PORT,
)

type SdmParams = ModbusSerialParams | ModbusTcpParams


def build_params(data: dict[str, Any]) -> SdmParams:
    """Build connection parameters from config-entry data.

    Raises ``KeyError`` or ``ValueError`` on data that cannot describe a link.
    """
    if data[CONF_CONNECTION_TYPE] == CONNECTION_SERIAL:
        return ModbusSerialParams(
            device=str(data[CONF_DEVICE]),
            baudrate=int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            # Every SDM parameter is a 32-bit float in two 8-bit-per-byte
            # registers; the protocol documents no 7-bit mode, so bytesize is
            # not offered and not stored.
            bytesize=8,
            parity=cast(
                Literal["N", "E", "O"], str(data.get(CONF_PARITY, DEFAULT_PARITY))
            ),
            stopbits=cast(
                Literal[1, 2], int(data.get(CONF_STOPBITS, DEFAULT_STOPBITS))
            ),
            framer="rtu",
        )
    return ModbusTcpParams(
        host=str(data[CONF_HOST]),
        port=int(data.get(CONF_PORT, DEFAULT_TCP_PORT)),
        # A serial gateway (ser2net, Waveshare, USR) tunnels RTU frames over
        # TCP and needs "rtu"; a native Modbus TCP meter such as the
        # SDM630-TCP speaks MBAP and needs "socket".
        framer=cast(Literal["socket", "rtu"], str(data.get(CONF_FRAMER, "socket"))),
    )


def describe(params: SdmParams) -> str:
    """Return a short name for the link, for entry titles and log lines."""
    if isinstance(params, ModbusSerialParams):
        return params.device
    return f"{params.host}:{params.port}"
