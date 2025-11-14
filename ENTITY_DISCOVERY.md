# Protege Entity Discovery - Troubleshooting Guide

## Status: Connected but No Entities

You've successfully connected and logged in, but no doors, inputs, or outputs are showing up. This guide will help you discover your devices.

## 🔍 Quick Diagnosis

### Step 1: Check the Logs

1. Go to **Settings** → **System** → **Logs**
2. Search for "protege"
3. Look for messages like:
   ```
   Starting door discovery...
   Checking door at index 1...
   Checking door at index 2...
   Found door at index X: {...}
   ```

### What You're Looking For:

**Good signs:**
```
Found door at index 3: {'index': 3, 'lock_state': 0, ...}
Found input at index 5: CP001:05
Found output at index 12: CP002:04
```

**Problem signs:**
```
No doors discovered! Check that doors are configured in Protege
No response for door 1
No door status data found in packet
```

## 🎯 Manual Discovery Service

I've added a service that lets you manually scan for devices and see what's found.

### How to Use It:

1. **Go to Developer Tools** → **Services**

2. **Select Service:** `protege.discover_devices`

3. **Fill in the fields:**
   - **Device Type**: "All Devices" (or specific type)
   - **Start Index**: 1
   - **End Index**: 20 (or higher)

4. **Click "CALL SERVICE"**

5. **Check Results:**
   - A notification will appear showing what was found
   - Check logs for detailed information

### Example Service Call:

```yaml
service: protege.discover_devices
data:
  device_type: all
  start_index: 1
  end_index: 50
```

### Try Different Ranges:

```yaml
# Try doors 1-100
service: protege.discover_devices
data:
  device_type: door
  start_index: 1
  end_index: 100
```

```yaml
# Try inputs 1-200
service: protege.discover_devices
data:
  device_type: input
  start_index: 1
  end_index: 200
```

## 🔧 Common Issues

### Issue 1: Devices Use Different Indices

**Problem:** Your Protege system might not use indices 1, 2, 3...

**Solution:** 
1. Check in Protege software what indices your devices have
2. Use the discovery service with a wider range
3. Or check the Protege "Display Order" setting

### Issue 2: Using Record IDs Instead of Indices

**Problem:** Protege GX uses Record IDs by default, not indices.

**Solution:**
In Protege software:
1. Go to: **Sites** → **Controllers**
2. Enter command: `ACPUseDisplayOrder=true`
3. Click **Save**
4. Upload configuration
5. Restart integration in Home Assistant

### Issue 3: NACK Responses (Access Denied)

**Problem:** Getting NACK responses when querying devices.

**Check Logs For:**
```
Error code: 0x030F - User doesn't have access rights
```

**Solution:**
1. In Protege: **Users** → Your automation user
2. Ensure user has **Access Levels** assigned
3. Grant access to doors, areas you want to control
4. Upload configuration

### Issue 4: Packets Not Parsed Correctly

**Problem:** Receiving responses but not parsing them.

**Check Logs For:**
```
Door 1 status response: 4943...
Expected Data packet, got type 0xC0
No door status data found in packet
```

**Solution:** This indicates a protocol issue. Enable debug logging:

```yaml
# configuration.yaml
logger:
  logs:
    custom_components.protege: debug
    custom_components.protege.protege_client: debug
```

Then check logs for the full packet hex dumps.

## 📊 Understanding Device Indices

### In Protege SE/LE:
- Doors: Usually 1-based sequential (Door 1, Door 2, etc.)
- Inputs: Module-based (CP001:01, CP001:02, etc.)
- Outputs: Module-based (CP001:01, CP001:02, etc.)

### In Protege GX:
- Uses Record IDs by default (not sequential)
- Can be switched to Display Order (indices) with ACPUseDisplayOrder command

### To Check Your Indices:

1. **Open Protege software**
2. **Go to the relevant section:**
   - Doors → Doors
   - Inputs → Inputs
   - Outputs → Outputs
3. **Note the numbering/indexing scheme**
4. **Use discovery service with that range**

## 🔄 Reload Integration After Discovery

Once you know which indices have devices:

1. **Remove the integration:**
   - Settings → Devices & Services → Protege → Remove

2. **Add it again:**
   - Settings → Devices & Services → Add Integration → Protege

3. **Discovery will run automatically** and now find your devices

**OR** you can just:
- **Restart Home Assistant** to trigger fresh discovery

## 🎨 Manual Device Configuration (Advanced)

If automatic discovery doesn't work, you can manually configure which indices to scan.

### Edit the Platform Files:

#### For Doors (lock.py):
```python
# Change line ~17
for door_index in range(1, 51):  # Current
# To your specific range, e.g.:
for door_index in [3, 7, 12, 15]:  # Specific doors
```

#### For Inputs (binary_sensor.py):
```python
# Change line ~17
for input_index in range(1, 101):  # Current
# To your specific range
```

#### For Outputs (switch.py):
```python
# Change line ~17
for output_index in range(1, 101):  # Current
# To your specific range
```

## 🧪 Testing Individual Devices

You can test if a specific device is accessible using Developer Tools:

### Test Door Status:
```yaml
# In Developer Tools → Template:
{{ states('lock.door_1') }}

# Should show: locked, unlocked, or unavailable
```

### Check Service Response:
```yaml
# Call discovery for a single device:
service: protege.discover_devices
data:
  device_type: door
  start_index: 3
  end_index: 3
```

Check the notification and logs for results.

## 📝 Checklist for Entity Discovery

- [ ] Integration shows "Connected" status
- [ ] Debug logging is enabled
- [ ] Ran manual discovery service
- [ ] Checked logs for "Starting door/input/output discovery"
- [ ] Checked logs for "Found" messages
- [ ] Checked logs for error messages
- [ ] Verified device indices in Protege software
- [ ] User has access rights to devices
- [ ] Tried ACPUseDisplayOrder command (for Protege GX)
- [ ] Tried wider index ranges (1-100 or more)
- [ ] Restarted Home Assistant after changes

## 🆘 Still No Entities?

### Collect This Information:

1. **Protege System:**
   - Model: WX / GX / SE
   - How many doors configured: ____
   - How many inputs configured: ____
   - How many outputs configured: ____
   - Indexing scheme: Sequential / Module-based / Record IDs

2. **From Logs:**
   - Copy all lines with "protege" in them
   - Especially lines like "Found door..." or "No response for..."

3. **From Discovery Service:**
   - Results from `protege.discover_devices` call
   - Notification content
   - Any error messages

4. **From Protege Software:**
   - Screenshot of Doors list showing indices/IDs
   - User access level configuration
   - ACPUseDisplayOrder setting (if GX)

## 💡 Pro Tips

1. **Start Small:** Use discovery service with range 1-10 first
2. **Check Protege First:** Verify devices are actually configured
3. **Use Specific Ranges:** If you know door 5 exists, scan just 5-5
4. **Watch Logs Live:** Keep logs open while running discovery
5. **One Type at a Time:** Discover doors first, then inputs, then outputs
6. **Patient Discovery:** Discovery can take 10-30 seconds for large ranges

## 🎯 Expected Behavior

When working correctly, you should see in logs:

```
Starting door discovery...
Checking door at index 1...
No response for door 1
Checking door at index 2...
No response for door 2
Checking door at index 3...
Found door at index 3: {'index': 3, 'lock_state': 0, 'door_state': 0, ...}
Checking door at index 4...
Found door at index 4: {'index': 4, 'lock_state': 0, 'door_state': 0, ...}
...
Added 2 Protege door locks: [3, 4]
```

Then in Home Assistant:
- `lock.door_3`
- `lock.door_4`

## 📞 Next Steps

1. **Run the discovery service** with a wide range
2. **Check the notification** for results
3. **Look at the logs** for detailed information
4. **Adjust scan ranges** based on what you find
5. **Restart HA** if you made configuration changes

The discovery service is your best tool for figuring out what's available!
