"""Protege Client for ICT Automation and Control Service Protocol."""
import asyncio
import logging
import struct
from typing import Callable, Optional

from .const import *

_LOGGER = logging.getLogger(__name__)


class ProtegeClient:
    """Client for Protege WX using ICT protocol."""

    def __init__(self, host: str, port: int, pin: str):
        """Initialize the client."""
        self.host = host
        self.port = port
        self.pin = pin
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.logged_in = False
        
        # Data storage
        self.doors = {}
        self.inputs = {}
        self.outputs = {}
        self.areas = {}
        self.variables = {}
        self.trouble_inputs = {}
        
        # Callbacks for real-time updates
        self.door_callbacks = []
        self.input_callbacks = []
        self.output_callbacks = []
        self.area_callbacks = []
        self.event_callbacks = []
        
        self._monitoring_task = None
        self._reader_task = None
        self._keepalive_task = None
        self._sequence = 0
        self._response_queue = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect to Protege system."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=10
            )
            self.connected = True
            _LOGGER.info(f"Connected to Protege at {self.host}:{self.port}")
            
            # Start the packet reader task
            self._reader_task = asyncio.create_task(self._packet_reader())
            
            # Test connection with a short timeout
            try:
                response = await asyncio.wait_for(
                    self._send_command(CMD_SYSTEM, SUBCMD_ARE_YOU_THERE),
                    timeout=3.0
                )
                if response:
                    _LOGGER.info("Protege system responded to 'Are You There'")
                else:
                    _LOGGER.warning("No response to 'Are You There', but continuing")
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout on 'Are You There', but connection established")
            
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to connect: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from Protege system."""
        if self.logged_in:
            try:
                await self.logout()
            except Exception as e:
                _LOGGER.warning(f"Error during logout: {e}")
        
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                _LOGGER.warning(f"Error closing writer: {e}")
        
        self.connected = False
        self.logged_in = False
        _LOGGER.info("Disconnected from Protege")

    async def login(self) -> bool:
        """Log in to Protege system."""
        try:
            _LOGGER.info(f"Attempting login with PIN: {self.pin}")
            
            # Convert PIN to individual digits
            pin_bytes = [int(d) for d in self.pin if d.isdigit()]
            if len(pin_bytes) > 6:
                pin_bytes = pin_bytes[:6]
            
            if len(pin_bytes) == 0:
                _LOGGER.error("PIN must contain at least one digit")
                return False
            
            _LOGGER.debug(f"PIN converted to {len(pin_bytes)} digits")
            
            # Add terminator
            pin_bytes.append(0xFF)
            
            # Create login packet
            data = bytes([CMD_SYSTEM, SUBCMD_LOGIN] + pin_bytes)
            packet = self._create_packet(PACKET_TYPE_COMMAND, data)
            
            _LOGGER.debug(f"Sending login packet ({len(packet)} bytes)")
            response = await self._send_packet(packet)
            
            if not response:
                _LOGGER.error("No response to login packet")
                return False
            
            _LOGGER.debug(f"Login response received ({len(response)} bytes)")
            
            if self._is_ack(response):
                self.logged_in = True
                _LOGGER.info("Successfully logged in to Protege")
                
                # Set login time to 10 minutes
                await self._set_login_time(600)
                
                # Configure acknowledgments
                await self._configure_ack()
                
                # Start keepalive
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                
                return True
            else:
                # Check if it's a NACK
                if len(response) >= 8:
                    data_start = 6
                    if response[data_start] == 0xFF and response[data_start + 1] == 0xFF:
                        _LOGGER.error("Login rejected (NACK)")
                        if len(response) >= 10:
                            error_code = struct.unpack('<H', response[8:10])[0]
                            _LOGGER.error(f"Error code: 0x{error_code:04X}")
                    else:
                        _LOGGER.error(f"Unexpected response: {response.hex()}")
                else:
                    _LOGGER.error(f"Invalid response: {response.hex()}")
                return False
                
        except Exception as e:
            _LOGGER.error(f"Login error: {e}", exc_info=True)
            return False

    async def logout(self):
        """Log out from Protege system."""
        if self.logged_in:
            await self._send_command(CMD_SYSTEM, SUBCMD_LOGOUT)
            self.logged_in = False
            _LOGGER.info("Logged out from Protege")

    async def get_panel_description(self) -> dict:
        """Get panel description."""
        response = await self._send_command(CMD_SYSTEM, SUBCMD_PANEL_DESCRIPTION)
        if response:
            return self._parse_panel_description(response)
        return {}

    async def start_monitoring(self):
        """Start monitoring for status changes and events."""
        # Request events in human-readable format
        await self._request_events(True, True)
        
        _LOGGER.info("Monitoring started for events and status updates")

    async def monitor_door(self, door_index: int, start: bool = True):
        """Monitor a door for status changes."""
        await self._request_monitor(MONITOR_DOOR, door_index, start)

    async def monitor_input(self, input_index: int, start: bool = True):
        """Monitor an input for status changes."""
        await self._request_monitor(MONITOR_INPUT, input_index, start)

    async def monitor_output(self, output_index: int, start: bool = True):
        """Monitor an output for status changes."""
        await self._request_monitor(MONITOR_OUTPUT, output_index, start)

    async def monitor_area(self, area_index: int, start: bool = True):
        """Monitor an area for status changes."""
        await self._request_monitor(MONITOR_AREA, area_index, start)

    # Door control methods
    async def lock_door(self, door_index: int) -> bool:
        """Lock a door."""
        data = struct.pack('<I', door_index)
        response = await self._send_command(CMD_DOOR, SUBCMD_LOCK_DOOR, data)
        return response is not None

    async def unlock_door(self, door_index: int) -> bool:
        """Unlock a door (momentary)."""
        data = struct.pack('<I', door_index)
        response = await self._send_command(CMD_DOOR, SUBCMD_UNLOCK_DOOR, data)
        return response is not None

    async def unlock_door_latched(self, door_index: int) -> bool:
        """Unlock a door and latch it."""
        data = struct.pack('<I', door_index)
        response = await self._send_command(CMD_DOOR, SUBCMD_UNLOCK_DOOR_LATCHED, data)
        return response is not None

    async def get_door_status(self, door_index: int) -> Optional[dict]:
        """Get door status."""
        data = struct.pack('<I', door_index)
        response = await self._send_command(CMD_DOOR, SUBCMD_REQUEST_DOOR_STATUS, data)
        
        if response:
            _LOGGER.debug(f"Door {door_index} status response: {response.hex()}")
            try:
                parsed = self._parse_door_status(response)
                _LOGGER.debug(f"Door {door_index} parsed status: {parsed}")
                return parsed
            except Exception as e:
                _LOGGER.error(f"Error parsing door {door_index} status: {e}")
                return None
        else:
            _LOGGER.debug(f"No response for door {door_index}")
            return None

    # Output control methods
    async def output_on(self, output_index: int) -> bool:
        """Turn output on."""
        data = struct.pack('<I', output_index)
        response = await self._send_command(CMD_OUTPUT, SUBCMD_OUTPUT_ON, data)
        return response is not None

    async def output_off(self, output_index: int) -> bool:
        """Turn output off."""
        data = struct.pack('<I', output_index)
        response = await self._send_command(CMD_OUTPUT, SUBCMD_OUTPUT_OFF, data)
        return response is not None

    async def output_on_timed(self, output_index: int, seconds: int) -> bool:
        """Turn output on for specified time."""
        data = struct.pack('<IH', output_index, seconds)
        response = await self._send_command(CMD_OUTPUT, SUBCMD_OUTPUT_ON_TIMED, data)
        return response is not None

    async def get_output_status(self, output_index: int) -> Optional[dict]:
        """Get output status."""
        data = struct.pack('<I', output_index)
        response = await self._send_command(CMD_OUTPUT, SUBCMD_REQUEST_OUTPUT_STATUS, data)
        
        if response:
            _LOGGER.debug(f"Output {output_index} status response: {response.hex()}")
            try:
                parsed = self._parse_output_status(response)
                _LOGGER.debug(f"Output {output_index} parsed status: {parsed}")
                return parsed
            except Exception as e:
                _LOGGER.error(f"Error parsing output {output_index} status: {e}")
                return None
        else:
            _LOGGER.debug(f"No response for output {output_index}")
            return None

    # Input control methods
    async def get_input_status(self, input_index: int) -> Optional[dict]:
        """Get input status."""
        data = struct.pack('<I', input_index)
        response = await self._send_command(CMD_INPUT, SUBCMD_REQUEST_INPUT_STATUS, data)
        
        if response:
            _LOGGER.debug(f"Input {input_index} status response: {response.hex()}")
            try:
                parsed = self._parse_input_status(response)
                _LOGGER.debug(f"Input {input_index} parsed status: {parsed}")
                return parsed
            except Exception as e:
                _LOGGER.error(f"Error parsing input {input_index} status: {e}")
                return None
        else:
            _LOGGER.debug(f"No response for input {input_index}")
            return None

    async def bypass_input(self, input_index: int, permanent: bool = False) -> bool:
        """Bypass an input."""
        subcmd = SUBCMD_BYPASS_INPUT_PERM if permanent else SUBCMD_BYPASS_INPUT_TEMP
        data = struct.pack('<I', input_index)
        response = await self._send_command(CMD_INPUT, subcmd, data)
        return response is not None

    async def remove_input_bypass(self, input_index: int) -> bool:
        """Remove input bypass."""
        data = struct.pack('<I', input_index)
        response = await self._send_command(CMD_INPUT, SUBCMD_REMOVE_INPUT_BYPASS, data)
        return response is not None

    # Area control methods
    async def arm_area(self, area_index: int, mode: str = "normal") -> bool:
        """Arm an area."""
        mode_map = {
            "normal": SUBCMD_ARM_NORMAL,
            "force": SUBCMD_ARM_FORCE,
            "stay": SUBCMD_ARM_STAY,
            "instant": SUBCMD_ARM_INSTANT,
        }
        subcmd = mode_map.get(mode, SUBCMD_ARM_NORMAL)
        data = struct.pack('<I', area_index)
        response = await self._send_command(CMD_AREA, subcmd, data)
        return response is not None

    async def disarm_area(self, area_index: int, disarm_24hr: bool = False) -> bool:
        """Disarm an area."""
        subcmd = SUBCMD_DISARM_ALL if disarm_24hr else SUBCMD_DISARM_AREA
        data = struct.pack('<I', area_index)
        response = await self._send_command(CMD_AREA, subcmd, data)
        return response is not None

    async def get_area_status(self, area_index: int) -> Optional[dict]:
        """Get area status."""
        data = struct.pack('<I', area_index)
        response = await self._send_command(CMD_AREA, SUBCMD_REQUEST_AREA_STATUS, data)
        if response:
            return self._parse_area_status(response)
        return None

    # Callback registration
    def register_door_callback(self, callback: Callable):
        """Register callback for door updates."""
        if callback not in self.door_callbacks:
            self.door_callbacks.append(callback)

    def register_input_callback(self, callback: Callable):
        """Register callback for input updates."""
        if callback not in self.input_callbacks:
            self.input_callbacks.append(callback)

    def register_output_callback(self, callback: Callable):
        """Register callback for output updates."""
        if callback not in self.output_callbacks:
            self.output_callbacks.append(callback)

    def register_area_callback(self, callback: Callable):
        """Register callback for area updates."""
        if callback not in self.area_callbacks:
            self.area_callbacks.append(callback)

    def register_event_callback(self, callback: Callable):
        """Register callback for events."""
        if callback not in self.event_callbacks:
            self.event_callbacks.append(callback)

    def is_connected(self) -> bool:
        """Check if connected."""
        return self.connected and self.logged_in

    # Private methods
    def _create_packet(self, packet_type: int, data: bytes, checksum_type: int = 1) -> bytes:
        """Create a packet according to protocol."""
        header = b'IC'
        format_byte = 0x00  # No encryption, no address
        
        # Calculate length (header + length + type + format + data + checksum)
        checksum_len = 1 if checksum_type == 1 else (2 if checksum_type == 2 else 0)
        total_length = 2 + 2 + 1 + 1 + len(data) + checksum_len
        
        length = struct.pack('<H', total_length)
        
        # Build packet
        packet = header + length + bytes([packet_type, format_byte]) + data
        
        # Add checksum if required
        if checksum_type == 1:  # 8-bit sum
            checksum = sum(packet) % 256
            packet += bytes([checksum])
        elif checksum_type == 2:  # 16-bit CRC
            crc = self._calculate_crc16(packet)
            packet += struct.pack('<H', crc)
        
        return packet

    def _calculate_crc16(self, data: bytes) -> int:
        """Calculate CRC-16-CCITT."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc = crc << 1
                crc &= 0xFFFF
        return crc

    async def _send_command(self, cmd_group: int, subcmd: int, data: bytes = b'') -> Optional[bytes]:
        """Send a command and wait for response."""
        cmd_data = bytes([cmd_group, subcmd]) + data
        packet = self._create_packet(PACKET_TYPE_COMMAND, cmd_data)
        return await self._send_packet(packet)

    async def _send_packet(self, packet: bytes) -> Optional[bytes]:
        """Send a packet and wait for response."""
        if not self.connected or not self.writer:
            return None
        
        async with self._lock:
            try:
                # Clear any old responses
                while not self._response_queue.empty():
                    try:
                        self._response_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                
                # Send packet
                self.writer.write(packet)
                await self.writer.drain()
                
                # Wait for response with timeout
                try:
                    response = await asyncio.wait_for(
                        self._response_queue.get(),
                        timeout=5.0
                    )
                    return response
                except asyncio.TimeoutError:
                    _LOGGER.warning("Timeout waiting for response")
                    return None
                    
            except Exception as e:
                _LOGGER.error(f"Error sending packet: {e}")
                return None

    async def _read_packet(self) -> Optional[bytes]:
        """Read a packet from the stream."""
        if not self.reader:
            return None
        
        try:
            # Read header
            header = await self.reader.readexactly(2)
            if header != b'IC':
                _LOGGER.warning(f"Invalid header: {header.hex()}")
                return None
            
            # Read length
            length_bytes = await self.reader.readexactly(2)
            length = struct.unpack('<H', length_bytes)[0]
            
            # Validate length
            if length < 6 or length > 1024:
                _LOGGER.warning(f"Invalid packet length: {length}")
                return None
            
            # Read rest of packet
            remaining = length - 4  # Already read 4 bytes (header + length)
            rest = await self.reader.readexactly(remaining)
            
            return header + length_bytes + rest
            
        except asyncio.IncompleteReadError as e:
            _LOGGER.error(f"Incomplete read - connection lost? {e}")
            self.connected = False
            return None
        except ConnectionResetError as e:
            _LOGGER.error(f"Connection reset: {e}")
            self.connected = False
            return None
        except Exception as e:
            _LOGGER.error(f"Error reading packet: {e}")
            return None

    def _is_ack(self, packet: bytes) -> bool:
        """Check if packet is an ACK."""
        if len(packet) < 8:
            return False
        
        packet_type = packet[4]
        if packet_type != PACKET_TYPE_SYSTEM:
            return False
        
        # Check for ACK (0xFF, 0x00)
        data_start = 6
        if len(packet) >= data_start + 2:
            return packet[data_start] == 0xFF and packet[data_start + 1] == 0x00
        
        return False

    async def _set_login_time(self, seconds: int):
        """Set login timeout."""
        data = struct.pack('<H', seconds)
        await self._send_command(CMD_SYSTEM, SUBCMD_SET_LOGIN_TIME, data)

    async def _configure_ack(self):
        """Configure acknowledgment settings."""
        # Full acknowledgment for everything
        data = bytes([0x01, 0x03, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00])
        await self._send_command(CMD_SYSTEM, SUBCMD_ACK_CONFIG, data)

    async def _request_events(self, start: bool, human_readable: bool):
        """Request event notifications."""
        control = 0x01 if start else 0x00
        format_flags = 0x01 if human_readable else 0x00
        data = bytes([control, format_flags])
        await self._send_command(CMD_SYSTEM, SUBCMD_REQUEST_EVENTS, data)

    async def _request_monitor(self, item_type: int, index: int, start: bool, force_update: bool = False):
        """Request monitoring of an item."""
        flags = 0x01 if start else 0x00
        if force_update:
            flags |= 0x02
        
        data = struct.pack('<HI', item_type, index) + bytes([flags])
        await self._send_command(CMD_SYSTEM, SUBCMD_REQUEST_TO_MONITOR, data)

    async def _keepalive_loop(self):
        """Send periodic keepalive messages."""
        _LOGGER.info("Keepalive loop started")
        
        while self.connected and self.logged_in:
            try:
                await asyncio.sleep(30)
                
                if not self.connected or not self.logged_in:
                    break
                
                # Send keepalive without waiting for response
                # This prevents blocking the keepalive loop
                data = bytes([CMD_SYSTEM, SUBCMD_ARE_YOU_THERE])
                packet = self._create_packet(PACKET_TYPE_COMMAND, data)
                
                if self.writer:
                    try:
                        self.writer.write(packet)
                        await self.writer.drain()
                        _LOGGER.debug("Keepalive sent")
                    except Exception as e:
                        _LOGGER.error(f"Keepalive send error: {e}")
                        self.connected = False
                        break
                        
            except asyncio.CancelledError:
                _LOGGER.info("Keepalive loop cancelled")
                break
            except Exception as e:
                _LOGGER.error(f"Keepalive error: {e}")
                await asyncio.sleep(5)
        
        _LOGGER.info("Keepalive loop stopped")

    async def _packet_reader(self):
        """Central packet reader that dispatches all incoming packets."""
        _LOGGER.info("Packet reader started")
        
        while self.connected:
            try:
                packet = await self._read_packet()
                if not packet:
                    _LOGGER.warning("No packet received, connection may be lost")
                    await asyncio.sleep(1)
                    continue
                
                # Determine packet type
                if len(packet) < 6:
                    _LOGGER.warning(f"Packet too short: {len(packet)} bytes")
                    continue
                
                packet_type = packet[4]
                
                if packet_type == PACKET_TYPE_SYSTEM:
                    # ACK or NACK - put in response queue
                    await self._response_queue.put(packet)
                
                elif packet_type == PACKET_TYPE_DATA:
                    # Data packet - process and send ACK
                    await self._process_data_packet(packet)
                    await self._send_ack()
                
                elif packet_type == PACKET_TYPE_COMMAND:
                    # Should not receive command packets, but handle gracefully
                    _LOGGER.debug("Received command packet (unexpected)")
                    await self._response_queue.put(packet)
                
            except asyncio.CancelledError:
                _LOGGER.info("Packet reader cancelled")
                break
            except Exception as e:
                _LOGGER.error(f"Packet reader error: {e}", exc_info=True)
                await asyncio.sleep(1)
        
        _LOGGER.info("Packet reader stopped")

    async def _send_ack(self):
        """Send ACK packet."""
        data = bytes([0xFF, 0x00])
        packet = self._create_packet(PACKET_TYPE_SYSTEM, data)
        if self.writer:
            try:
                self.writer.write(packet)
                await self.writer.drain()
            except Exception as e:
                _LOGGER.error(f"Error sending ACK: {e}")

    async def _process_data_packet(self, packet: bytes):
        """Process data packet."""
        pos = 6  # Start of data section
        
        while pos < len(packet) - 3:
            # Read data type
            data_type = struct.unpack('<H', packet[pos:pos+2])[0]
            pos += 2
            
            if data_type == DATA_TYPE_END:
                break
            
            # Read data length
            data_length = packet[pos]
            pos += 1
            
            # Read data
            data = packet[pos:pos+data_length]
            pos += data_length
            
            # Process based on type
            if data_type == DATA_TYPE_DOOR_STATUS:
                door_status = self._parse_door_status_data(data)
                self.doors[door_status['index']] = door_status
                for callback in self.door_callbacks:
                    callback(door_status)
            
            elif data_type == DATA_TYPE_INPUT_STATUS:
                input_status = self._parse_input_status_data(data)
                self.inputs[input_status['index']] = input_status
                for callback in self.input_callbacks:
                    callback(input_status)
            
            elif data_type == DATA_TYPE_OUTPUT_STATUS:
                output_status = self._parse_output_status_data(data)
                self.outputs[output_status['index']] = output_status
                for callback in self.output_callbacks:
                    callback(output_status)
            
            elif data_type == DATA_TYPE_AREA_STATUS:
                area_status = self._parse_area_status_data(data)
                self.areas[area_status['index']] = area_status
                for callback in self.area_callbacks:
                    callback(area_status)
            
            elif data_type == DATA_TYPE_EVENT_READABLE:
                event_text = data[:-1].decode('ascii', errors='ignore')  # Remove null terminator
                _LOGGER.info(f"Event: {event_text}")
                for callback in self.event_callbacks:
                    callback(event_text)

    def _parse_panel_description(self, packet: bytes) -> dict:
        """Parse panel description from packet."""
        info = {}
        pos = 6
        
        while pos < len(packet) - 3:
            data_type = struct.unpack('<H', packet[pos:pos+2])[0]
            pos += 2
            
            if data_type == DATA_TYPE_END:
                break
            
            data_length = packet[pos]
            pos += 1
            data = packet[pos:pos+data_length]
            pos += data_length
            
            if data_type == DATA_TYPE_PANEL_SERIAL:
                info['serial'] = struct.unpack('<I', data)[0]
            elif data_type == DATA_TYPE_FIRMWARE_TYPE:
                info['firmware_type'] = data.decode('ascii')
            elif data_type == DATA_TYPE_FIRMWARE_VERSION:
                info['firmware_version'] = f"{data[1]}.{data[0]}"
            elif data_type == DATA_TYPE_FIRMWARE_BUILD:
                info['firmware_build'] = struct.unpack('<H', data)[0]
        
        return info

    def _parse_door_status_data(self, data: bytes) -> dict:
        """Parse door status data."""
        index = struct.unpack('<I', data[0:4])[0]
        lock_state = data[4]
        door_state = data[5]
        
        return {
            'index': index,
            'lock_state': lock_state,
            'door_state': door_state,
            'is_locked': lock_state == DOOR_LOCKED,
            'is_open': door_state != DOOR_STATE_CLOSED,
        }

    def _parse_input_status_data(self, data: bytes) -> dict:
        """Parse input status data."""
        index = struct.unpack('<I', data[0:4])[0]
        reference = data[4:12].decode('ascii', errors='ignore')
        state = data[12]
        bypass = data[13]
        
        return {
            'index': index,
            'reference': reference,
            'state': state,
            'bypass': bypass,
            'is_open': state == INPUT_OPEN,
            'is_bypassed': (bypass & 0x01) != 0,
        }

    def _parse_output_status_data(self, data: bytes) -> dict:
        """Parse output status data."""
        index = struct.unpack('<I', data[0:4])[0]
        reference = data[4:12].decode('ascii', errors='ignore')
        state = data[12]
        
        return {
            'index': index,
            'reference': reference,
            'state': state,
            'is_on': state != OUTPUT_OFF,
        }

    def _parse_area_status_data(self, data: bytes) -> dict:
        """Parse area status data."""
        index = struct.unpack('<I', data[0:4])[0]
        state = data[4]
        tamper_state = data[5]
        flags = data[6]
        
        return {
            'index': index,
            'state': state,
            'tamper_state': tamper_state,
            'flags': flags,
            'is_armed': state >= AREA_ARMED,
            'alarm_active': (flags & 0x01) != 0,
        }

    def _parse_door_status(self, packet: bytes) -> dict:
        """Parse door status from response packet."""
        # Response is a Data packet, need to extract data section
        if len(packet) < 10:
            _LOGGER.error(f"Door status packet too short: {len(packet)} bytes")
            return None
        
        # Check packet type
        packet_type = packet[4]
        if packet_type != PACKET_TYPE_DATA:
            _LOGGER.error(f"Expected Data packet, got type 0x{packet_type:02X}")
            return None
        
        # Data starts at byte 6, look for door status data type
        pos = 6
        while pos < len(packet) - 3:
            data_type = struct.unpack('<H', packet[pos:pos+2])[0]
            pos += 2
            
            if data_type == DATA_TYPE_END:
                break
            
            data_length = packet[pos]
            pos += 1
            
            if data_type == DATA_TYPE_DOOR_STATUS:
                data = packet[pos:pos+data_length]
                return self._parse_door_status_data(data)
            
            pos += data_length
        
        _LOGGER.error("No door status data found in packet")
        return None

    def _parse_input_status(self, packet: bytes) -> dict:
        """Parse input status from response packet."""
        if len(packet) < 10:
            _LOGGER.error(f"Input status packet too short: {len(packet)} bytes")
            return None
        
        packet_type = packet[4]
        if packet_type != PACKET_TYPE_DATA:
            _LOGGER.error(f"Expected Data packet, got type 0x{packet_type:02X}")
            return None
        
        pos = 6
        while pos < len(packet) - 3:
            data_type = struct.unpack('<H', packet[pos:pos+2])[0]
            pos += 2
            
            if data_type == DATA_TYPE_END:
                break
            
            data_length = packet[pos]
            pos += 1
            
            if data_type == DATA_TYPE_INPUT_STATUS:
                data = packet[pos:pos+data_length]
                return self._parse_input_status_data(data)
            
            pos += data_length
        
        _LOGGER.error("No input status data found in packet")
        return None

    def _parse_output_status(self, packet: bytes) -> dict:
        """Parse output status from response packet."""
        if len(packet) < 10:
            _LOGGER.error(f"Output status packet too short: {len(packet)} bytes")
            return None
        
        packet_type = packet[4]
        if packet_type != PACKET_TYPE_DATA:
            _LOGGER.error(f"Expected Data packet, got type 0x{packet_type:02X}")
            return None
        
        pos = 6
        while pos < len(packet) - 3:
            data_type = struct.unpack('<H', packet[pos:pos+2])[0]
            pos += 2
            
            if data_type == DATA_TYPE_END:
                break
            
            data_length = packet[pos]
            pos += 1
            
            if data_type == DATA_TYPE_OUTPUT_STATUS:
                data = packet[pos:pos+data_length]
                return self._parse_output_status_data(data)
            
            pos += data_length
        
        _LOGGER.error("No output status data found in packet")
        return None

    def _parse_area_status(self, packet: bytes) -> dict:
        """Parse area status from response packet."""
        if len(packet) < 10:
            _LOGGER.error(f"Area status packet too short: {len(packet)} bytes")
            return None
        
        packet_type = packet[4]
        if packet_type != PACKET_TYPE_DATA:
            _LOGGER.error(f"Expected Data packet, got type 0x{packet_type:02X}")
            return None
        
        pos = 6
        while pos < len(packet) - 3:
            data_type = struct.unpack('<H', packet[pos:pos+2])[0]
            pos += 2
            
            if data_type == DATA_TYPE_END:
                break
            
            data_length = packet[pos]
            pos += 1
            
            if data_type == DATA_TYPE_AREA_STATUS:
                data = packet[pos:pos+data_length]
                return self._parse_area_status_data(data)
            
            pos += data_length
        
        _LOGGER.error("No area status data found in packet")
        return None
