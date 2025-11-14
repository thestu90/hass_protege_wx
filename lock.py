"""Support for Protege door locks."""
import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DOOR_LOCKED

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Protege locks from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    _LOGGER.info("Starting door discovery...")
    
    # Discover doors - try a wider range
    entities = []
    doors_found = []
    
    for door_index in range(1, 51):  # Scan doors 1-50
        try:
            _LOGGER.debug(f"Checking door at index {door_index}...")
            status = await client.get_door_status(door_index)
            
            if status:
                _LOGGER.info(f"Found door at index {door_index}: {status}")
                entities.append(ProtegeDoorLock(coordinator, client, door_index))
                doors_found.append(door_index)
                # Start monitoring
                await client.monitor_door(door_index, True)
            else:
                _LOGGER.debug(f"No door at index {door_index}")
                
        except Exception as e:
            _LOGGER.debug(f"Door {door_index} not accessible: {e}")
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} Protege door locks: {doors_found}")
    else:
        _LOGGER.warning("No doors discovered! Check that doors are configured in Protege and try different index ranges.")


class ProtegeDoorLock(LockEntity):
    """Representation of a Protege door lock."""

    def __init__(self, coordinator, client, door_index):
        """Initialize the lock."""
        self.coordinator = coordinator
        self._client = client
        self._door_index = door_index
        self._attr_unique_id = f"protege_door_{door_index}"
        self._attr_name = f"Door {door_index}"
        self._attr_has_entity_name = True
        
        # Register callback for real-time updates
        client.register_door_callback(self._handle_door_update)
        
        # Initial state
        self._update_from_data()

    @callback
    def _handle_door_update(self, door_status: dict):
        """Handle door status update from client."""
        if door_status['index'] == self._door_index:
            self._update_from_data()
            self.async_write_ha_state()

    def _update_from_data(self):
        """Update entity state from coordinator data."""
        if self._door_index in self._client.doors:
            door_data = self._client.doors[self._door_index]
            self._attr_is_locked = door_data['is_locked']
            self._attr_is_jammed = door_data['door_state'] == 4  # FORCED_OPEN
            self._attr_available = True
        else:
            self._attr_available = False

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"door_{self._door_index}")},
            "name": f"Protege Door {self._door_index}",
            "manufacturer": "ICT",
            "model": "Protege Door",
        }

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the door."""
        success = await self._client.lock_door(self._door_index)
        if success:
            self._attr_is_locked = True
            self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door (momentary)."""
        success = await self._client.unlock_door(self._door_index)
        if success:
            # Door will auto-lock after 5 seconds, but update state immediately
            self._attr_is_locked = False
            self.async_write_ha_state()

    async def async_open(self, **kwargs: Any) -> None:
        """Open the door (unlock latched)."""
        success = await self._client.unlock_door_latched(self._door_index)
        if success:
            self._attr_is_locked = False
            self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False
