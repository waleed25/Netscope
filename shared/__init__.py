"""
Shared types and bus utilities for the NetScope 3-process architecture.

This package is imported by all three processes:
  - gateway/  (API + WebSocket)
  - daemon/   (elevated capture + Modbus)
  - engine/   (AI + RAG)
"""
