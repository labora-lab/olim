from typing import Generic, Iterable, TypeVar, Any
from copy import copy

import numpy as np


T = TypeVar("T")


def dict_to_list(x: dict[int, Any]) -> list[Any]:
    return [x[i] for i in range(len(x))]


def sanitize_data(data):
    """
    Recursively sanitizes all data in dict, list, array, tuple, or set by converting
    any numpy types into native Python types.

    Args:
        data (any): The input data to sanitize. Can be a dict, list, array, tuple, set,
                    or a single value.

    Returns:
        any: Sanitized data with no numpy types.
    """
    if isinstance(data, dict):
        return {key: sanitize_data(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(sanitize_data(item) for item in data)
    elif isinstance(data, set):
        return {sanitize_data(item) for item in data}
    elif isinstance(data, np.ndarray):
        return sanitize_data(data.tolist())
    elif isinstance(data, (np.integer, np.floating)):
        return data.item()
    elif isinstance(data, np.bool_):
        return bool(data)
    elif isinstance(data, np.str_):
        return str(data)
    else:
        return data


class SlotSet(Generic[T]):
    """
    A custom data structure that provides efficient operations for
    maintaining a collection of unique elements, supporting removal
    and indexing operations with dynamic updates to indices.

    Attributes:
        array (list[T]): A list containing the elements in the SlotSet.
        mapping (dict[T, int]): A dictionary mapping elements to their indices in the `array`.

    Args:
        elems (Iterable[T] | None): An optional iterable of elements to initialize the SlotSet with.
    """

    def __init__(self, elems: Iterable[T] | None = None):
        if elems is None:
            elems = []
        self.array = list(elems)
        self.mapping = {x: i for i, x in enumerate(elems)}

    def shallow_copy(self) -> "SlotSet[T]":
        """
        Creates a shallow copy of the SlotSet, including its internal state.

        Returns:
            SlotSet[T]: A shallow copy of the current SlotSet.
        """
        out = copy(self)
        out.array = copy(self.array)
        out.mapping = copy(self.mapping)
        return out

    def remove(self, x: T) -> None:
        """
        Removes an element from the SlotSet.

        Note: This invalidates all indices for subsequent operations
        due to dynamic index reassignment.

        Args:
            x (T): The element to remove.

        Raises:
            KeyError: If the element is not present in the SlotSet.
        """
        if x not in self.mapping:
            raise KeyError(f"element not in SlotSet: {x}")
        i = self.mapping[x]
        del self.mapping[x]
        # Swap-remove: Replace the removed element with the last element
        if i == len(self.array) - 1:
            self.array.pop()
        else:
            self.mapping[self.array[-1]] = i
            self.array[i] = self.array.pop()

    def append(self, x: T) -> None:
        if x in self.array:
            return
        self.mapping[x] = len(self.array)
        self.array.append(x)

    def __len__(self) -> int:
        """
        Returns the number of elements in the SlotSet.

        Returns:
            int: The number of elements in the SlotSet.
        """
        assert len(self.array) == len(self.mapping)
        return len(self.array)

    def __getitem__(self, i: int) -> T:
        """
        Retrieves an element by its index in the SlotSet.

        Args:
            i (int): The index of the element to retrieve.

        Returns:
            T: The element at the specified index.
        """
        return self.array[i]

    def __setitem__(self, i: int, x: T) -> None:
        """
        Replaces the element at a specific index with a new element.

        If the new element already exists, it simply ensures that the element is
        correctly positioned at the specified index.

        Args:
            i (int): The index of the element to replace.
            x (T): The new element to insert.
        """
        old_elem = self.array[i]
        if old_elem == x:
            # No action needed if the element is already correct
            return
        # Update mapping and array only if the element differs
        del self.mapping[old_elem]
        self.array[i] = x
        self.mapping[x] = i

    def __delitem__(self, i: int) -> None:
        """
        Deletes the element at a specific index, removing it from the SlotSet.

        Args:
            i (int): The index of the element to delete.
        """
        x = self.array[i]
        self.remove(x)
