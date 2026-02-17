"""Entry type registry for class-based and module-based entry types.

This module provides backward compatibility during the migration from function-based
modules to class-based entry types. It allows both systems to coexist and provides
utilities to check which system an entry type uses.
"""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .base import EntryTypeBase

T = TypeVar("T", bound="EntryTypeBase")

# Global registry of entry type classes
_ENTRY_TYPE_CLASSES: dict[str, type["EntryTypeBase"]] = {}


def register_entry_type(entry_type_class: type[T]) -> type[T]:
    """Decorator to register an entry type class.

    This decorator adds the entry type class to the global registry,
    making it available via get_entry_type_class() and get_entry_type_instance().

    Args:
        entry_type_class: The entry type class to register. Must have a
            get_entry_type() class method that returns a string identifier.

    Returns:
        The unmodified class (for use as a decorator)

    Example:
        @register_entry_type
        class SingleTextEntry(EntryTypeBase):
            entry_type = "single_text"
            template_path = "entry_types/single_text.html"
            ...
    """
    type_name = entry_type_class.get_entry_type()
    _ENTRY_TYPE_CLASSES[type_name] = entry_type_class
    return entry_type_class


def get_entry_type_class(type_name: str) -> type | None:
    """Get entry type class by name.

    Args:
        type_name: Entry type identifier (e.g., "single_text", "patient")

    Returns:
        Entry type class if registered, None otherwise
    """
    return _ENTRY_TYPE_CLASSES.get(type_name)


def get_entry_type_instance(type_name: str) -> "EntryTypeBase | None":
    """Get entry type instance by name.

    Creates a new instance of the entry type class each time called.
    Consider using a singleton pattern in the entry type module if you need
    to reuse instances (as done in backward compatibility wrappers).

    Args:
        type_name: Entry type identifier (e.g., "single_text", "patient")

    Returns:
        New instance of the entry type class, or None if not registered

    Example:
        instance = get_entry_type_instance("single_text")
        if instance:
            html = instance.render(entry_id, dataset_id=123)
    """
    cls = get_entry_type_class(type_name)
    if cls:
        return cls()
    return None


def list_entry_types() -> list[str]:
    """List all registered entry type names.

    Returns:
        List of entry type identifiers (e.g., ["single_text", "pdf", ...])
    """
    return list(_ENTRY_TYPE_CLASSES.keys())


def is_class_based(type_name: str) -> bool:
    """Check if entry type uses new class-based system.

    During the migration period, this helps determine if an entry type
    has been converted to the class-based system or still uses the old
    module-based function approach.

    Args:
        type_name: Entry type identifier (e.g., "single_text", "patient")

    Returns:
        True if entry type is registered in class system, False otherwise
    """
    return type_name in _ENTRY_TYPE_CLASSES


def get_entry_type_handler(type_name: str) -> "EntryTypeBase | None":
    """Get entry type handler (class instance or module).

    This is a compatibility helper that can return either a class instance
    (for new class-based types) or would fall back to module lookup
    (for old module-based types). However, since we're maintaining backward
    compatibility via wrapper functions, this primarily returns class instances.

    Args:
        type_name: Entry type identifier

    Returns:
        Entry type instance if class-based, None otherwise
    """
    if is_class_based(type_name):
        return get_entry_type_instance(type_name)
    return None


def call_entry_method(type_name: str, method_name: str, *args, **kwargs) -> object:
    """Call a method on an entry type handler.

    This is a convenience function for calling entry type methods
    without manually getting the handler first.

    Args:
        type_name: Entry type identifier
        method_name: Name of method to call (e.g., "render", "search")
        *args: Positional arguments to pass to the method
        **kwargs: Keyword arguments to pass to the method

    Returns:
        Result of the method call

    Raises:
        AttributeError: If method doesn't exist on the entry type
        ValueError: If entry type is not registered

    Example:
        html = call_entry_method("single_text", "render", entry_id, dataset_id=123)
    """
    handler = get_entry_type_handler(type_name)
    if handler is None:
        raise ValueError(f"Entry type '{type_name}' is not registered")

    method = getattr(handler, method_name)
    return method(*args, **kwargs)


def has_entry_method(type_name: str, method_name: str) -> bool:
    """Check if entry type has a specific method.

    Args:
        type_name: Entry type identifier
        method_name: Name of method to check (e.g., "render", "search")

    Returns:
        True if entry type has the method, False otherwise
    """
    handler = get_entry_type_handler(type_name)
    if handler is None:
        return False

    return hasattr(handler, method_name)


def clear_registry() -> None:
    """Clear all registered entry types.

    This is primarily useful for testing. In normal operation, the registry
    is populated when entry type modules are imported.
    """
    _ENTRY_TYPE_CLASSES.clear()
