"""The MCP stdio and http transports; otlp.py, the only module in the framework that
may import opentelemetry. A non-loopback bind is refused without --api-key
(OW-A-040 / OW_HTTP_BIND_UNAUTHENTICATED).

Specified in 02-architecture.md section 2 row 40 and 10-interfaces.md.
"""
