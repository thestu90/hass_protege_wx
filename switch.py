"""Support for Protege switches (outputs)."""
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, OUTPUT_OFF

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Protege switches from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    _LOGGER.info("Starting output discovery...")
    
    # Discover outputs
    entities = []
    outputs_found = []
    
    for output_index in range(1, 101):  # Scan outputs 1-100
        try:
            _LOGGER.debug(f"Checking output at index {output_index}...")
            status = await client.get_output_status(output_index)
            
            if status:
                _LOGGER.info(f"Found output at index {output_index}: {status.get('reference', 'N/A')}")
                entities.append(ProtegeOutputSwitch(coordinator, client, output_index, status))
                outputs_found.append(output_index)
                # Start monitoring
                await client.monitor_output(output_index, True)
            else:
                _LOGGER.debug(f"No output at index {output_index}")
                
        except Exception as e:
            _LOGGER.debug(f"Output {output_index} not accessible: {e}")
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} Protege output switches: {outputs_found}")
    else:
        _LOGGER.warning("No outputs discovered! Check that outputs are configured in Protege.")


class ProtegeOutputSwitch(SwitchEntity):
    """Representation of a Protege output switch."""

    def __init__(self, coordinator, client, output_index, initial_status):
        """Initialize the switch."""
        self.coordinator = coordinator
        self._client = client
        self._output_index = output_index
        self._reference = initial_status.get('reference', '').strip()
        
        self._attr_unique_id = f"protege_output_{output_index}"
        self._attr_name = f"Output {self._reference if self._reference else output_index}"
        self._attr_has_entity_name = True
        
        # Register callback for real-time updates
        client.register_output_callback(self._handle_output_update)
        
        # Initial state
        self._update_from_data()

    @callback
    def _handle_output_update(self, output_status: dict):
        """Handle output status update from client."""
        if output_status['index'] == self._output_index:
            self._update_from_data()
            self.async_write_ha_state()

    def _update_from_data(self):
        """Update entity state from coordinator data."""
        if self._output_index in self._client.outputs:
            output_data = self._client.outputs[self._output_index]
            self._attr_is_on = output_data['is_on']
            self._attr_available = True
            
            # Set extra attributes
            self._attr_extra_state_attributes = {
                "reference": output_data.get('reference', '').strip(),
                "state": output_data['state'],
            }
        else:
            self._attr_available = False

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"output_{self._output_index}")},
            "name": f"Protege Output {self._reference if self._reference else self._output_index}",
            "manufacturer": "ICT",
            "model": "Protege Output",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the output on."""
        success = await self._client.output_on(self._output_index)
        if success:
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the output off."""
        success = await self._client.output_off(self._output_index)
        if success:
            self._attr_is_on = False
            self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False
