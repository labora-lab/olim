"""Global settings parser and utilities.

This module provides type-safe parsing and serialization of global settings
with proper type hints and overloads for different data types.
"""

import json
from typing import Any, Literal, overload


@overload
def parse_setting_value(value: str, type_hint: Literal["str"]) -> str: ...


@overload
def parse_setting_value(value: str, type_hint: Literal["int"]) -> int: ...


@overload
def parse_setting_value(value: str, type_hint: Literal["float"]) -> float: ...


@overload
def parse_setting_value(value: str, type_hint: Literal["bool"]) -> bool: ...


@overload
def parse_setting_value(value: str, type_hint: Literal["json"]) -> dict | list: ...


def parse_setting_value(value: str, type_hint: str) -> Any:  # type: ignore
    """Parse a string value to the appropriate type based on type hint.

    Args:
        value: String value to parse
        type_hint: Type hint ('str', 'int', 'float', 'bool', 'json')

    Returns:
        Parsed value with appropriate type

    Raises:
        ValueError: If value cannot be parsed to the specified type
        json.JSONDecodeError: If JSON parsing fails
    """
    if not isinstance(value, str):
        raise ValueError(f"Expected string value, got {type(value)}")

    value = value.strip()

    if type_hint == "str":
        return value

    elif type_hint == "int":
        try:
            return int(value)
        except ValueError as e:
            raise ValueError(f"Cannot convert '{value}' to int: {e}") from e

    elif type_hint == "float":
        try:
            return float(value)
        except ValueError as e:
            raise ValueError(f"Cannot convert '{value}' to float: {e}") from e

    elif type_hint == "bool":
        # Handle various boolean representations
        if value.lower() in ("true", "1", "yes", "on", "enabled"):
            return True
        elif value.lower() in ("false", "0", "no", "off", "disabled"):
            return False
        else:
            raise ValueError(
                f"Cannot convert '{value}' to bool. Use 'true'/'false', '1'/'0', 'yes'/'no', etc."
            )

    elif type_hint == "json":
        if not value:
            return {}
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

    else:
        raise ValueError(f"Unknown type hint: {type_hint}")


def serialize_setting_value(value: Any, type_hint: str) -> str:  # noqa: ANN401
    """Serialize a value to string for storage.

    Args:
        value: Value to serialize
        type_hint: Type hint for proper serialization

    Returns:
        String representation of the value

    Raises:
        ValueError: If value cannot be serialized
    """
    if type_hint == "str":
        return str(value)

    elif type_hint == "int":
        if not isinstance(value, int | float) and not str(value).isdigit():
            raise ValueError(f"Cannot serialize {value} as int")
        return str(int(value))

    elif type_hint == "float":
        if not isinstance(value, int | float):
            try:
                float(value)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Cannot serialize {value} as float") from e
        return str(float(value))

    elif type_hint == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, str):
            return value.lower()
        else:
            return "true" if value else "false"

    elif type_hint == "json":
        if isinstance(value, str):
            # Try to parse as JSON to validate
            try:
                json.loads(value)
                return value
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON string: {value}") from e
        else:
            return json.dumps(value, ensure_ascii=False, indent=None)

    else:
        raise ValueError(f"Unknown type hint: {type_hint}")


def validate_setting_value(value: str, type_hint: str) -> bool:
    """Validate if a string value can be parsed to the specified type.

    Args:
        value: String value to validate
        type_hint: Type hint to validate against

    Returns:
        True if value can be parsed, False otherwise
    """
    try:
        parse_setting_value(value, type_hint)  # type: ignore
        return True
    except (ValueError, json.JSONDecodeError):
        return False


def get_typed_setting_value(key: str, type_hint: str, default: Any = None) -> Any:  # noqa: ANN401
    """Get a setting value and parse it to the appropriate type.

    This is a convenience function that combines getting the setting
    from the database and parsing it.

    Args:
        key: Setting key
        type_hint: Expected type ('str', 'int', 'float', 'bool', 'json')
        default: Default value if setting not found

    Returns:
        Parsed setting value or default
    """
    from ..database import get_setting_value

    raw_value = get_setting_value(key)
    if raw_value is None:
        return default

    try:
        return parse_setting_value(raw_value, type_hint)  # type: ignore
    except (ValueError, json.JSONDecodeError):
        # If parsing fails, return default
        return default
