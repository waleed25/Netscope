# SKILL.md - Modbus Wireshark Analyzer

## Description
Analyzes Wireshark packet captures (PCAP/PCAPNG) to identify Modbus protocol issues, errors, and anomalies using Qwen LLM.

## When to Use
- User asks to analyze Modbus traffic from a Wireshark capture
- Debugging Modbus communication issues
- Security auditing Modbus/TCP traffic

## Requirements
- Qwen model available (via Ollama or LM Studio)
- Wireshark `tshark` CLI installed
- PCAP file accessible locally

---

## Tool: analyze_modbus_capture

### Input
- `pcap_path` (required): Path to the PCAP file
- `filter` (optional): Wireshark display filter (default: `modbus || modbus.tcp`)
- `max_packets` (optional): Max packets to analyze (default: 5000)

### Process

1. **Export Modbus traffic** using tshark:
   ```bash
   tshark -r <pcap> -Y "<filter>" -T fields -e frame.number -e frame.time_relative \
       -e modbus.func_code -e modbus.domain -e modbus.exception_code -e modbus.error_code \
       -e modbus.transaction_id -e modbus.unit_id -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport
   ```

2. **Extract metrics**:
   - Exception codes (01-Illegal Function, 02-Illegal Data Address, 03-Illegal Data Value, 04=Server Device Failure)
   - Error codes
   - Function code distribution
   - Response times
   - Source/destination patterns

3. **Send to Qwen** with structured prompt for analysis

4. **Return formatted results**

### Example Output
```
## Modbus Analysis Results

### Summary
- Total Modbus packets: 1,247
- Exceptions: 23 (1.8%)
- Errors: 4
- Unique devices: 5

### Issues Found

1. **Exception Code 04** - Server Device Failure (12 occurrences)
   - Primarily on register reads at address 0x1234
   - Slave device #5
   - Suggests hardware/sensor failure

2. **Exception Code 03** - Illegal Data Value (8 occurrences)
   - Write commands with invalid data range
   - Check PLC logic for bounds validation

3. **High latency detected**
   - Average response time: 450ms
   - Max: 2.1s (slave #3)

### Recommendations
- Inspect slave device #5 for hardware failures
- Validate write ranges in PLC logic
- Investigate network latency to slave #3
- Consider protocol timeout adjustments
```

---

## Implementation Notes

- Uses existing `agent.llm_client.chat_completion()` for Qwen calls
- Falls back to basic stats if tshark unavailable
- Large captures sampled automatically
- Integrates with existing modbus device registry
