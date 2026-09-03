"""Config flow for the Eastron SDM integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_DEVICE,
    CONF_HOST,
    CONF_MODEL,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from modbus_connection import (
    ModbusConnectionError,
    ModbusError,
    ModbusExceptionError,
    ModbusTimeoutError,
)
import voluptuous as vol

from .connection import SdmParams, build_params, describe
from .const import (
    BAUD_RATES,
    CONF_BAUDRATE,
    CONF_CONNECTION_TYPE,
    CONF_FRAMER,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_UNIT_ID,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_PARITY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STOPBITS,
    DEFAULT_TCP_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    PARITIES,
    STOPBITS,
)
from .sdm import SdmModel, SdmProbe, async_ping, async_probe

_LOGGER = logging.getLogger(__name__)

_UNIT_ID = NumberSelector(
    NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)
)


def _options(values: list[Any]) -> SelectSelector:
    """Return a dropdown over a fixed list, storing the string of each value."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[str(value) for value in values],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class SdmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one Eastron SDM meter."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._data: dict[str, Any] = {}
        self._probe: SdmProbe | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SdmOptionsFlow:
        """Return the options flow."""
        return SdmOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how the meter is reached."""
        return self.async_show_menu(
            step_id="user", menu_options=[CONNECTION_SERIAL, CONNECTION_TCP]
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a meter on an RS485 serial port."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_CONNECTION_TYPE: CONNECTION_SERIAL, **_coerce(user_input)}
            errors = await self._async_try(data)
            if not errors:
                return await self._async_finish()

        return self.async_show_form(
            step_id=CONNECTION_SERIAL,
            data_schema=self.add_suggested_values_to_schema(
                await self._async_serial_schema(), self._suggestions(CONNECTION_SERIAL)
            ),
            errors=errors,
        )

    async def async_step_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a meter reached over TCP, directly or through a gateway."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_CONNECTION_TYPE: CONNECTION_TCP, **_coerce(user_input)}
            errors = await self._async_try(data)
            if not errors:
                return await self._async_finish()

        return self.async_show_form(
            step_id=CONNECTION_TCP,
            data_schema=self.add_suggested_values_to_schema(
                _TCP_SCHEMA, self._suggestions(CONNECTION_TCP)
            ),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which model this is, when the meter did not say.

        Reached when a meter answers the bus but reports no meter code, or one
        this integration does not recognise. That is not a failure: the
        register maps are per model and the user knows which meter they wired.
        """
        if user_input is not None:
            self._data[CONF_MODEL] = user_input[CONF_MODEL]
            return self._async_create()

        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=model, label=model)
                                for model in SdmModel
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={
                "meter_code": (
                    f"0x{self._probe.meter_code:04X}"
                    if self._probe is not None and self._probe.meter_code is not None
                    else "none"
                )
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change an existing meter's link settings or unit ID."""
        entry = self._get_reconfigure_entry()
        self._data = dict(entry.data)
        if entry.data[CONF_CONNECTION_TYPE] == CONNECTION_SERIAL:
            return await self.async_step_serial(user_input)
        return await self.async_step_tcp(user_input)

    # -- helpers --------------------------------------------------------------

    def _suggestions(self, connection_type: str) -> dict[str, Any]:
        """Prefill from this flow, or from a meter already on the same bus.

        Adding the second through sixth meter on one converter should be a
        matter of changing the unit ID, so the last entry configured the same
        way supplies every other field.
        """
        if self._data:
            return self._data
        for entry in reversed(self._async_current_entries()):
            if entry.data.get(CONF_CONNECTION_TYPE) == connection_type:
                return {k: v for k, v in entry.data.items() if k != CONF_UNIT_ID}
        return {}

    async def _async_port_options(self) -> list[SelectOptionDict]:
        """List the serial ports present, best effort.

        pyserial is not a dependency of Home Assistant core or of the Modbus
        integration -- the shared connection manager drives serial ports
        through tmodbus, which uses serialx. It is listed in the manifest so
        it is normally there, but a lean install that lacks it should still be
        able to set a meter up by typing the path.
        """
        try:
            from serial.tools import list_ports
        except ImportError:
            _LOGGER.debug("pyserial is unavailable; serial ports cannot be listed")
            return []

        ports = await self.hass.async_add_executor_job(list_ports.comports)
        return [
            SelectOptionDict(
                value=port.device,
                label=f"{port.device} ({port.description})"
                if port.description and port.description != "n/a"
                else port.device,
            )
            for port in ports
        ]

    async def _async_serial_schema(self) -> vol.Schema:
        """Build the serial form, listing the ports currently present."""
        options = await self._async_port_options()
        device_selector: SelectSelector | TextSelector = (
            SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            )
            if options
            else TextSelector()
        )
        return vol.Schema(
            {
                vol.Required(CONF_DEVICE): device_selector,
                vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): _options(
                    BAUD_RATES
                ),
                vol.Required(CONF_PARITY, default=DEFAULT_PARITY): _options(PARITIES),
                vol.Required(CONF_STOPBITS, default=DEFAULT_STOPBITS): _options(
                    STOPBITS
                ),
                vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): _UNIT_ID,
            }
        )

    async def _async_try(self, data: dict[str, Any]) -> dict[str, str]:
        """Probe the meter described by ``data``; return form errors, if any."""
        try:
            params = build_params(data)
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_link"}

        unit_id = int(data[CONF_UNIT_ID])
        try:
            probe = await self._async_identify(params, unit_id)
        except HomeAssistantError as err:
            # The port is already open under different line settings. Every
            # meter on one bus must agree on baud rate and parity, so this is
            # a wiring truth, not a Home Assistant limitation.
            _LOGGER.debug("Bus settings conflict on %s: %s", describe(params), err)
            return {"base": "bus_settings_conflict"}
        except (ModbusTimeoutError, ModbusConnectionError):
            return {"base": "cannot_connect"}
        except ModbusError as err:
            _LOGGER.debug("Unexpected Modbus error probing %s: %s", unit_id, err)
            return {"base": "cannot_connect"}

        self._data = data
        self._probe = probe
        return {}

    async def _async_identify(self, params: SdmParams, unit_id: int) -> SdmProbe:
        """Read the meter's identity, tolerating a missing device-info block."""
        async with async_get_temporary_unit(self.hass, params, unit_id) as unit:
            try:
                return await async_probe(unit)
            except ModbusExceptionError:
                # The meter answered, but with an exception: it is on the bus
                # and simply does not serve 0xFC00, which the SDM630 V1.8
                # document never promised. Confirm it is alive on a block
                # every model documents, then let the user name the model.
                await async_ping(unit)
                return SdmProbe(
                    serial_number=None,
                    meter_code=None,
                    software_version=None,
                    model=None,
                )

    async def _async_finish(self) -> ConfigFlowResult:
        """Set the unique ID and either create the entry or ask for the model."""
        assert self._probe is not None
        params = build_params(self._data)
        unit_id = int(self._data[CONF_UNIT_ID])

        # A serial number identifies the meter wherever it is moved to. Without
        # one, its position on the bus is the next best thing -- stable as long
        # as the meter stays where it is wired.
        if self._probe.serial_number is not None:
            unique_id = f"{self._probe.serial_number}"
        else:
            unique_id = f"{'-'.join(str(p) for p in params.endpoint)}-{unit_id}"

        await self.async_set_unique_id(unique_id)
        if self.source == "reconfigure":
            entry = self._get_reconfigure_entry()
            self._abort_if_unique_id_mismatch(reason="different_meter")
            return self.async_update_reload_and_abort(entry, data=self._data)

        self._abort_if_unique_id_configured()

        if self._probe.model is None:
            return await self.async_step_model()
        self._data[CONF_MODEL] = self._probe.model
        return self._async_create()

    def _async_create(self) -> ConfigFlowResult:
        """Create the entry."""
        model = self._data[CONF_MODEL]
        unit_id = int(self._data[CONF_UNIT_ID])
        return self.async_create_entry(title=f"{model} ({unit_id})", data=self._data)


class SdmOptionsFlow(OptionsFlow):
    """Adjust how often a meter is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the scan interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_SCAN_INTERVAL,
                                max=MAX_SCAN_INTERVAL,
                                step=1,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement="s",
                            )
                        )
                    }
                ),
                {
                    CONF_SCAN_INTERVAL: self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    )
                },
            ),
        )


_TCP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(),
        vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_FRAMER, default="socket"): SelectSelector(
            SelectSelectorConfig(
                options=["socket", "rtu"],
                mode=SelectSelectorMode.LIST,
                translation_key="framer",
            )
        ),
        vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): _UNIT_ID,
    }
)

#: Fields the selectors hand back as strings or floats but that belong in the
#: entry as integers, so that two entries built from the same form always
#: produce identical connection parameters and therefore share a connection.
_INTEGERS = (CONF_BAUDRATE, CONF_STOPBITS, CONF_UNIT_ID, CONF_PORT)


def _coerce(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise form input to the types stored in the config entry."""
    return {
        key: int(value) if key in _INTEGERS else value
        for key, value in user_input.items()
    }
