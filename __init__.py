"""Protege WX Integration for Home Assistant."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_PIN
from .protege_client import ProtegeClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LOCK, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Protege from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    pin = entry.data[CONF_PIN]

    _LOGGER.info(f"Setting up Protege integration for {host}:{port}")
    
    client = ProtegeClient(host, port, pin)
    
    try:
        _LOGGER.info("Attempting to connect to Protege system...")
        if not await client.connect():
            _LOGGER.error("Failed to connect to Protege - check network connectivity")
            raise ConfigEntryNotReady("Could not connect to Protege controller")
        
        _LOGGER.info("Connection established, attempting login...")
        if not await client.login():
            await client.disconnect()
            _LOGGER.error("Failed to login to Protege - check PIN is correct")
            raise ConfigEntryNotReady("Login failed - verify PIN is a numeric code from Protege Users")
        
        _LOGGER.info("Login successful, getting panel info...")
        # Get panel description
        try:
            panel_info = await client.get_panel_description()
            _LOGGER.info(f"Connected to Protege panel: {panel_info}")
        except Exception as e:
            _LOGGER.warning(f"Could not get panel description: {e}")
            panel_info = {}
        
    except ConfigEntryNotReady:
        raise
    except Exception as err:
        _LOGGER.error(f"Unexpected error during setup: {err}", exc_info=True)
        try:
            await client.disconnect()
        except:
            pass
        raise ConfigEntryNotReady(f"Setup failed: {err}") from err

    # Create coordinator for status updates
    coordinator = ProtegeDataUpdateCoordinator(hass, client)
    
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as e:
        _LOGGER.warning(f"First coordinator refresh failed (continuing anyway): {e}")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_output_on_timed(call):
        """Handle the output_on_timed service call."""
        entity_id = call.data.get("entity_id")
        duration = call.data.get("duration")
        
        # Extract output index from entity_id
        # Format: switch.output_X or switch.output_cpXXX_XX
        entity_parts = entity_id.split("_")
        if len(entity_parts) >= 2:
            try:
                output_index = int(entity_parts[-1])
                await client.output_on_timed(output_index, duration)
            except ValueError:
                _LOGGER.error(f"Could not extract output index from {entity_id}")
    
    async def handle_bypass_input(call):
        """Handle the bypass_input service call."""
        entity_id = call.data.get("entity_id")
        permanent = call.data.get("permanent", False)
        
        # Extract input index from entity_id
        entity_parts = entity_id.split("_")
        if len(entity_parts) >= 2:
            try:
                input_index = int(entity_parts[-1])
                await client.bypass_input(input_index, permanent)
            except ValueError:
                _LOGGER.error(f"Could not extract input index from {entity_id}")
    
    async def handle_remove_input_bypass(call):
        """Handle the remove_input_bypass service call."""
        entity_id = call.data.get("entity_id")
        
        # Extract input index from entity_id
        entity_parts = entity_id.split("_")
        if len(entity_parts) >= 2:
            try:
                input_index = int(entity_parts[-1])
                await client.remove_input_bypass(input_index)
            except ValueError:
                _LOGGER.error(f"Could not extract input index from {entity_id}")
    
    async def handle_discover_devices(call):
        """Handle manual device discovery."""
        start_index = call.data.get("start_index", 1)
        end_index = call.data.get("end_index", 20)
        device_type = call.data.get("device_type", "all")
        
        _LOGGER.info(f"Manual discovery: {device_type} from {start_index} to {end_index}")
        
        results = {
            "doors": [],
            "inputs": [],
            "outputs": []
        }
        
        if device_type in ["all", "door"]:
            for i in range(start_index, end_index + 1):
                try:
                    status = await client.get_door_status(i)
                    if status:
                        results["doors"].append(i)
                        _LOGGER.info(f"Found door at index {i}")
                except Exception as e:
                    _LOGGER.debug(f"Door {i}: {e}")
        
        if device_type in ["all", "input"]:
            for i in range(start_index, end_index + 1):
                try:
                    status = await client.get_input_status(i)
                    if status:
                        results["inputs"].append(i)
                        _LOGGER.info(f"Found input at index {i}: {status.get('reference', 'N/A')}")
                except Exception as e:
                    _LOGGER.debug(f"Input {i}: {e}")
        
        if device_type in ["all", "output"]:
            for i in range(start_index, end_index + 1):
                try:
                    status = await client.get_output_status(i)
                    if status:
                        results["outputs"].append(i)
                        _LOGGER.info(f"Found output at index {i}: {status.get('reference', 'N/A')}")
                except Exception as e:
                    _LOGGER.debug(f"Output {i}: {e}")
        
        _LOGGER.info(f"Discovery complete: {results}")
        
        # Send persistent notification with results
        hass.components.persistent_notification.create(
            f"Protege Discovery Results:\n"
            f"Doors: {results['doors']}\n"
            f"Inputs: {results['inputs']}\n"
            f"Outputs: {results['outputs']}\n\n"
            f"Check logs for more details.",
            title="Protege Device Discovery",
            notification_id="protege_discovery"
        )
    
    hass.services.async_register(
        DOMAIN, "output_on_timed", handle_output_on_timed
    )
    hass.services.async_register(
        DOMAIN, "bypass_input", handle_bypass_input
    )
    hass.services.async_register(
        DOMAIN, "remove_input_bypass", handle_remove_input_bypass
    )
    hass.services.async_register(
        DOMAIN, "discover_devices", handle_discover_devices
    )

    # Start monitoring
    entry.async_create_background_task(
        hass,
        client.start_monitoring(),
        "protege_monitoring",
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        client = hass.data[DOMAIN][entry.entry_id]["client"]
        await client.disconnect()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class ProtegeDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Protege data."""

    def __init__(self, hass: HomeAssistant, client: ProtegeClient) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.client = client

    async def _async_update_data(self):
        """Fetch data from Protege."""
        try:
            # The monitoring system handles real-time updates
            # This is just for periodic health checks
            if not self.client.is_connected():
                raise UpdateFailed("Connection to Protege lost")
            
            return {
                "doors": self.client.doors,
                "inputs": self.client.inputs,
                "outputs": self.client.outputs,
                "areas": self.client.areas,
                "variables": self.client.variables,
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Protege: {err}") from err
