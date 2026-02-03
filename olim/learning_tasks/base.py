from abc import ABC, abstractmethod
from typing import Any


class BaseState(ABC):
    """Base class for learning task states.

    Each state represents a step in the learning task workflow.
    States can render UI and transition based on user interaction.

    Example initial_setup structure:
    {
        "sequence": [
            {"state": "IntroState", "params": {"title": "Welcome"}},
            {"state": "QuestionState", "params": {"question_id": 1}},
            {"state": "QuestionState", "params": {"question_id": 2}},
            {"state": "SummaryState", "params": {}}
        ]
    }

    The data dict tracks position and stores user responses:
    {
        "position": 0,
        "responses": {...}
    }
    """

    def __init__(self, data: dict[str, Any], params: dict[str, Any] | None = None):
        """Initialize state with task memory and step parameters.

        Args:
            data: Shared memory dict that persists across state transitions
            params: Optional parameters specific to this step in the sequence
        """
        self.data = data
        self.params = params or {}

    @abstractmethod
    def render(self) -> str:
        """Render the user interface for this state.

        Returns:
            HTML string or template name to render
        """
        pass

    @abstractmethod
    def handle(self, action: str, payload: dict[str, Any]) -> int:
        """Handle user interaction and return relative position change.

        Args:
            action: Action identifier from user interaction
            payload: Data submitted by the user

        Returns:
            Relative position change in the sequence:
                0  = stay at current step
                1  = move to next step
                -1 = move to previous step
                n  = jump n steps forward/backward
        """
        pass

    @property
    def name(self) -> str:
        """Return the state name (class name by default)."""
        return self.__class__.__name__