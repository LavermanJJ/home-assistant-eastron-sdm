"""Eastron SDM energy meters over Modbus.

A self-contained device library built on ``modbus-connection``. It imports no
Home Assistant, so it can be lifted into its own PyPI package unchanged if
this integration is ever submitted to core, where ADR-0004 requires device
communication to live outside the integration.

Register maps are transcribed from the Eastron protocol documents; see
``docs/README.md`` for the exact versions and the module docstrings for the
section each map came from.
"""

from __future__ import annotations

from .const import (
    BAUD_RATES,
    METER_CODES,
    PARITY_STOP,
    PROVISIONAL_METER_CODES,
    SdmModel,
)
from .meter import (
    MEASUREMENTS,
    SdmInfo,
    SdmMeter,
    SdmProbe,
    async_ping,
    async_probe,
    contradicting_model,
    provisional_model,
)

__all__ = [
    "BAUD_RATES",
    "MEASUREMENTS",
    "METER_CODES",
    "PARITY_STOP",
    "PROVISIONAL_METER_CODES",
    "SdmInfo",
    "SdmMeter",
    "SdmModel",
    "SdmProbe",
    "async_ping",
    "async_probe",
    "contradicting_model",
    "provisional_model",
]
