"""Config flow for the Eastron SDM integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
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
from .sdm import (
    SdmModel,
    SdmProbe,
    async_ping,
    async_probe,
    contradicting_model,
    provisional_model,
)

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
        self._released = False

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
            data = self._merge(CONNECTION_SERIAL, user_input)
            errors = await self._async_try(data)
            if not errors:
                return await self._async_finish()

        return self.async_show_form(
            step_id=CONNECTION_SERIAL,
            data_schema=self.add_suggested_values_to_schema(
                await self._async_serial_schema(),
                self._suggestions(CONNECTION_SERIAL, user_input),
            ),
            errors=errors,
        )

    async def async_step_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a meter reached over TCP, directly or through a gateway."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._merge(CONNECTION_TCP, user_input)
            errors = await self._async_try(data)
            if not errors:
                return await self._async_finish()

        return self.async_show_form(
            step_id=CONNECTION_TCP,
            data_schema=self.add_suggested_values_to_schema(
                _TCP_SCHEMA, self._suggestions(CONNECTION_TCP, user_input)
            ),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which model this is, when the meter's answer is not enough.

        Four situations reach here and they read very differently to a user,
        so each gets its own wording through its own step id.

        A meter that reports no code at all is the documented, expected path
        for the SDM120CT and SDM230, whose manuals define no meter code --
        telling those users their meter "reported model code none, which this
        integration does not recognise" would describe correct hardware as a
        fault. A meter that reports a code this integration does not know is
        the genuinely unexpected one, and worth quoting the code back. A meter
        reporting a code seen in the field but not in any manual is the third,
        and gets that report offered as a preselection. A meter that
        contradicts the model an existing entry is set to is the fourth: only
        reachable from a reconfigure.

        None of the four is a failure: the register maps are per model and the
        user knows which meter they wired.
        """
        if user_input is not None:
            self._data[CONF_MODEL] = user_input[CONF_MODEL]
            return self._async_save()

        # A zero is not a code. A meter whose manual defines none may either
        # refuse the register outright or answer it with zero, and both mean
        # the same thing to the user; only the diagnostics dump keeps the raw
        # value, where the distinction might matter to a bug report.
        code = (self._probe.meter_code if self._probe is not None else None) or None
        contradiction = self._contradiction()
        detected = None

        if contradiction is not None:
            reported, detected = contradiction
            step_id = "model_mismatch"
            placeholders = {
                "meter_code": f"0x{reported:04X}",
                "detected": str(detected),
                "configured": str(self._data[CONF_MODEL]),
            }
        elif code is None:
            step_id = "model"
            placeholders = {}
        elif (suggested := provisional_model(code)) is not None:
            # Seen in the field on this model, but no manual says so. Offered,
            # never applied: a code that decides on its own has to be one the
            # hardware cannot contradict, and this one is a single report.
            detected = suggested
            step_id = "model_provisional_code"
            placeholders = {
                "meter_code": f"0x{code:04X}",
                "detected": str(suggested),
            }
        else:
            step_id = "model_unknown_code"
            placeholders = {"meter_code": f"0x{code:04X}"}
            # The only durable record of the code. It is otherwise quoted just
            # in this dialog, which the user dismisses by answering it, and in
            # a diagnostics dump nobody downloads for a flow that succeeded --
            # so without this line every field report starts by asking the user
            # to reproduce a form they have already got past.
            _LOGGER.warning(
                "Meter on unit %s reported unrecognised meter code 0x%04X. "
                "Setup continues with the model you choose; please report that "
                "code together with the model printed on the meter, so it can "
                "be detected automatically",
                self._data.get(CONF_UNIT_ID),
                code,
            )

        schema = vol.Schema(
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
        )
        # Preselected only where there is something to preselect. Leaving the
        # list unset elsewhere makes the user choose rather than accept a
        # default this integration has no basis for.
        if detected is not None:
            schema = self.add_suggested_values_to_schema(
                schema, {CONF_MODEL: str(detected)}
            )

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders=placeholders,
        )

    async def async_step_model_unknown_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the model step for a meter that reported an unknown code.

        Same question and same handling; it exists so that variant can carry
        its own wording, which is keyed by step id.
        """
        return await self.async_step_model(user_input)

    async def async_step_model_provisional_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the model step for a code seen in the field but undocumented.

        Same question and same handling, its own wording; see
        ``async_step_model``.
        """
        return await self.async_step_model(user_input)

    async def async_step_model_mismatch(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the model step for a meter that contradicts its entry.

        Same question and same handling, its own wording; see
        ``async_step_model``.
        """
        return await self.async_step_model(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change an existing meter's link settings or unit ID."""
        entry = self._get_reconfigure_entry()
        if not self._data:
            self._data = dict(entry.data)
        if entry.data[CONF_CONNECTION_TYPE] == CONNECTION_SERIAL:
            return await self.async_step_serial(user_input)
        return await self.async_step_tcp(user_input)

    # -- helpers --------------------------------------------------------------

    def _merge(
        self, connection_type: str, user_input: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Fold this form's answers into what the flow already knows.

        The form only carries link settings, so a reconfigure would otherwise
        drop everything not on it -- the model above all, without which the
        entry cannot be set up again at all.
        """
        return {
            **self._data,
            CONF_CONNECTION_TYPE: connection_type,
            **_coerce(user_input),
        }

    def _suggestions(
        self, connection_type: str, user_input: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Prefill the form, most specific source first.

        After a failed probe that is what the user just typed, so a wrong baud
        rate does not cost them the device path as well. Otherwise it is this
        flow's own data (a reconfigure, or the entry being edited), and failing
        that the last meter configured the same way -- which is what makes
        adding the second through sixth meter on one converter a matter of
        changing the unit ID.
        """
        source: dict[str, Any]
        if user_input is not None:
            source = dict(user_input)
        elif self._data:
            source = dict(self._data)
        else:
            source = {}
            for entry in reversed(self._async_current_entries()):
                if entry.data.get(CONF_CONNECTION_TYPE) == connection_type:
                    source = {k: v for k, v in entry.data.items() if k != CONF_UNIT_ID}
                    break

        # The dropdowns are string-valued, so an int suggestion matches no
        # option and the field renders unset.
        return {
            key: str(value) if key in _SELECT_INTEGERS else value
            for key, value in source.items()
        }

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
                # The defaults are strings to match the selector's options;
                # `_coerce` turns them back into integers for the entry.
                vol.Required(CONF_BAUDRATE, default=str(DEFAULT_BAUDRATE)): _options(
                    BAUD_RATES
                ),
                vol.Required(CONF_PARITY, default=DEFAULT_PARITY): _options(PARITIES),
                vol.Required(CONF_STOPBITS, default=str(DEFAULT_STOPBITS)): _options(
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
        await self._async_release_own_connection()
        try:
            probe = await self._async_identify(params, unit_id)
        except HomeAssistantError as err:
            # The port is already open under different line settings. Every
            # meter on one bus must agree on baud rate and parity, so this is
            # a wiring truth, not a Home Assistant limitation.
            _LOGGER.debug("Bus settings conflict on %s: %s", describe(params), err)
            return self._async_failed({"base": "bus_settings_conflict"})
        except (ModbusTimeoutError, ModbusConnectionError):
            return self._async_failed({"base": "cannot_connect"})
        except ModbusError as err:
            _LOGGER.debug("Unexpected Modbus error probing %s: %s", unit_id, err)
            return self._async_failed({"base": "cannot_connect"})

        self._data = data
        self._probe = probe
        return {}

    async def _async_release_own_connection(self) -> None:
        """Unload the entry being reconfigured before probing it.

        Its own connection is still open on this port with the old line
        settings, and the shared connection manager refuses a second set of
        settings on one endpoint. Without letting go first, changing a baud
        rate -- the thing this step exists for -- could only ever report a
        conflict with itself.
        """
        if self.source != SOURCE_RECONFIGURE:
            return
        entry = self._get_reconfigure_entry()
        if entry.state is ConfigEntryState.LOADED:
            await self.hass.config_entries.async_unload(entry.entry_id)
            self._released = True

    @callback
    def _async_failed(self, errors: dict[str, str]) -> dict[str, str]:
        """Put a reconfigured entry back the way it was after a failed probe."""
        if self.source == SOURCE_RECONFIGURE:
            self._async_restore()
        return errors

    @callback
    def _async_restore(self) -> None:
        """Reload the entry this flow unloaded, if it still owes it one."""
        if not self._released:
            return
        self._released = False
        self.hass.config_entries.async_schedule_reload(
            self._get_reconfigure_entry().entry_id
        )

    @callback
    def async_remove(self) -> None:
        """Reload a reconfigured entry if the flow was abandoned.

        The flow unloads the entry to free the port before probing, and the
        model step can leave the user sitting on a form afterwards. Closing
        that dialog must not leave their meter dark until the next restart.

        Called on every removal, including a successful one -- which is why
        finishing clears the debt first, so this reloads nothing twice.
        """
        self._async_restore()

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
                if await async_ping(unit) is None:
                    # Something is at this address, but it did not answer the
                    # one block every SDM documents with anything an SDM could
                    # report. Refusing both blocks is what a device of another
                    # make looks like -- most often a unit ID typed wrong --
                    # and offering to set it up as a meter would hand the user
                    # an entry whose every reading is decoded from registers
                    # that mean something else. Re-raising puts them back on
                    # the form with "cannot connect", which is the truth.
                    raise
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
        serial_number = self._probe.serial_number

        if self.source == SOURCE_RECONFIGURE:
            if serial_number is not None:
                # A serial number identifies the meter itself, so it is worth
                # refusing an entry that has been pointed at a different one:
                # its history would silently continue under the wrong meter.
                await self.async_set_unique_id(str(serial_number))
                self._abort_if_unique_id_mismatch(reason="different_meter")
            # A meter with no serial number is only identified by where it sits
            # on the bus, which is exactly what this step changes -- so there is
            # nothing here to compare, and the entry keeps the ID it has.
            if self._contradiction() is not None:
                # The meter says it is not what the entry claims. Offered, not
                # applied: the code for the SDM630 is a field report rather
                # than a documented one, so a user who overrode it deliberately
                # must not have that overridden on the way past.
                return await self.async_step_model()
            return self._async_save()

        # A serial number identifies the meter wherever it is moved to. Without
        # one, its position on the bus is the next best thing -- stable as long
        # as the meter stays where it is wired.
        if serial_number is not None:
            unique_id = str(serial_number)
        else:
            unique_id = f"{'-'.join(str(p) for p in params.endpoint)}-{unit_id}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        if self._probe.model is None:
            return await self.async_step_model()
        self._data[CONF_MODEL] = self._probe.model
        return self._async_save()

    @callback
    def _contradiction(self) -> tuple[int, SdmModel] | None:
        """Return the code the meter reports and what it names, if they clash.

        ``None`` unless the meter reported a code for a model read differently
        from the one the entry is set to. Only ever true on a reconfigure: a
        new entry has no configured model to be contradicted, and takes the
        probe's answer where there is one.

        The code comes back alongside the model because it is quoted to the
        user, and pairing them here is what keeps that quote from having to
        cope with a code that cannot be absent.
        """
        if self._probe is None or CONF_MODEL not in self._data:
            return None
        code = self._probe.meter_code
        detected = contradicting_model(code, SdmModel(self._data[CONF_MODEL]))
        if code is None or detected is None:
            return None
        return code, detected

    def _title(self) -> str:
        """Name the entry for its model and its place on the bus."""
        return f"{self._data[CONF_MODEL]} ({int(self._data[CONF_UNIT_ID])})"

    def _async_save(self) -> ConfigFlowResult:
        """Create the entry, or update the one being reconfigured.

        Clears the reload this flow owes the entry first: the update reloads
        it, and ``async_remove`` must not schedule a second one behind it.
        """
        if self.source == SOURCE_RECONFIGURE:
            self._released = False
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=self._data, title=self._title()
            )
        return self.async_create_entry(title=self._title(), data=self._data)


class SdmOptionsFlow(OptionsFlowWithReload):
    """Adjust how often a meter is polled.

    ``OptionsFlowWithReload`` reloads the entry when the options change, so the
    integration does not register an update listener of its own.
    """

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

#: Of those, the ones backed by a string-valued dropdown, whose suggestions
#: have to be stringified again on the way back into the form.
_SELECT_INTEGERS = (CONF_BAUDRATE, CONF_STOPBITS)


def _coerce(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise form input to the types stored in the config entry."""
    return {
        key: int(value) if key in _INTEGERS else value
        for key, value in user_input.items()
    }
