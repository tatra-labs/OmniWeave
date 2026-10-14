"""The answer checked against its schema, by the subset of JSON Schema the four schemas use. D710.

06:1491-1500's rules are what the schemas say; this is what makes a model's answer meet them when a
provider's constrained decoding did not. No third-party validator: the package imports
`omniweave_ports` alone, and the schemas use ten keywords, each a few lines here.

The keywords: `type` (one or a list), `enum`, `required`, `additionalProperties: false`,
`properties`, `items`, `minItems`/`maxItems`, `minLength`/`maxLength`, `pattern` (searched, as JSON
Schema does; the four schemas anchor theirs), and `minimum`/`maximum`. A boolean is not an integer
and not a number, as JSON Schema has it and Python does not.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["violations"]

_TYPES: Final = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def violations(schema: Mapping[str, Any], value: Any, at: str = "$") -> list[str]:
    """Every way `value` fails `schema`, each naming where; empty when it conforms."""
    kinds = schema.get("type")
    if kinds is not None:
        allowed = kinds if isinstance(kinds, list) else [kinds]
        if not any(_TYPES[k](value) for k in allowed):
            return [f"{at}: expected {' or '.join(allowed)}"]
    found: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{at}: {value!r} is not one of the enum")
    if isinstance(value, dict):
        found.extend(_object(schema, value, at))
    if isinstance(value, list):
        if _outside(len(value), schema, "minItems", "maxItems"):
            found.append(f"{at}: {len(value)} items is outside the bounds")
        for index, item in enumerate(value):
            found.extend(violations(schema.get("items", {}), item, f"{at}[{index}]"))
    if isinstance(value, str):
        if _outside(len(value), schema, "minLength", "maxLength"):
            found.append(f"{at}: {len(value)} characters is outside the bounds")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            found.append(f"{at}: does not match the pattern")
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and _outside(value, schema, "minimum", "maximum")
    ):
        found.append(f"{at}: {value} is outside the bounds")
    return found


def _outside(n: float, schema: Mapping[str, Any], low: str, high: str) -> bool:
    """Whether `n` is below the schema's `low` bound or above its `high`, where it states them."""
    return (low in schema and n < schema[low]) or (high in schema and n > schema[high])


def _object(schema: Mapping[str, Any], value: dict[str, Any], at: str) -> list[str]:
    properties = schema.get("properties", {})
    found = [f"{at}: {key} is required" for key in schema.get("required", ()) if key not in value]
    if schema.get("additionalProperties") is False:
        found.extend(f"{at}: {key} is not allowed" for key in value if key not in properties)
    for key, item in value.items():
        if key in properties:
            found.extend(violations(properties[key], item, f"{at}.{key}"))
    return found
