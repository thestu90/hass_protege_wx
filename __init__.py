# Copyright 2023 ICT Automation & Control Service Integration
# This file is part of the ICT integration for Home Assistant.

import logging
import os

from .const import DOMAIN
from .config_flow import ConfigFlow
from .device import IctDevice
from .helpers.auth import IctAuthManager
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ict"

def setup(hass, config):
    """Setup the ICT integration."""
    # Load device registry
    hass.data.setdefault(DOMAIN, {})
    
    # Register configuration flow
    hass.data[DOMAIN]["config_flow"] = ConfigFlow()
    
    # Register services
    async_register_services(hass)
    
    # Register device entities
    # This will be handled by the device manager later
    return True
