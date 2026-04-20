"""Learning tasks for OLIM - LLM-powered auto-labeling"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, create_model
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

from .. import app as flask_app, entry_types
from ..celery_app import app
from ..database import (
    add_entry_label,
    get_entry,
    get_label,
    get_learning_task,
    get_or_create_llm_user,
)
from ..label_types import get_label_type_module, is_free_text_label
from ..settings import DEBUG

if TYPE_CHECKING:
    from celery import Task


@app.task(bind=True, name="learning_tasks.label_queue_with_llm")
def label_queue_with_llm(
    self: Task,
    user_id: int,
    learning_task_id: int,
    label_configs: list[dict],
    datasets: list[int],
    project_id: int,
    ollama_url: str,
    model: str,
    system_prompt: str,
    prompt_template: str,
    thinking: bool = False,
    **kwargs: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """Label a queue of entries using an LLM via Ollama.

    Args:
        self: Celery task instance (bound)
        user_id: User ID performing the labeling
        learning_task_id: LearningTask ID — queue_ids are fetched from its data field
        label_configs: Label configurations [{"id": 1, "name": "Sentiment"}, ...]
        datasets: List of dataset IDs to search for entries
        project_id: Project ID
        ollama_url: Ollama API URL (e.g., http://localhost:11434/v1)
        model: Model name (e.g., llama3.2)
        system_prompt: System prompt for the LLM
        prompt_template: Template for the user prompt with {text}, {label_name}, {label_options}
        thinking: Enable model thinking/reasoning (for deepseek-r1, qwq, etc.)
        **kwargs: Additional task parameters

    Returns:
        Dictionary with results:
            - success: bool
            - total_entries: int
            - labeled_count: int
            - error_count: int
            - errors: list of error dicts
            - stats_by_label: dict of label name to value counts
    """
    with flask_app.app_context():
        llm_user_id = get_or_create_llm_user().id

        learning_task = get_learning_task(learning_task_id)
        if not learning_task:
            return {"success": False, "error": f"Learning task {learning_task_id} not found"}
        queue_ids: list[str] = (learning_task.data or {}).get("queue_ids", [])

        # Setup Ollama model using OllamaProvider
        # This is the correct way to use Ollama with PydanticAI
        ollama_model = OpenAIChatModel(
            model_name=model,
            provider=OllamaProvider(base_url=ollama_url),
        )

        max_consecutive_errors: int = kwargs.get("max_consecutive_errors", 3)
        success_count = 0
        consecutive_errors = 0
        early_stop = False
        early_stop_error: str | None = None
        errors = []
        stats_by_label: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        debug_conversations: list[dict] = []

        for idx, entry_id in enumerate(queue_ids):
            try:
                # 1. Find entry across datasets
                entry_obj = None
                dataset_id = None

                for ds_id in datasets:
                    # Try to get entry from this dataset
                    entry_obj = get_entry((ds_id, entry_id), by="composite")
                    if entry_obj:
                        dataset_id = ds_id
                        break

                if not entry_obj or not dataset_id:
                    errors.append({"entry_id": entry_id, "error": "Entry not found"})
                    continue

                # 2. Extract all text from entry
                entry_instance = entry_types.get_entry_type_instance(entry_obj.type)
                if not entry_instance:
                    errors.append(
                        {"entry_id": entry_id, "error": f"Unknown entry type: {entry_obj.type}"}
                    )
                    continue

                df = entry_instance.extract_texts(entry_id, dataset_id=dataset_id)

                # Combine all text columns (skip entry_id column)
                text_parts = []
                for col in df.columns:
                    if col != "entry_id":
                        text_parts.append(str(df[col].iloc[0]))
                full_text = "\n\n".join(text_parts)

                # 3. For each label, create Pydantic model and get prediction
                for label_config in label_configs:
                    label = get_label(label_config["id"])
                    if not label:
                        continue

                    # Get label type module and options
                    label_module = get_label_type_module(label.label_type)
                    options = label_module.get_label_options()

                    # Determine if this is a predefined label or free text
                    if is_free_text_label(label.label_type):
                        # Free text - use string output
                        output_model = str
                        label_options_str = "(Provide your response as free text)"
                    else:
                        # Predefined options - create Literal type for validation
                        # options format: [("sim", "icon", "check-circle-fill", "green"), ...]
                        valid_values = tuple(opt[0] for opt in options)

                        # Create Pydantic model with Literal for strict validation
                        output_model = create_model(
                            f"{label.name}Response",
                            value=(
                                Literal[valid_values],  # type: ignore[valid-type]
                                Field(description=f"Label value for {label.name}"),
                            ),
                        )

                        label_options_str = "\n".join([f"- {opt[0]}" for opt in options])

                    # Format prompt
                    label_description = (label_config.get("description") or "").strip()
                    user_prompt = prompt_template.format(
                        text=full_text,
                        label_name=label.name,
                        label_options=label_options_str,
                        label_description=label_description,
                    )

                    # Create agent with output validation
                    # Note: pydantic-ai uses 'output_type' parameter (not 'result_type')
                    agent = Agent(
                        ollama_model,
                        output_type=output_model,
                        system_prompt=system_prompt,
                        retries=5,  # Increase retries for validation failures
                    )

                    # Run inference (PydanticAI handles validation automatically)
                    # Pass think=True via extra_body for models that support it (deepseek-r1, qwq…)
                    run_kwargs: dict[str, Any] = {}
                    if thinking:
                        run_kwargs["model_settings"] = {"extra_body": {"think": True}}
                    result = agent.run_sync(user_prompt, **run_kwargs)

                    # Extract value (either string or .value attribute)
                    if is_free_text_label(label.label_type):
                        predicted_value = result.output.strip()
                    else:
                        predicted_value = result.output.value  # type: ignore[attr-defined]

                    # Capture raw conversation in debug mode
                    if DEBUG:
                        import json as _json

                        debug_conversations.append(
                            {
                                "entry_id": entry_id,
                                "label": label.name,
                                "predicted": predicted_value,
                                "messages": _json.loads(result.all_messages_json()),
                            }
                        )

                    # Apply label to entry
                    add_entry_label(
                        label_id=label.id,
                        entry_uid=entry_obj.id,
                        user_id=llm_user_id,
                        value=predicted_value,
                        metadata={
                            "model": model,
                            "ollama_url": ollama_url,
                            "system_prompt": system_prompt,
                            "prompt_template": prompt_template,
                            "thinking": thinking,
                        },
                    )

                    success_count += 1
                    stats_by_label[label.name][predicted_value] += 1

                # Successful entry — reset consecutive error counter
                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1

                # Get label name safely
                label_name = "unknown"
                try:
                    if label is not None:  # type: ignore[possibly-undefined]
                        label_name = label.name  # type: ignore[possibly-undefined]
                except (NameError, AttributeError):
                    pass

                errors.append(
                    {
                        "entry_id": entry_id,
                        "label": label_name,
                        "error": str(e),
                    }
                )

                # Stop early if errors keep repeating — likely a configuration problem
                if consecutive_errors >= max_consecutive_errors:
                    early_stop = True
                    early_stop_error = str(e)
                    break

            # Update progress
            progress = ((idx + 1) / len(queue_ids)) * 100
            meta: dict[str, Any] = {
                "status": f"Labeled {idx + 1}/{len(queue_ids)} entries",
                "progress": progress,
            }
            if DEBUG:
                meta["debug_conversations"] = debug_conversations
            self.update_state(state="PROCESSING", meta=meta)

        return {
            "success": True,
            "early_stop": early_stop,
            "early_stop_error": early_stop_error,
            "total_entries": len(queue_ids),
            "labeled_count": success_count,
            "error_count": len(errors),
            "errors": errors,
            "stats_by_label": dict(stats_by_label),
            "debug_conversations": debug_conversations if DEBUG else [],
        }
