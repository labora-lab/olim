from dataclasses import dataclass

from sqlalchemy.orm import Session


class NoTargetFieldError(Exception):
    """The scheme has no select field to use as the training target."""


class NotEnoughLabelsError(Exception):
    """Fewer than two labeled classes — nothing to train a classifier on."""


@dataclass(frozen=True, slots=True)
class DataBundle:
    """The labeled training set for one run, loaded once by the task and handed
    to the runners. Everything is row-aligned by index: row i is item_ids[i],
    texts[i], labels[i]. `classes` maps a class index back to its option_id."""

    item_ids: list[int]
    texts: list[str]
    labels: list[int]
    classes: list[int]  # class idx -> option_id
    n_classes: int


def load_training_data(session: Session, dataset_id: int, scheme_id: int) -> DataBundle:
    """Build the training set from a dataset + scheme. Target is the first
    `select` field; its option ids are label-encoded to class indices. Only
    items that carry a label for that field are included.

    ponytail: materializes every item + annotation in RAM via .list(). Fine for
    now; at millions of rows stream with yield_per / a server-side cursor (and
    push X/labels out-of-core) — this loader is the only place data enters, so
    the runners and the accumulator contract don't change when it does.
    """
    from olim.repositories import AnnotationRepository, ItemRepository, SchemeRepository

    scheme = SchemeRepository(session).get(scheme_id)
    if scheme is None:
        raise NoTargetFieldError(f"scheme {scheme_id} not found")
    target = next((f for f in scheme.fields if f.type == "select"), None)
    if target is None:
        raise NoTargetFieldError(f"scheme {scheme_id} has no select field")

    # item_id -> option_id (first annotation per item; the value of a select
    # annotation is its option_id).
    label_by_item: dict[int, int] = {}
    for ann in AnnotationRepository(session).list(field_id=target.id):
        if ann.item_id not in label_by_item and isinstance(ann.value, int):
            label_by_item[ann.item_id] = ann.value

    # label-encode the option ids actually present, sorted for determinism.
    classes = sorted(set(label_by_item.values()))
    class_idx = {option_id: i for i, option_id in enumerate(classes)}
    if len(classes) < 2:
        raise NotEnoughLabelsError(f"need >= 2 labeled classes, got {len(classes)}")

    item_ids: list[int] = []
    texts: list[str] = []
    labels: list[int] = []
    for item in ItemRepository(session).list(dataset_id=dataset_id):
        if item.id in label_by_item:
            item_ids.append(item.id)
            texts.append(item.content)
            labels.append(class_idx[label_by_item[item.id]])

    return DataBundle(
        item_ids=item_ids,
        texts=texts,
        labels=labels,
        classes=classes,
        n_classes=len(classes),
    )
