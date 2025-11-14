"""Support for Protege binary sensors (inputs)."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, INPUT_OPEN, INPUT_TAMPER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Protege binary sensors from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    _LOGGER.info("Starting input discovery...")
    
    # Discover inputs
    entities = []
    inputs_found = []
    
    for input_index in range(1, 101):  # Scan inputs 1-100
        try:
            _LOGGER.debug(f"Checking input at index {input_index}...")
            status = await client.get_input_status(input_index)
            
            if status:
                _LOGGER.info(f"Found input at index {input_index}: {status.get('reference', 'N/A')}")
                entities.append(ProtegeInputSensor(coordinator, client, input_index, status))
                inputs_found.append(input_index)
                # Start monitoring
                await client.monitor_input(input_index, True)
            else:
                _LOGGER.debug(f"No input at index {input_index}")
                
        except Exception as e:
            _LOGGER.debug(f"Input {input_index} not accessible: {e}")
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} Protege input sensors: {inputs_found}")
    else:
        _LOGGER.warning("No inputs discovered! Check that inputs are configured in Protege.")


class ProtegeInputSensor(BinarySensorEntity):
    """Representation of a Protege input sensor."""

    def __init__(self, coordinator, client, input_index, initial_status):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._client = client
        self._input_index = input_index
        self._reference = initial_status.get('reference', '').strip()
        
        self._attr_unique_id = f"protege_input_{input_index}"
        self._attr_name = f"Input {self._reference if self._reference else input_index}"
        self._attr_has_entity_name = True
        self._attr_device_class = BinarySensorDeviceClass.MOTION  # Default, can be customized
        
        # Register callback for real-time updates
        client.register_input_callback(self._handle_input_update)
        
        # Initial state
        self._update_from_data()

    @callback
    def _handle_input_update(self, input_status: dict):
        """Handle input status update from client."""
        if input_status['index'] == self._input_index:
            self._update_from_data()
            self.async_write_ha_state()

    def _update_from_data(self):
        """Update entity state from coordinator data."""
        if self._input_index in self._client.inputs:
            input_data = self._client.inputs[self._input_index]
            self._attr_is_on = input_data['is_open']
            self._attr_available = True
            
            # Set extra attributes
            self._attr_extra_state_attributes = {
                "reference": input_data.get('reference', '').strip(),
                "state": input_data['state'],
                "bypassed": input_data['is_bypassed'],
                "tamper": input_data['state'] == INPUT_TAMPER,
            }
        else:
            self._attr_available = False

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"input_{self._input_index}")},
            "name": f"Protege Input {self._reference if self._reference else self._input_index}",
            "manufacturer": "ICT",
            "model": "Protege Input",
        }

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False
