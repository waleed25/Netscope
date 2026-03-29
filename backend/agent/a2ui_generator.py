import json
import re
from typing import Optional, Tuple, Any

A2UI_COMPONENTS = {
    "packet-table": {
        "type": "packet-table",
        "description": "Display network packets",
        "props": {
            "filter": {"type": "string"},
            "protocol": {"type": "string"},
            "limit": {"type": "number"},
        }
    },
    "capture-controls": {
        "type": "capture-controls",
        "description": "Start/stop capture",
        "props": {
            "interface": {"type": "string"},
            "bpfFilter": {"type": "string"},
        }
    },
    "insight-card": {
        "type": "insight-card",
        "description": "AI-generated insights",
        "props": {
            "mode": {"type": "string"},
            "streaming": {"type": "boolean"},
        }
    },
}

UI_INTENT_PATTERNS = {
    "packet-table": [
        r"\b(show|list|display|filter|view|get)\b.*\b(packets?|traffic|capture)\b",
        r"\b(tcp|udp|icmp|dns|http|https)\b.*\b(packets?|traffic)\b",
        r"\bport\s+\d+\b",
        r"\bfilter\s+by\b",
    ],
    "capture-controls": [
        r"\b(start|stop|begin|pause|resume)\s*(capture|listening)\b",
        r"\b(start|stop)\b.*\b(eth\d|interface|network)\b",
    ],
    "insight-card": [
        r"\b(insight|analyze|audit|detect|analysis|generate)\b",
        r"\b(security|performance|ics|scada)\b.*\b(result|analysis|audit)\b",
    ],
    "filter-bar": [
        r"\b(filter|show filter|set filter|apply filter)\b",
        r"\bquick filter\b",
        r"\bfilters?\b.*\b(http|dns|ssh|modbus)\b",
    ],
    "network-tools": [
        r"\b(ping|traceroute|tracert)\b.*\b\d+\.\d+\.\d+\.\d+\b",
        r"\b(ping|traceroute|tracert)\b",
        r"\b(run|execute)\s*(network )?tool\b",
        r"\b(subnet|port)\s*scan\b",
        r"\b(arp|netstat)\b",
    ],
    "status-panel": [
        r"\b(status|health|check)\s*(system|llm|connection)\b",
        r"\bshow\s*(system )?status\b",
        r"\bllm\s*(status|connected|reachable)\b",
    ],
    "expert-tools": [
        r"\b(expert|advanced)\s*(analysis|tool|audit)\b",
        r"\bics\s*audit\b",
        r"\bscada\b.*\banalysis\b",
        r"\bport\s*scan\b.*\bexpert\b",
        r"\bflow\s*analysis\b",
        r"\bnetwork\s*conversations\b",
    ],
    "modbus-panel": [
        r"\bmodbus\b",
        r"\bscan\b.*\bdevice\b",
        r"\bread\b.*\bregister\b",
        r"\bwrite\b.*\bcoil\b",
    ],
    "rag-panel": [
        r"\b(search|query|find)\s*(knowledge|document|docs)\b",
        r"\brag\b",
        r"\bknowledge\s*base\b",
        r"\bingest\b.*\bdocument\b",
    ],
    "llm-config": [
        r"\b(change|switch|set)\s*(llm|model|backend)\b",
        r"\bllm\s*config\b",
        r"\bconfigure\b.*\b(ollama|lmstudio)\b",
        r"\btemperature\b",
    ],
}

FAST_INTENTS = {
    "show packets": "packet-table",
    "display packets": "packet-table",
    "filter packets": "packet-table",
    "tcp packets": "packet-table",
    "udp packets": "packet-table",
    "start capture": "capture-controls",
    "stop capture": "capture-controls",
    "start listening": "capture-controls",
    "stop listening": "capture-controls",
    "generate insight": "insight-card",
    "analyze": "insight-card",
    "security audit": "insight-card",
    "show filter": "filter-bar",
    "ping": "network-tools",
    "run network tools": "network-tools",
    "show status": "status-panel",
    "check status": "status-panel",
    "run expert analysis": "expert-tools",
    "ics audit": "expert-tools",
    "modbus": "modbus-panel",
    "search knowledge": "rag-panel",
    "configure llm": "llm-config",
}


def should_generate_a2ui(user_message: str, context: dict | None = None) -> Tuple[Optional[str], dict]:
    """
    Determine if we should generate A2UI based on user message.
    Returns (component_name, props) or (None, {})
    """
    message_lower = user_message.lower().strip()
    
    # Fast path: exact match
    if message_lower in FAST_INTENTS:
        component = FAST_INTENTS[message_lower]
        return component, _extract_props(component, user_message)
    
    # Check each component's patterns
    for component, patterns in UI_INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return component, _extract_props(component, user_message)
    
    return None, {}


def _extract_props(component: str, message: str) -> dict:
    """Extract component-specific props from the message."""
    props = {}
    message_lower = message.lower()
    
    if component == "packet-table":
        # Extract protocol
        protocols = ["tcp", "udp", "icmp", "dns", "http", "https", "arp", "mqtt", "modbus"]
        for proto in protocols:
            if proto in message_lower:
                props["protocol"] = proto.upper()
                break
        
        # Extract port
        port_match = re.search(r'\bport\s+(\d+)\b', message_lower)
        if port_match:
            props["filter"] = f"port {port_match.group(1)}"
        
        # Extract limit
        limit_match = re.search(r'\b(limit|show|first)\s+(\d+)\b', message_lower)
        if limit_match:
            props["limit"] = int(limit_match.group(2))
        else:
            props["limit"] = 100
            
    elif component == "capture-controls":
        # Extract filter
        filter_match = re.search(r'filter\s+["\']?([^"\']+)["\']?', message_lower)
        if filter_match:
            props["bpfFilter"] = filter_match.group(1).strip()
            
    elif component == "insight-card":
        # Extract mode
        if "security" in message_lower:
            props["mode"] = "security"
        elif "performance" in message_lower:
            props["mode"] = "performance"
        elif "ics" in message_lower or "scada" in message_lower or "modbus" in message_lower:
            props["mode"] = "ics"
        else:
            props["mode"] = "general"
        
        props["streaming"] = True
    
    elif component == "network-tools":
        # Extract tool
        tools = ["ping", "tracert", "tracert", "arp", "netstat", "subnet-scan"]
        for tool in tools:
            if tool in message_lower:
                props["tool"] = tool
                break
        
        # Extract target IP/hostname
        ip_match = re.search(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b', message)
        if ip_match:
            props["target"] = ip_match.group(1)
    
    elif component == "status-panel":
        # Extract components to check
        if "llm" in message_lower or "model" in message_lower:
            props["components"] = ["llm"]
        elif "capture" in message_lower:
            props["components"] = ["capture"]
        else:
            props["components"] = ["capture", "llm", "websocket"]
        
        props["refresh"] = 5000
    
    elif component == "expert-tools":
        # Extract mode
        if "ics" in message_lower or "scada" in message_lower:
            props["mode"] = "ics_audit"
        elif "port" in message_lower:
            props["mode"] = "port_scan"
        elif "flow" in message_lower:
            props["mode"] = "flow_analysis"
        elif "conversation" in message_lower:
            props["mode"] = "conversations"
        elif "anomaly" in message_lower or "unusual" in message_lower:
            props["mode"] = "anomaly_detect"
        
        props["with_llm"] = True
    
    elif component == "modbus-panel":
        # Extract action
        if "scan" in message_lower:
            props["action"] = "scan"
        elif "read" in message_lower:
            props["action"] = "read"
        elif "write" in message_lower:
            props["action"] = "write"
        elif "simulate" in message_lower:
            props["action"] = "simulate"
    
    elif component == "rag-panel":
        if "ingest" in message_lower or "add" in message_lower:
            props["mode"] = "ingest"
        elif "manage" in message_lower:
            props["mode"] = "manage"
        else:
            props["mode"] = "search"
    
    elif component == "llm-config":
        if "ollama" in message_lower:
            props["backend"] = "ollama"
        elif "lmstudio" in message_lower:
            props["backend"] = "lmstudio"
        
        # Extract temperature
        temp_match = re.search(r'temperature\s*[:=]?\s*(\d+\.?\d*)', message_lower)
        if temp_match:
            props["temperature"] = float(temp_match.group(1))
        else:
            props["temperature"] = 0.7
    
    return props


def generate_a2ui_response(component_name: str, props: dict) -> str:
    """Generate the A2UI JSON block for a component."""
    a2ui_data = {
        "type": component_name,
        "props": props
    }
    return f'\x00A2UI:{json.dumps(a2ui_data)}\x00'
