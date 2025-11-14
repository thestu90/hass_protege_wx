#!/usr/bin/env python3
"""
Protege Device Query Diagnostic Tool

This script connects to Protege and tests device queries to see exactly what responses we get.
This will help diagnose why devices aren't being discovered.

Usage:
    python3 diagnose_protege_devices.py <IP> <PORT> <PIN>
"""

import asyncio
import struct
import sys


def create_packet(packet_type, data, checksum_type=1):
    """Create a Protege protocol packet."""
    header = b'IC'
    format_byte = 0x00
    
    checksum_len = 1 if checksum_type == 1 else 0
    total_length = 2 + 2 + 1 + 1 + len(data) + checksum_len
    
    length = struct.pack('<H', total_length)
    packet = header + length + bytes([packet_type, format_byte]) + data
    
    if checksum_type == 1:
        checksum = sum(packet) % 256
        packet += bytes([checksum])
    
    return packet


async def read_packet(reader):
    """Read a packet from the stream."""
    try:
        # Read header
        header = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        if header != b'IC':
            print(f"❌ Invalid header: {header.hex()}")
            return None
        
        # Read length
        length_bytes = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        length = struct.unpack('<H', length_bytes)[0]
        
        # Read rest
        remaining = length - 4
        rest = await asyncio.wait_for(reader.readexactly(remaining), timeout=5)
        
        return header + length_bytes + rest
    except asyncio.TimeoutError:
        print("❌ Timeout reading packet")
        return None
    except Exception as e:
        print(f"❌ Error reading packet: {e}")
        return None


async def send_and_receive(writer, reader, packet):
    """Send a packet and wait for response."""
    writer.write(packet)
    await writer.drain()
    
    response = await read_packet(reader)
    return response


def analyze_packet(packet, label="Packet"):
    """Analyze and print packet details."""
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    print(f"Raw bytes ({len(packet)}): {packet.hex()}")
    
    if len(packet) < 6:
        print("❌ Packet too short")
        return
    
    # Parse header
    header = packet[0:2]
    length = struct.unpack('<H', packet[2:4])[0]
    packet_type = packet[4]
    format_byte = packet[5]
    
    print(f"\nHeader: {header.hex()} ('{header.decode('ascii')}')")
    print(f"Length: {length} bytes")
    print(f"Type: 0x{packet_type:02X} ", end="")
    
    if packet_type == 0x00:
        print("(Command)")
    elif packet_type == 0x01:
        print("(Data)")
    elif packet_type == 0xC0:
        print("(System)")
    else:
        print("(Unknown)")
    
    print(f"Format: 0x{format_byte:02X}")
    
    # Parse data section
    data_start = 6
    
    if packet_type == 0xC0:  # System packet
        if len(packet) >= 8:
            data_bytes = packet[data_start:-1] if len(packet) >= 9 else packet[data_start:]
            print(f"\nData: {data_bytes.hex()}")
            
            if data_bytes[0] == 0xFF and data_bytes[1] == 0x00:
                print("✅ ACK")
            elif data_bytes[0] == 0xFF and data_bytes[1] == 0xFF:
                print("❌ NACK")
                if len(data_bytes) >= 4:
                    error_code = struct.unpack('<H', data_bytes[2:4])[0]
                    print(f"Error code: 0x{error_code:04X}")
                    
                    errors = {
                        0x0120: "Command not valid",
                        0x0121: "Index not valid",
                        0x0302: "Invalid user/PIN",
                        0x0303: "User has no access rights",
                        0x030F: "Access denied for this device",
                        0x0869: "Area no change",
                        0x0A32: "Door already in state",
                    }
                    
                    if error_code in errors:
                        print(f"Meaning: {errors[error_code]}")
    
    elif packet_type == 0x01:  # Data packet
        pos = data_start
        print(f"\nData sections:")
        
        while pos < len(packet) - 3:
            if pos + 2 > len(packet):
                break
                
            data_type = struct.unpack('<H', packet[pos:pos+2])[0]
            pos += 2
            
            if data_type == 0xFFFF:
                print("  End marker")
                break
            
            if pos >= len(packet):
                break
                
            data_length = packet[pos]
            pos += 1
            
            if pos + data_length > len(packet):
                break
            
            data = packet[pos:pos+data_length]
            pos += data_length
            
            print(f"  Type: 0x{data_type:04X}, Length: {data_length}, Data: {data.hex()}")
            
            # Decode known types
            if data_type == 0x0100:  # Door status
                if len(data) >= 8:
                    index = struct.unpack('<I', data[0:4])[0]
                    lock_state = data[4]
                    door_state = data[5]
                    print(f"    → Door index: {index}, Lock: {lock_state}, State: {door_state}")
            
            elif data_type == 0x0400:  # Input status
                if len(data) >= 16:
                    index = struct.unpack('<I', data[0:4])[0]
                    reference = data[4:12].decode('ascii', errors='ignore')
                    state = data[12]
                    bypass = data[13]
                    print(f"    → Input index: {index}, Ref: {reference}, State: {state}, Bypass: {bypass}")
            
            elif data_type == 0x0300:  # Output status
                if len(data) >= 16:
                    index = struct.unpack('<I', data[0:4])[0]
                    reference = data[4:12].decode('ascii', errors='ignore')
                    state = data[12]
                    print(f"    → Output index: {index}, Ref: {reference}, State: {state}")


async def test_device_query(reader, writer, device_type, index):
    """Test querying a specific device."""
    print(f"\n{'#'*60}")
    print(f"Testing {device_type} at index {index}")
    print(f"{'#'*60}")
    
    # Prepare command based on device type
    if device_type == "door":
        cmd_group = 0x01
        subcmd = 0x80
    elif device_type == "input":
        cmd_group = 0x04
        subcmd = 0x80
    elif device_type == "output":
        cmd_group = 0x03
        subcmd = 0x80
    else:
        print(f"Unknown device type: {device_type}")
        return False
    
    # Create query packet
    data = bytes([cmd_group, subcmd]) + struct.pack('<I', index)
    packet = create_packet(0x00, data)  # Command packet
    
    print(f"\nSending query packet:")
    print(f"Command group: 0x{cmd_group:02X}, Subcommand: 0x{subcmd:02X}, Index: {index}")
    print(f"Packet: {packet.hex()}")
    
    # Send and wait for response
    response = await send_and_receive(writer, reader, packet)
    
    if response:
        analyze_packet(response, f"Response for {device_type} {index}")
        return True
    else:
        print(f"❌ No response for {device_type} {index}")
        return False


async def main():
    if len(sys.argv) != 4:
        print("Usage: python3 diagnose_protege_devices.py <IP> <PORT> <PIN>")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2])
    pin = sys.argv[3]
    
    print("="*60)
    print("Protege Device Query Diagnostic Tool")
    print("="*60)
    print(f"Target: {host}:{port}")
    print(f"PIN: {pin}")
    
    # Connect
    print("\n[1] Connecting...")
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=10
        )
        print("✅ Connected")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # Login
    print("\n[2] Logging in...")
    pin_bytes = [int(d) for d in pin if d.isdigit()]
    if len(pin_bytes) > 6:
        pin_bytes = pin_bytes[:6]
    pin_bytes.append(0xFF)
    
    login_data = bytes([0x00, 0x02] + pin_bytes)
    login_packet = create_packet(0x00, login_data)
    
    print(f"Login packet: {login_packet.hex()}")
    response = await send_and_receive(writer, reader, login_packet)
    
    if response:
        analyze_packet(response, "Login Response")
        
        # Check if ACK
        if len(response) >= 8:
            if response[6] == 0xFF and response[7] == 0x00:
                print("\n✅ Login successful")
            else:
                print("\n❌ Login failed")
                writer.close()
                await writer.wait_closed()
                return
    else:
        print("❌ No login response")
        writer.close()
        await writer.wait_closed()
        return
    
    # Test device queries
    print("\n" + "="*60)
    print("Testing Device Queries")
    print("="*60)
    
    devices_to_test = [
        ("door", [1, 2, 3, 5, 10]),
        ("input", [1, 2, 3, 5, 10]),
        ("output", [1, 2, 3, 5, 10]),
    ]
    
    results = {}
    
    for device_type, indices in devices_to_test:
        results[device_type] = []
        print(f"\n{'='*60}")
        print(f"Testing {device_type}s")
        print(f"{'='*60}")
        
        for index in indices:
            found = await test_device_query(reader, writer, device_type, index)
            if found:
                results[device_type].append(index)
            await asyncio.sleep(0.2)  # Small delay between queries
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for device_type, indices in results.items():
        if indices:
            print(f"✅ {device_type.title()}s found at indices: {indices}")
        else:
            print(f"❌ No {device_type}s found")
    
    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    
    if not any(results.values()):
        print("""
No devices found at any tested indices.

Possible issues:
1. Devices are configured with different indices (not 1,2,3...)
   → Check Protege software to see actual device indices
   → Try running this script with those specific indices

2. Using Protege GX with Record IDs (not Display Order)
   → In Protege: Sites → Controllers
   → Add command: ACPUseDisplayOrder=true
   → Save and upload configuration

3. User doesn't have access rights
   → In Protege: Users → Your user → Access Levels
   → Assign access to doors/areas
   → Save and upload configuration

4. Devices not configured in Protege
   → Check Protege: Doors, Inputs, Outputs sections
   → Verify devices are actually configured

Next steps:
- Check the response packets above for NACK/error codes
- Look for "Error code: 0x030F" (access denied)
- Verify device configuration in Protege software
""")
    else:
        print("""
✅ Found some devices!

The indices found above should work in Home Assistant.
Update your integration to scan these specific ranges.
""")
    
    # Cleanup
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
