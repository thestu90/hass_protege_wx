"""Support for Protege sensors (events and system info)."""
import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Protege sensors from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Create event sensor
    entities = [
        ProtegeEventSensor(coordinator, client),
        ProtegeSystemSensor(coordinator, client),
    ]
    
    async_add_entities(entities)
    _LOGGER.info("Added Protege event and system sensors")


class ProtegeEventSensor(SensorEntity):
    """Sensor for Protege system events."""

    def __init__(self, coordinator, client):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._client = client
        
        self._attr_unique_id = "protege_events"
        self._attr_name = "Protege Events"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:information-outline"
        
        self._events = []
        self._last_event = None
        
        # Register callback for events
        client.register_event_callback(self._handle_event)

    @callback
    def _handle_event(self, event_text: str):
        """Handle event from client."""
        self._last_event = event_text
        self._events.append({
            "timestamp": datetime.now().isoformat(),
            "event": event_text,
        })
        
        # Keep only last 50 events
        if len(self._events) > 50:
            self._events = self._events[-50:]
        
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._last_event if self._last_event else "No events"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "events": self._events,
            "event_count": len(self._events),
        }

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, "protege_system")},
            "name": "Protege System",
            "manufacturer": "ICT",
            "model": "Protege WX",
        }

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False


class ProtegeSystemSensor(SensorEntity):
    """Sensor for Protege system status."""

    def __init__(self, coordinator, client):
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._client = client
        
        self._attr_unique_id = "protege_system_status"
        self._attr_name = "Protege System Status"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:shield-check"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self._client.is_connected():
            return "Connected"
        return "Disconnected"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "connected": self._client.connected,
            "logged_in": self._client.logged_in,
            "doors": len(self._client.doors),
            "inputs": len(self._client.inputs),
            "outputs": len(self._client.outputs),
            "areas": len(self._client.areas),
        }

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, "protege_system")},
            "name": "Protege System",
            "manufacturer": "ICT",
            "model": "Protege WX",
        }

    @property
    def should_poll(self) -> bool:
        """Poll for system status updates."""
        return True
