"""Task modules for Celery workers"""

# Import learning_tasks conditionally to avoid breaking the app
# if pydantic-ai dependencies are not properly installed
try:
    from . import learning_tasks  # noqa: F401
except ImportError as e:
    import warnings

    warnings.warn(
        f"Failed to import learning_tasks module: {e}. "
        "LLM auto-labeling functionality will not be available. "
        "To enable it, ensure pydantic-ai and its dependencies are properly installed.",
        ImportWarning,
        stacklevel=2,
    )
