"""The top-level device object an application constructs from a ModbusUnit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from modbus_connection import ModbusError
from modbus_connection.model import Component

from .const import BAUD_RATES, METER_CODES, PARITY_STOP, SdmModel
from .identity import SdmDeviceInfo, SdmNetworkSettings
from .sdm72d import Sdm72dMeasurements, Sdm72dmV2Measurements
from .sdm120 import Sdm120Measurements
from .sdm230 import Sdm230Measurements
from .sdm630 import Sdm630Measurements
from .sdm630mct import Sdm630MctMeasurements

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

#: The measurement component for each model. Adding another is a new module
#: plus one line here, and its meter code in ``const.METER_CODES``.
#:
#: The SDM120CT map is identical to the SDM120's -- the CT variant changes how
#: current is sensed, not which registers report it -- so it shares the
#: component while keeping its own model name for the device page.
MEASUREMENTS: dict[SdmModel, type[Component]] = {
    SdmModel.SDM120: Sdm120Measurements,
    SdmModel.SDM120CT: Sdm120Measurements,
    SdmModel.SDM230: Sdm230Measurements,
    SdmModel.SDM630: Sdm630Measurements,
    SdmModel.SDM630MCT: Sdm630MctMeasurements,
    SdmModel.SDM72D: Sdm72dMeasurements,
    SdmModel.SDM72DM_V2: Sdm72dmV2Measurements,
}


@dataclass(frozen=True, kw_only=True)
class SdmInfo:
    """What the meter says about itself, read once at setup."""

    model: SdmModel
    serial_number: int | None = None
    software_version: int | None = None
    meter_code: int | None = None
    node_address: int | None = None
    baud_rate: int | None = None
    parity: str | None = None
    stopbits: int | None = None

    @property
    def software_version_str(self) -> str | None:
        """The firmware version as the meter's display shows it."""
        if self.software_version is None:
            return None
        return f"{self.software_version >> 8}.{self.software_version & 0xFF}"


class SdmMeter:
    """One Eastron SDM meter on a Modbus unit.

    Takes a ``ModbusUnit`` and nothing else -- never a connection, never a
    host or a serial port. Who owns the link, and how many other meters share
    it, is the caller's business.
    """

    def __init__(self, unit: ModbusUnit, model: SdmModel) -> None:
        """Build the components this model needs on ``unit``."""
        self.model = model
        self.measurements = MEASUREMENTS[model](unit)
        self.network = SdmNetworkSettings(unit)
        self.identity = SdmDeviceInfo(unit)
        self._info = SdmInfo(model=model)

    @property
    def info(self) -> SdmInfo:
        """Identity and link settings, populated by ``async_setup``."""
        return self._info

    @property
    def fields(self) -> tuple[str, ...]:
        """The measurement field names this model declares."""
        return tuple(self.measurements.declared_fields)

    def value(self, field: str) -> float | None:
        """Return the last decoded value of a measurement field."""
        return cast("float | None", getattr(self.measurements, field))

    async def async_setup(self) -> None:
        """Read identity and link settings once.

        Both blocks are optional: the SDM630 V1.8 document does not describe
        the ``0xFC00`` device-info block at all, and a meter that answers it
        with an exception is not broken. A failure here leaves the affected
        fields as ``None`` rather than failing setup, because none of them are
        needed to read measurements.
        """
        self._info = await self._async_read_identity()

    async def async_update(self) -> None:
        """Poll every measurement register for this model."""
        await self.measurements.async_update()

    async def _async_read_identity(self) -> SdmInfo:
        model = self.model
        serial_number = software_version = meter_code = None
        node_address = baud_rate = None
        parity: str | None = None
        stopbits: int | None = None

        try:
            await self.identity.async_update()
        except ModbusError:
            pass
        else:
            serial_number = self.identity.serial_number
            meter_code = self.identity.meter_code
            software_version = self.identity.software_version

        try:
            await self.network.async_update()
        except ModbusError:
            pass
        else:
            if (node := self.network.node_address) is not None:
                node_address = int(node)
            if (baud := self.network.baud_rate) is not None:
                baud_rate = BAUD_RATES.get(int(baud))
            if (encoded := self.network.parity_stop) is not None:
                parity, stopbits = PARITY_STOP.get(int(encoded), (None, None))

        return SdmInfo(
            model=model,
            serial_number=serial_number,
            software_version=software_version,
            meter_code=meter_code,
            node_address=node_address,
            baud_rate=baud_rate,
            parity=parity,
            stopbits=stopbits,
        )


@dataclass(frozen=True, kw_only=True)
class SdmProbe:
    """What a pre-setup read of the device-info block found."""

    serial_number: int | None
    meter_code: int | None
    software_version: int | None
    model: SdmModel | None

    @property
    def identified(self) -> bool:
        """Whether both the model and a serial number came back."""
        return self.model is not None and self.serial_number is not None


async def async_probe(unit: ModbusUnit) -> SdmProbe:
    """Identify the meter on ``unit``, before its model is known.

    Reads only the device-info block, which is model independent. Raises the
    underlying ``ModbusError`` if the meter does not answer at all -- that is
    the caller's "is anything there?" signal. A meter that answers the bus but
    reports an unrecognised meter code comes back with ``model=None``, which
    means "ask the user", not "unsupported".
    """
    info = SdmDeviceInfo(unit)
    await info.async_update()
    code = info.meter_code
    return SdmProbe(
        serial_number=info.serial_number,
        meter_code=code,
        software_version=info.software_version,
        model=METER_CODES.get(code) if code is not None else None,
    )


async def async_ping(unit: ModbusUnit) -> int | None:
    """Confirm a meter is answering on ``unit``, returning its node address.

    The network-settings block is documented for every SDM model, unlike the
    ``0xFC00`` device-info block, so this answers "is a meter there?" for a
    meter that ``async_probe`` could not identify. Raises the underlying
    ``ModbusError`` when nothing answers.
    """
    network = SdmNetworkSettings(unit)
    await network.async_update()
    node = network.node_address
    return int(node) if node is not None else None
