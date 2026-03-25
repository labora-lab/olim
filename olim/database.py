import hashlib
import json
import random
import re
import string
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict

from flask import session
from sqlalchemy import ScalarResult, Select, func
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, declared_attr
from werkzeug.security import generate_password_hash

from . import db

if TYPE_CHECKING:
    from olim.ml.models import MLModel, MLModelPrediction, MLModelVersion


## DB tables
class CreationControl:
    created: Mapped[datetime] = db.mapped_column(nullable=False)
    created_by: Mapped[int] = db.mapped_column(
        db.ForeignKey("users.id", name="fk_created_by"), nullable=False
    )
    is_deleted: Mapped[bool] = db.mapped_column(nullable=False, default=False)
    deleted: Mapped[datetime | None] = db.mapped_column(nullable=True)
    deleted_by: Mapped[int | None] = db.mapped_column(db.Integer, nullable=True)

    @declared_attr
    def creator(cls) -> Mapped["User"]:  # noqa: N805
        return db.relationship(
            "User",
            foreign_keys=[cls.created_by],  # Explicit foreign key
            primaryjoin=f"{cls.__name__}.created_by == User.id",
            uselist=False,
            viewonly=True,
        )


class ProjectDataset(db.Model, CreationControl):
    """Association model for many-to-many relationship between Projects and Datasets"""

    __tablename__ = "project_datasets"

    # Composite primary key
    project_id: Mapped[int] = db.mapped_column(db.ForeignKey("projects.id"), primary_key=True)
    dataset_id: Mapped[int] = db.mapped_column(db.ForeignKey("datasets.id"), primary_key=True)

    # Relationships
    project: Mapped["Project"] = db.relationship(back_populates="project_datasets")
    dataset: Mapped["Dataset"] = db.relationship(back_populates="project_datasets")


class Dataset(db.Model, CreationControl):
    __tablename__ = "datasets"

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    name: Mapped[str] = db.mapped_column(nullable=False)
    learner_key: Mapped[str] = db.mapped_column(nullable=True)
    sep: Mapped[str] = db.mapped_column(nullable=False, default=",")
    encoding: Mapped[str] = db.mapped_column(nullable=False, default="utf-8")

    # Relationships
    project_datasets: Mapped[list["ProjectDataset"]] = db.relationship(back_populates="dataset")
    entries: Mapped[list["Entry"]] = db.relationship(back_populates="dataset")

    # Association proxy to projects through project_datasets relationship
    projects: Mapped[list["Project"]] = association_proxy(
        "project_datasets",
        "project",
        creator=lambda project: ProjectDataset(project=project),
    )  # type: ignore


class Project(db.Model, CreationControl):
    __tablename__ = "projects"

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    name: Mapped[str] = db.mapped_column(nullable=False)

    # Relationships
    project_datasets: Mapped[list["ProjectDataset"]] = db.relationship(back_populates="project")
    labels: Mapped[list["Label"]] = db.relationship(back_populates="project")
    queues: Mapped[list["Queue"]] = db.relationship(back_populates="project")
    learning_tasks: Mapped[list["LearningTask"]] = db.relationship(back_populates="project")

    # Association proxy to datasets through project_datasets relationship
    datasets: Mapped[list["Dataset"]] = association_proxy(
        "project_datasets",
        "dataset",
        creator=lambda dataset: ProjectDataset(dataset=dataset),
    )  # type: ignore


class User(db.Model, CreationControl):
    __tablename__ = "users"

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    name: Mapped[str] = db.mapped_column(nullable=False)
    username: Mapped[str] = db.mapped_column(unique=True, nullable=False)
    password: Mapped[str] = db.mapped_column(nullable=False)
    role: Mapped[str] = db.mapped_column(nullable=False)
    language: Mapped[str | None] = db.mapped_column(nullable=True)

    # Session storage (replaces last_project_id)
    session_data: Mapped[dict | None] = db.mapped_column(db.JSON, nullable=True)


class LabelEntry(db.Model, CreationControl):
    __tablename__ = "label-patient"

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    entry_id: Mapped[int] = db.mapped_column(db.ForeignKey("entries.id"))
    label_id: Mapped[int] = db.mapped_column(db.ForeignKey("labels.id"))
    value: Mapped[str] = db.mapped_column(nullable=True)
    meta: Mapped[dict | None] = db.mapped_column("metadata", db.JSON, nullable=True)

    # Relations
    label: Mapped["Label"] = db.relationship(back_populates="entries")
    entry: Mapped["Entry"] = db.relationship(back_populates="labels")


class ModelPrediction(db.Model):
    """ML model prediction per entry/label — separate from human annotations."""

    __tablename__ = "model_predictions"
    __table_args__ = (
        db.Index("ix_model_predictions_label", "label_id"),
        db.Index("ix_model_predictions_entry_label", "entry_id", "label_id"),
    )

    id: Mapped[int] = db.mapped_column(primary_key=True)
    entry_id: Mapped[int] = db.mapped_column(db.ForeignKey("entries.id"), nullable=False)
    label_id: Mapped[int] = db.mapped_column(db.ForeignKey("labels.id"), nullable=False)
    model_id: Mapped[int] = db.mapped_column(db.ForeignKey("ml_models.id"), nullable=False)
    version_id: Mapped[int] = db.mapped_column(
        db.ForeignKey("ml_model_versions.id"), nullable=False
    )
    value: Mapped[str | None] = db.mapped_column(nullable=True)
    score: Mapped[float | None] = db.mapped_column(nullable=True)
    prediction_set: Mapped[list | None] = db.mapped_column(db.JSON, nullable=True)
    created_at: Mapped[datetime] = db.mapped_column(nullable=False, default=datetime.now)


class Entry(db.Model):
    __tablename__ = "entries"
    __table_args__ = (db.UniqueConstraint("entry_id", "dataset_id", name="uq_entry_id_dataset"),)

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True, autoincrement=True)
    entry_id: Mapped[str] = db.mapped_column(nullable=False)
    type: Mapped[str] = db.mapped_column(nullable=False)
    dataset_id: Mapped[int] = db.mapped_column(db.ForeignKey("datasets.id"), nullable=False)

    # Relationships
    labels: Mapped[list["LabelEntry"]] = db.relationship(back_populates="entry")
    dataset: Mapped["Dataset"] = db.relationship(back_populates="entries")


class Label(db.Model, CreationControl):
    __tablename__ = "labels"

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    name: Mapped[str] = db.mapped_column(nullable=False)
    al_key: Mapped[str] = db.mapped_column(nullable=True)
    priority: Mapped[float] = db.mapped_column(default=1.0, nullable=False)
    project_id: Mapped[int] = db.mapped_column(db.ForeignKey("projects.id"), nullable=False)

    # Label type configuration
    label_type: Mapped[str] = db.mapped_column(
        nullable=True
    )  # string identifier for the label type
    label_settings: Mapped[dict] = db.mapped_column(
        db.JSON, nullable=True
    )  # JSON with type-specific configuration

    metrics: Mapped[list] = db.mapped_column(db.JSON, nullable=True)
    cache: Mapped[list] = db.mapped_column(db.JSON, nullable=True)
    training_counter: Mapped[int] = db.mapped_column(db.Integer, default=0)

    # Learner parameters for active learning configuration
    learner_parameters: Mapped[dict] = db.mapped_column(db.JSON, nullable=True)

    # Auto-labels stored as {COMPOSITE_ID: value} for automatic labeling during active learning
    auto_labels: Mapped[dict] = db.mapped_column(db.JSON, nullable=True)

    ml_model_id: Mapped[int | None] = db.mapped_column(
        db.ForeignKey("ml_models.id"), nullable=True, index=True
    )

    # Relationships
    entries: Mapped[list["LabelEntry"]] = db.relationship(
        back_populates="label", foreign_keys="[LabelEntry.label_id]"
    )
    project: Mapped["Project"] = db.relationship(back_populates="labels")
    ml_model: Mapped["MLModel"] = db.relationship(  # type: ignore
        foreign_keys=[ml_model_id], viewonly=True
    )


class GlobalSetting(db.Model, CreationControl):
    """Global system settings table"""

    __tablename__ = "global_settings"
    __table_args__ = (db.Index("ix_global_settings_category", "category"),)

    # Columns
    key: Mapped[str] = db.mapped_column(db.String(128), primary_key=True)
    display_name: Mapped[str] = db.mapped_column(db.String(256), nullable=False)
    value: Mapped[str] = db.mapped_column(db.Text, nullable=False)
    default_value: Mapped[str] = db.mapped_column(db.Text, nullable=False)
    type: Mapped[str] = db.mapped_column(
        db.String(16), nullable=False
    )  # 'str', 'int', 'float', 'bool', 'json'
    description: Mapped[str | None] = db.mapped_column(db.Text, nullable=True)
    category: Mapped[str | None] = db.mapped_column(db.String(64), nullable=True)


class Queue(db.Model, CreationControl):
    """Queue model for storing entry queues"""

    __tablename__ = "queues"
    __table_args__ = (
        db.Index("ix_queues_project_id", "project_id"),
        db.Index("ix_queues_created", "created"),
    )

    # Columns
    id: Mapped[str] = db.mapped_column(db.String(32), primary_key=True)  # MD5 hash
    name: Mapped[str] = db.mapped_column(db.String(255), nullable=False)
    project_id: Mapped[int] = db.mapped_column(db.ForeignKey("projects.id"), nullable=False)

    # Queue data stored as JSON
    queue_data: Mapped[list] = db.mapped_column(
        db.JSON, nullable=False
    )  # [(dataset_id, entry_id), ...]
    highlight: Mapped[list | None] = db.mapped_column(
        db.JSON, nullable=True
    )  # List of highlight terms
    extra_data: Mapped[dict | None] = db.mapped_column(
        db.JSON, nullable=True
    )  # Additional metadata

    # Computed field
    length: Mapped[int] = db.mapped_column(db.Integer, nullable=False)  # Cached queue length

    # Relationships
    project: Mapped["Project"] = db.relationship(back_populates="queues")


class LearningTask(db.Model, CreationControl):
    __tablename__ = "learning_tasks"

    id: Mapped[int] = db.mapped_column(primary_key=True)
    project_id: Mapped[int] = db.mapped_column(db.ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = db.mapped_column(nullable=False)
    state: Mapped[str] = db.mapped_column(nullable=False)
    position: Mapped[int] = db.mapped_column(default=0, nullable=False)
    data: Mapped[dict] = db.mapped_column(db.JSON, nullable=False)
    initial_setup: Mapped[dict] = db.mapped_column(db.JSON, nullable=False)
    assigned_to: Mapped[int | None] = db.mapped_column(
        db.ForeignKey("users.id"), nullable=True
    )

    # Relationships
    project: Mapped["Project"] = db.relationship(back_populates="learning_tasks")
    assignee: Mapped["User | None"] = db.relationship(foreign_keys=[assigned_to])


class CeleryTaskStatus(db.TypeDecorator):
    """Enum for Celery task states"""

    impl = db.String(20)
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(length=20)

    @property
    def python_type(self) -> type:
        return str

    def process_bind_param(self, value: str, _) -> str:
        valid_states = {"PENDING", "STARTED", "RETRY", "SUCCESS", "FAILURE", "REVOKED"}
        if value not in valid_states:
            raise ValueError(f"Invalid task state: {value}")
        return value


class CeleryTask(db.Model, CreationControl):
    __tablename__ = "celery_tasks"
    __table_args__ = (
        db.Index("ix_celery_tasks_status", "status"),
        db.Index("ix_celery_tasks_created_by", "created_by"),
        db.Index("ix_celery_tasks_date_completed", "date_completed"),
    )

    # Core task information
    id: Mapped[str] = db.mapped_column(
        db.String(36),
        primary_key=True,  # Celery task UUID
    )
    status: Mapped[str] = db.mapped_column(CeleryTaskStatus(), nullable=False, default="PENDING")
    task_name: Mapped[str] = db.mapped_column(db.String(128), nullable=False)
    description: Mapped[str] = db.mapped_column(db.String(128), nullable=True)

    # Task arguments and results
    args: Mapped[dict | None] = db.mapped_column(db.JSON, nullable=True)
    kwargs: Mapped[dict | None] = db.mapped_column(db.JSON, nullable=True)
    result: Mapped[dict | None] = db.mapped_column(db.JSON, nullable=True)

    # Error tracking
    error: Mapped[str | None] = db.mapped_column(db.Text, nullable=True)
    traceback: Mapped[str | None] = db.mapped_column(db.Text, nullable=True)

    # Timing information
    date_started: Mapped[datetime | None] = db.mapped_column(nullable=True)
    date_completed: Mapped[datetime | None] = db.mapped_column(nullable=True)

    # Relationships
    created_by: Mapped[int] = db.mapped_column(db.ForeignKey("users.id"), nullable=False)
    user: Mapped["User"] = db.relationship()

    def update_status(self, status: str) -> None:
        """Update task status with timestamp handling"""
        valid_transitions = {
            "PENDING": {"STARTED", "SUCCESS", "REVOKED"},
            "STARTED": {"SUCCESS", "FAILURE", "RETRY", "REVOKED"},
            "RETRY": {"STARTED", "FAILURE", "REVOKED"},
        }

        if self.status == status:
            return

        if status not in valid_transitions[self.status]:
            return

        if status in ("STARTED", "RETRY"):
            self.date_started = datetime.utcnow()
        elif status in ("SUCCESS", "FAILURE", "REVOKED"):
            self.date_completed = datetime.utcnow()

        self.status = status

    @classmethod
    def create_task(
        cls,
        task_id: str,
        task_name: str,
        user_id: int,
        args=None,
        kwargs=None,
        description="",
    ) -> "CeleryTask":
        """Helper to create a new task record"""
        return cls(
            id=task_id,
            task_name=task_name,
            description=description,
            status="PENDING",
            args=args,
            kwargs=kwargs,
            created_by=user_id,
            created=datetime.now(),
        )

    def __repr__(self) -> str:
        return f"<CeleryTask {self.id} [{self.status}]>"


## Database Manipulation Functions


# region General Utility Functions
# --------------------------------
def del_controled(obj: CreationControl, user_id: int) -> None:
    """Soft-delete any creation-controlled record.

    Args:
        obj: Record to mark as deleted
        user_id: ID of user performing deletion
    """
    if not obj.is_deleted:
        obj.is_deleted = True
        obj.deleted = datetime.now()
        obj.deleted_by = user_id
        db.session.commit()


def get_setup_step() -> str | None:
    """Determine required initialization steps.

    Returns:
        String representing current setup step or None if setup is complete
    """
    if "is_setup" not in session:
        session["is_setup"] = False
    if not session["is_setup"]:
        if not db.session.execute(db.select(User.id)).scalar():
            return "add-user"
        elif not db.session.execute(db.select(Project.id)).scalar():
            return "add-project"
        elif not db.session.execute(db.select(Dataset.id)).scalar():
            return "add-data"
        else:
            session["is_setup"] = True
    return None


def get_by(table: ..., col: str, idt: int | str, filter_deleted=True) -> ...:
    """Generic record retrieval helper.

    Args:
        table: Model class to query
        col: Column name to filter by
        idt: Value to match in column
        filter_deleted: Whether to exclude deleted records

    Returns:
        Found record or None
    """
    if col == "id":
        obj = db.session.get(table, idt)
        if obj and filter_deleted and hasattr(obj, "is_deleted") and obj.is_deleted:
            return None
        return obj
    filter_params = {col: idt}
    if filter_deleted:
        filter_params["is_deleted"] = False
    try:
        return db.session.execute(db.select(table).filter_by(**filter_params)).scalar_one()
    except db.orm.exc.NoResultFound:
        return None


def init_db(
    admin_user: str = "admin",
    admin_name: str = "Administrator",
    admin_passwd: str | None = None,
) -> ...:
    """Initialize database with default admin user.

    Args:
        admin_user: Default admin username
        admin_name: Default admin display name
        admin_passwd: Optional admin password

    Returns:
        None
    """
    db.create_all()
    if not get_user(admin_user, "username"):
        password = admin_passwd or "".join(
            random.choices(string.ascii_uppercase + string.digits, k=12)
        )
        user = insert_user(
            name=admin_name,
            username=admin_user,
            hashed_password=generate_password_hash(password),
            role="admin",
            creator=1,
        )
        user.created_by = user.id
        db.session.commit()


# endregion


# region User Management
# ---------------------
def get_user(idt: int | str, by: str = "id") -> User | None:
    """Retrieve user by ID or username.

    Args:
        idt: User ID or username
        by: Field to search by ('id' or 'username')

    Returns:
        User object or None if not found
    """
    return get_by(User, by, idt, True)


def get_users() -> list[User]:
    """Retrieve all active users.

    Returns:
        List of User objects sorted by username
    """
    return db.session.execute(
        db.select(User)
        .filter_by(is_deleted=False)
        .filter(User.username != LLM_USER_USERNAME)
        .order_by(User.username)
    ).scalars()


def insert_user(username: str, hashed_password: str, role: str, creator: int, **kwargs) -> User:
    """Create new user account.

    Args:
        username: Unique username
        hashed_password: Pre-hashed password
        role: User role ('admin' or 'user')
        creator: ID of creating user
        **kwargs: Additional user attributes

    Returns:
        Newly created User object
    """
    user = User(
        name=kwargs.get("name", ""),
        username=username,
        password=hashed_password,
        role=role,
        created=datetime.now(),
        created_by=creator,
        is_deleted=False,
    )
    db.session.add(user)
    db.session.commit()
    return user


LLM_USER_USERNAME = "__llm__"


def get_or_create_llm_user() -> User:
    """Return the virtual LLM user, creating it if it doesn't exist.

    This user is used as the author of all LLM-generated labels so they can be
    differentiated from human labels.  The account has an unusable password and
    cannot be used to log in.
    """
    user = db.session.execute(
        db.select(User).filter_by(username=LLM_USER_USERNAME)
    ).scalar_one_or_none()
    if user:
        return user

    # Find any existing user to satisfy the created_by FK
    creator_id: int = db.session.execute(
        db.select(User.id).order_by(User.id).limit(1)
    ).scalar_one()

    user = User(
        name="LLM Auto-Labeler",
        username=LLM_USER_USERNAME,
        password="!",  # unusable — no valid bcrypt hash starts with "!"
        role="annotator",
        created=datetime.now(),
        created_by=creator_id,
        is_deleted=False,
    )
    db.session.add(user)
    db.session.flush()
    user.created_by = user.id  # self-owned record
    db.session.commit()
    return user


def update_user(identification: int | str, by: str = "id", **parameters) -> User:
    """Update user attributes.

    Args:
        identification: User ID or username
        by: Field to search by ('id' or 'username')
        parameters: Attributes to update

    Returns:
        Updated User object
    """
    user = get_user(identification, by)
    if not user:
        raise ValueError("User not found")
    for key, value in parameters.items():
        setattr(user, key, value)
    db.session.commit()
    return user


def update_user_password(
    identification: int | str, new_password: str, by: str = "id"
) -> User | None:
    """Update user password.

    Args:
        identification: User ID or username
        new_password: New plaintext password
        by: Field to search by ('id' or 'username')

    Returns:
        Updated User object
    """
    user = get_user(identification, by)
    if user is not None:
        user.password = generate_password_hash(new_password)
        db.session.commit()
        return user


# endregion


# region Session Management
# ------------------------
def save_session(user_id: int, session_data: dict) -> None:
    """Save user session data to the database.

    Args:
        user_id: ID of the user to save session for
        session_data: Dictionary of session data to persist

    Example:
        save_session(123, {'last_project': 5, 'page_size': 25})
    """
    user = get_user(user_id)
    if user:
        user.session_data = session_data
        db.session.commit()


def load_session(user_id: int) -> dict:
    """Load user session data from the database.

    Args:
        user_id: ID of the user to load session for

    Returns:
        Dictionary of stored session data (empty dict if none exists)

    Example:
        session = load_session(123)
        # Returns {'last_project': 5, 'page_size': 25}
    """
    user = get_user(user_id)
    return user.session_data if user and user.session_data else {}


def update_session(user_id: int, **updates) -> None:
    """Update specific session values without overwriting entire session.

    Args:
        user_id: ID of the user to update session for
        **updates: Key-value pairs to update

    Example:
        update_session(123, last_project=6, new_feature_flag=True)
    """
    user = get_user(user_id)
    if user:
        current = user.session_data or {}
        current.update(updates)
        user.session_data = current
        db.session.commit()


def clear_session(user_id: int) -> None:
    """Remove all session data for a user.

    Args:
        user_id: ID of the user to clear session for
    """
    user = get_user(user_id)
    if user and user.session_data:
        user.session_data = None
        db.session.commit()


# endregion


# region Project Management
# ------------------------
def new_project(project_name, user_id) -> Project:
    """Create new project.

    Args:
        project_name: Name for new project
        user_id: ID of creating user

    Returns:
        New Project object
    """
    project = Project(
        name=project_name,
        created_by=user_id,
        created=datetime.now(),
        is_deleted=False,
    )
    db.session.add(project)
    db.session.commit()
    return project


def get_projects() -> list[Project]:
    """Retrieve all active projects.

    Returns:
        List of Project objects sorted by name
    """
    return list(
        db.session.execute(
            db.select(Project).filter_by(is_deleted=False).order_by(Project.name)
        ).scalars()
    )


def get_project(idt: int | str, by: str = "id") -> Project | None:
    """Retrieve a project by specified criteria.

    Args:
        idt: Project ID or other identifier value
        by: Column name to search by (default 'id')

    Returns:
        Project object if found, None otherwise
    """
    return get_by(Project, by, idt, True)


# endregion


# region Dataset Management
# ------------------------
def new_dataset(dataset_name, user_id, learner_key=None, sep=",", encoding="utf-8") -> Dataset:
    """Create new dataset.

    Args:
        dataset_name: Name for new dataset
        user_id: ID of creating user
        learner_key: Optional learner key
        sep: CSV column separator (default ",")
        encoding: File encoding (default "utf-8")

    Returns:
        New Dataset object
    """
    dataset = Dataset(
        name=dataset_name,
        learner_key=learner_key,
        created_by=user_id,
        created=datetime.now(),
        is_deleted=False,
        sep=sep,
        encoding=encoding,
    )
    db.session.add(dataset)
    db.session.commit()
    return dataset


def get_datasets(project_id: int | None = None, non_empty: bool = False) -> list[Dataset]:
    """Retrieve datasets with optional project filtering and non-empty check.

    Args:
        project_id: Optional project ID to filter by
        non_empty: Only return datasets with entries (default False)

    Returns:
        List of Dataset objects ordered by name
    """
    query = db.select(Dataset).filter_by(is_deleted=False)

    # Filter by project if specified
    if project_id is not None:
        query = (
            query.join(ProjectDataset)
            .filter(ProjectDataset.project_id == project_id)
            .filter(ProjectDataset.is_deleted == False)  # noqa
        )

    # Filter out empty datasets if requested
    if non_empty:
        query = query.where(db.exists().where(Entry.dataset_id == Dataset.id))

    return db.session.execute(query.order_by(Dataset.name)).scalars()


def get_dataset(idt: int | str, by: str = "id") -> Dataset | None:
    """Retrieve a dataset by specified criteria.

    Args:
        idt: Dataset ID or other identifier value
        by: Column name to search by (default 'id')

    Returns:
        Dataset object if found, None otherwise
    """
    return get_by(Dataset, by, idt, True)


def get_dataset_stats() -> dict[int, dict]:
    """Get statistics for all datasets including entry counts and associated projects.

    Returns:
        dict: {
            dataset_id: {
                'entry_count': int,
                'projects': list[name: str]
            }
        }
    """
    # Get base dataset query
    base_query = (
        db.select(
            Dataset.id,
            Dataset.name,
            func.count(Entry.id).label("entry_count"),
            Project.id.label("project_id"),
            Project.name.label("project_name"),
        )
        .outerjoin(Entry, Dataset.id == Entry.dataset_id)
        .outerjoin(ProjectDataset, Dataset.id == ProjectDataset.dataset_id)
        .outerjoin(Project, ProjectDataset.project_id == Project.id)
        .filter(
            Dataset.is_deleted == False,  # noqa
            ProjectDataset.is_deleted == False,  # noqa
        )
        .group_by(Dataset.id, Project.id)
    )

    results = db.session.execute(base_query).all()

    # Organize results
    stats = defaultdict(lambda: {"entry_count": 0, "projects": []})

    for row in results:
        dataset_id = row.id
        stats[dataset_id]["entry_count"] = row.entry_count

        if row.project_id:  # Only add projects with valid associations
            stats[dataset_id]["projects"].append(row.project_name)

    return dict(stats)


# endregion


# region Dataset-Project Relations
# ------------------------------
def link_dataset_to_project(dataset_id: int, project_id: int, user_id: int) -> ProjectDataset:
    """Associate a dataset with one or more projects.

    Args:
        dataset_id: ID of dataset to link
        project_id: ID of project to associate
        user_id: ID of user creating the association

    Returns:
        Created ProjectDataset association object

    Example:
        link_dataset_to_project(dataset_id=5, project_id=3, user_id=1)
    """
    # Check existing association
    existing = db.session.execute(
        db.select(ProjectDataset).filter_by(
            project_id=project_id, dataset_id=dataset_id, is_deleted=False
        )
    ).scalar()

    if existing:
        return existing

    association = ProjectDataset(
        project_id=project_id,
        dataset_id=dataset_id,
        created=datetime.now(),
        created_by=user_id,
        is_deleted=False,
    )
    db.session.add(association)
    db.session.commit()
    return association


def unlink_dataset_from_project(dataset_id: int, project_id: int, user_id: int) -> None:
    """Remove association between dataset and project (soft delete).

    Args:
        dataset_id: ID of dataset to unlink
        project_id: ID of project to remove from
        user_id: ID of user performing the action
    """
    association = db.session.execute(
        db.select(ProjectDataset).filter_by(
            project_id=project_id, dataset_id=dataset_id, is_deleted=False
        )
    ).scalar_one()

    del_controled(association, user_id)


def get_projects_for_dataset(dataset_id: int) -> list[Project]:
    """Get all projects associated with a dataset.

    Args:
        dataset_id: ID of dataset to check

    Returns:
        List of Project objects
    """
    return db.session.execute(
        db.select(Project)
        .join(ProjectDataset)
        .filter(ProjectDataset.dataset_id == dataset_id, ProjectDataset.is_deleted == False)  # noqa
    ).scalars()


def get_datasets_for_project(project_id: int) -> list[Dataset]:
    """Get all datasets associated with a project.

    Args:
        project_id: ID of project to check

    Returns:
        List of Dataset objects
    """
    return db.session.execute(
        db.select(Dataset)
        .join(ProjectDataset)
        .filter(ProjectDataset.project_id == project_id, ProjectDataset.is_deleted == False)  # noqa
    ).scalars()


def get_all_dataset_relations() -> list[ProjectDataset]:
    """Get all active dataset-project associations.

    Returns:
        List of ProjectDataset objects
    """
    return db.session.execute(db.select(ProjectDataset).filter_by(is_deleted=False)).scalars()


def is_dataset_linked(dataset_id: int, project_id: int) -> bool:
    """Check if dataset is linked to a specific project.

    Args:
        dataset_id: ID of dataset to check
        project_id: ID of project to check

    Returns:
        True if active association exists
    """
    return db.session.query(
        db.session.execute(
            db.select(ProjectDataset.project_id).filter_by(
                project_id=project_id, dataset_id=dataset_id, is_deleted=False
            )
        ).exists()
    ).scalar()


# endregion


# region Label Management
# ----------------------
def new_label(
    label, user_id, project_id, al_id=None, label_type=None, label_settings=None
) -> Label:
    """Create new classification label.

    Args:
        label: Display name for label
        user_id: ID of creating user
        project_id: Associated project ID
        al_id: Active learning identifier (optional)
        label_type: Type identifier for the label (optional)
        label_settings: JSON settings specific to the label type (optional)

    Returns:
        New Label object
    """
    label = Label(
        name=label,
        project_id=project_id,
        created_by=user_id,
        created=datetime.now(),
        is_deleted=False,
        al_key=al_id,
        label_type=label_type,
        label_settings=label_settings or {},
    )
    db.session.add(label)
    db.session.commit()
    return label


def get_labels(project_id: int | None = None) -> list[Label]:
    """Retrieve labels with optional project filtering.

    Args:
        project_id (int | None): Optional project ID to filter by

    Returns:
        list[Label]: List of Label objects ordered by name
    """
    query = db.select(Label).filter_by(is_deleted=False)

    if project_id is not None:
        query = query.filter_by(project_id=project_id)

    return db.session.execute(query.order_by(Label.name)).scalars().all()


def del_label(label_id, user_id) -> Label:
    """Soft-delete label and its associations.

    Args:
        label_id: ID of label to delete
        user_id: ID of user performing deletion

    Returns:
        Deleted Label object
    """
    label = db.get_or_404(Label, label_id)
    for le in label.entries:
        del_controled(le, user_id)
    del_controled(label, user_id)
    return label


def get_label(idt: int, by: str = "id") -> Label | None:
    """Retrieve label by ID.

    Args:
        idt: Label ID
        by: Field to search by (default 'id')

    Returns:
        Label object or None if not found
    """
    return get_by(Label, by, idt, True)


def get_label_entries(label_id: int) -> list[LabelEntry]:
    """Return all non-null LabelEntry rows for a label.

    Args:
        label_id: Target label ID

    Returns:
        List of LabelEntry objects with their associated Entry loaded
    """
    return (
        db.session.query(LabelEntry)
        .filter(LabelEntry.label_id == label_id, LabelEntry.value.isnot(None))
        .all()
    )


def get_labeled_entry_ids(label_id: int) -> set[int]:
    """Return the set of Entry DB PKs that already have a value for this label.

    Args:
        label_id: Target label ID

    Returns:
        Set of Entry.id integers that have a non-null, non-deleted label value
    """
    rows = (
        db.session.query(LabelEntry.entry_id)
        .filter(
            LabelEntry.label_id == label_id,
            LabelEntry.value.isnot(None),
            LabelEntry.is_deleted.is_(False),
        )
        .all()
    )
    return {row[0] for row in rows}


# endregion


# region Queue Management
# ----------------------
def new_queue(
    queue_data: list[tuple[int, str]],
    name: str,
    project_id: int,
    user_id: int,
    highlight: list[str] | None = None,
    **extra_data: dict,
) -> Queue:
    """Create new queue.

    Args:
        queue_data: List of (dataset_id, entry_id) tuples
        name: Queue name (required)
        project_id: Associated project ID
        user_id: ID of creating user
        highlight: Optional list of terms to highlight
        **extra_data: Additional metadata

    Returns:
        New Queue object
    """
    # Generate ID from queue content (for URL compatibility)
    queue_id = hashlib.md5(json.dumps(queue_data).encode("utf-8")).hexdigest()

    # Check if queue with this ID already exists
    existing = db.session.get(Queue, queue_id)
    if existing and not existing.is_deleted:
        return existing

    queue = Queue(
        id=queue_id,
        name=name,
        project_id=project_id,
        queue_data=queue_data,
        highlight=highlight,
        extra_data=extra_data or {},
        length=len(queue_data),
        created=datetime.now(),
        created_by=user_id,
        is_deleted=False,
    )
    db.session.add(queue)
    db.session.commit()
    return queue


def get_queue_by_id(queue_id: str, project_id: int) -> Queue | None:
    """Retrieve queue by ID and project.

    Args:
        queue_id: Queue ID (MD5 hash)
        project_id: Project ID for validation

    Returns:
        Queue object or None if not found
    """
    queue = db.session.get(Queue, queue_id)
    if queue and not queue.is_deleted and queue.project_id == project_id:
        return queue
    return None


def get_queues_for_project(project_id: int) -> list[Queue]:
    """Retrieve all queues for a project.

    Args:
        project_id: Project ID

    Returns:
        List of Queue objects ordered by creation date (newest first)
    """
    return list(
        db.session.execute(
            db.select(Queue)
            .filter_by(project_id=project_id, is_deleted=False)
            .order_by(Queue.created.desc())
        ).scalars()
    )


def delete_queue_by_id(queue_id: str, project_id: int, user_id: int) -> bool:
    """Soft-delete a queue.

    Args:
        queue_id: Queue ID to delete
        project_id: Project ID for validation
        user_id: ID of user performing deletion

    Returns:
        True if deleted successfully, False otherwise
    """
    queue = get_queue_by_id(queue_id, project_id)
    if queue:
        del_controled(queue, user_id)
        return True
    return False


# endregion


# region Entry Management
# ----------------------
def get_entry(idt, by="composite") -> Entry | None:
    """Retrieve an entry using various identifiers.

    Supports three lookup methods:
    1. By unique id (primary key): get_entry(5, by='id')
    3. By composite ID + dataset_id: get_entry((123, 456), by='composite')

    Args:
        entry_id: Identification value (type depends on lookup method)
        by: Lookup method - 'id' or 'composite'

    Returns:
        Entry object if found, None otherwise
    """
    if by == "composite":
        # Composite ID + dataset_id lookup
        if not isinstance(idt, tuple) or len(idt) != 2:
            raise ValueError("For composite lookup, provide (id, dataset_id) tuple")

        dataset_id, entry_id_num = idt
        return db.session.execute(
            db.select(Entry).filter_by(entry_id=entry_id_num, dataset_id=dataset_id)
        ).scalar_one_or_none()

    if by == "id":
        # Primary key lookup
        return get_by(Entry, "id", idt)

    raise ValueError(f"Invalid by method: {by} for get_entry.")


def get_entries(type=None) -> ScalarResult:
    """Retrieve entries with optional type filter.

    Args:
        type: Optional entry type filter

    Returns:
        Scalar result of entry IDs
    """
    if type is None:
        return db.session.execute(db.select(Entry.id)).scalars()
    return db.session.execute(db.select(Entry.id).filter_by(type=type)).scalars()


def check_entries_exist(entry_ids: list[str], dataset_id: int) -> tuple[list[str], list[str]]:
    """Bulk check which entry IDs exist in a dataset.

    Args:
        entry_ids: List of entry ID strings to check
        dataset_id: Dataset ID to check within

    Returns:
        Tuple of (existing_ids, missing_ids)
    """
    existing_entry_ids = (
        db.session.execute(
            db.select(Entry.entry_id).filter(
                Entry.dataset_id == dataset_id, Entry.entry_id.in_(entry_ids)
            )
        )
        .scalars()
        .all()
    )

    existing_set = set(existing_entry_ids)
    missing_ids = [eid for eid in entry_ids if eid not in existing_set]

    return list(existing_set), missing_ids


def random_entries(number: int, project_id: int | None = None) -> list[Entry]:
    """Retrieve random entries with optional project filtering.

    Args:
        number: Number of entries to retrieve
        project_id: Optional project ID to filter entries by

    Returns:
        List of Entry objects from specified project
    """
    base_query = db.select(Entry)

    if project_id is not None:
        base_query = (
            base_query.join(Dataset)
            .join(ProjectDataset)
            .filter(ProjectDataset.project_id == project_id)
            .filter(ProjectDataset.is_deleted == False)  # noqa
        )

    return db.session.execute(base_query.order_by(db.func.random()).limit(number)).scalars()


def register_entries(entries_ids: list[str], entries_type: str, dataset_id: int) -> None:
    """Bulk register new data entries.

    Args:
        entries_ids: List of entry identifiers
        entries_type: Classification type for entries
    """
    entries = [
        Entry(entry_id=str(eid), type=entries_type, dataset_id=dataset_id) for eid in entries_ids
    ]
    db.session.add_all(entries)
    db.session.commit()


# endregion


# region Label-Entry Association
# -----------------------------
def add_entry_label(
    label_id: int,
    entry_uid: int,
    user_id: int,
    value: str,
    created: datetime | None = None,
    metadata: dict | None = None,
) -> LabelEntry | None:
    """Apply label to data entry.

    Args:
        label_id: Target label ID
        entry_uid: Entry to label
        user_id: ID of labeling user
        value: Label value/text
        created: Optional timestamp override
        metadata: Optional provenance metadata (e.g. LLM model/prompt settings)

    Returns:
        Created LabelEntry object or None
    """
    entry = get_entry(entry_uid, by="id")
    label = get_label(label_id)
    if not entry or not label:
        raise ValueError("Invalid entry or label")

    # Remove existing labels
    for le in db.session.execute(
        db.select(LabelEntry).filter_by(label=label, entry=entry, is_deleted=False)
    ).scalars():
        del_controled(le, user_id)

    if value != "":
        label_entry = LabelEntry(
            value=value,
            created=created or datetime.now(),
            created_by=user_id,
            is_deleted=False,
            entry_id=entry.id,
            label_id=label.id,
            meta=metadata,
        )
        db.session.add(label_entry)
        db.session.commit()
        return label_entry


def get_labeled(label_id: int) -> Select:
    """Retrieve labeling history for a label.

    Args:
        label_id: Target label ID

    Returns:
        SQLAlchemy Select query (includes label_metadata for export post-processing)
    """
    return (
        db.select(
            LabelEntry.created,
            Entry.entry_id,
            Dataset.name.label("dataset_name"),
            Dataset.id.label("dataset_id"),
            Label.name.label("label"),
            LabelEntry.value,
            User.username.label("created_by"),
            LabelEntry.meta.label("label_metadata"),
        )
        .filter_by(is_deleted=False, label_id=label_id)
        .join(LabelEntry.entry)
        .join(LabelEntry.label)
        .join(LabelEntry.creator)
        .join(Entry.dataset)
    )


def add_model_prediction(
    entry_id: int,
    label_id: int,
    model_id: int,
    version_id: int,
    value: str | None,
    score: float | None = None,
    prediction_set: list | None = None,
) -> ModelPrediction:
    """Upsert an ML model prediction for an entry/label/version.

    Replaces any existing prediction for the same (entry, label, version) triple.
    """
    db.session.execute(
        db.delete(ModelPrediction).where(
            ModelPrediction.entry_id == entry_id,
            ModelPrediction.label_id == label_id,
            ModelPrediction.version_id == version_id,
        )
    )
    mp = ModelPrediction(
        entry_id=entry_id,
        label_id=label_id,
        model_id=model_id,
        version_id=version_id,
        value=value,
        score=score,
        prediction_set=prediction_set,
        created_at=datetime.now(),
    )
    db.session.add(mp)
    db.session.commit()
    return mp


def get_model_predictions(
    label_id: int, version_id: int | None = None
) -> list[ModelPrediction]:
    """Return model predictions for a label, optionally filtered to one version."""
    q = db.select(ModelPrediction).filter_by(label_id=label_id)
    if version_id is not None:
        q = q.filter_by(version_id=version_id)
    return list(db.session.execute(q).scalars())


def export_model_predictions_csv(model_id: int, version_id: int | None = None, trusted_only: bool = False) -> str:
    """Export model predictions as a CSV string.

    Columns: entry_id, label, model_version, predicted_value, score, prediction_set, created_at
    """
    import csv as _csv
    import io as _io

    from olim.ml.models import MLModelVersion

    q = (
        db.select(
            Entry.entry_id.label("entry_id"),
            Label.name.label("label"),
            MLModelVersion.version.label("model_version"),
            ModelPrediction.value.label("predicted_value"),
            ModelPrediction.score.label("score"),
            ModelPrediction.prediction_set.label("prediction_set"),
            ModelPrediction.created_at.label("created_at"),
        )
        .join(Entry, Entry.id == ModelPrediction.entry_id)
        .join(Label, Label.id == ModelPrediction.label_id)
        .join(MLModelVersion, MLModelVersion.id == ModelPrediction.version_id)
        .where(ModelPrediction.model_id == model_id)
        .order_by(MLModelVersion.version, Entry.entry_id)
    )
    if version_id is not None:
        q = q.where(ModelPrediction.version_id == version_id)

    rows = db.session.execute(q).mappings().all()
    if trusted_only:
        rows = [r for r in rows if r["prediction_set"] and len(r["prediction_set"]) == 1]

    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["entry_id", "label", "model_version", "predicted_value", "score", "prediction_set", "created_at"])
    for row in rows:
        writer.writerow([
            row["entry_id"],
            row["label"],
            row["model_version"],
            row["predicted_value"],
            row["score"],
            row["prediction_set"],
            row["created_at"],
        ])
    return buf.getvalue()


def bulk_replace_model_predictions(
    predictions: list[dict],
    model_id: int,
    version_id: int,
) -> None:
    """Delete all existing predictions for a model version then bulk-insert new ones.

    Each dict in predictions must have: entry_id, label_id, value, score, prediction_set.
    Uses bulk_insert_mappings for performance (no per-row commit).
    """
    from datetime import datetime as _dt

    db.session.execute(
        db.delete(ModelPrediction).where(
            ModelPrediction.model_id == model_id,
            ModelPrediction.version_id == version_id,
        )
    )
    now = _dt.now()
    rows = [
        {
            "entry_id": p["entry_id"],
            "label_id": p["label_id"],
            "model_id": model_id,
            "version_id": version_id,
            "value": p.get("value"),
            "score": p.get("score"),
            "prediction_set": p.get("prediction_set"),
            "created_at": now,
        }
        for p in predictions
    ]
    db.session.bulk_insert_mappings(ModelPrediction, rows)  # type: ignore[arg-type]
    db.session.commit()


def delete_model_predictions(model_id: int, version_id: int) -> None:
    """Delete all predictions for a specific model version."""
    db.session.execute(
        db.delete(ModelPrediction).where(
            ModelPrediction.model_id == model_id,
            ModelPrediction.version_id == version_id,
        )
    )
    db.session.commit()


def bulk_append_model_predictions(predictions: list[dict]) -> None:
    """Bulk-insert model predictions without deleting existing ones.

    Each dict must have: entry_id, label_id, model_id, version_id, value, score, prediction_set.
    """
    from datetime import datetime as _dt

    if not predictions:
        return
    now = _dt.now()
    rows = [
        {
            "entry_id": p["entry_id"],
            "label_id": p["label_id"],
            "model_id": p["model_id"],
            "version_id": p["version_id"],
            "value": p.get("value"),
            "score": p.get("score"),
            "prediction_set": p.get("prediction_set"),
            "created_at": now,
        }
        for p in predictions
    ]
    db.session.bulk_insert_mappings(ModelPrediction, rows)  # type: ignore[arg-type]
    db.session.commit()


# endregion


# region CeleryTask management


class TaskStatus(TypedDict):
    id: str
    name: str
    status: str
    error: str | None


def get_celery_tasks(n=10) -> list[TaskStatus]:
    """
    Update task statuses and categorize into pending/completed tasks.

    Returns:
        tuple: (list_of_pending_tasks, list_of_completed_tasks)
    """
    # Get all active/waiting tasks from database
    active_tasks = (
        CeleryTask.query.filter(CeleryTask.is_deleted == False)  # noqa
        .order_by(CeleryTask.created.desc(), CeleryTask.id.desc())
        .all()
    )

    tasks = []
    n_comp = 0

    for task in active_tasks:
        # Categorize based on updated status
        if task.status in {"SUCCESS", "FAILURE", "REVOKED"}:
            if (datetime.now() - task.date_completed) <= timedelta(hours=24):
                if n_comp < n:
                    n_comp += 1
                    tasks.append(
                        {
                            "id": task.id,
                            "name": (task.description if task.description else task.task_name),
                            "error": task.error,
                            "status": task.status,
                        }
                    )
        else:
            tasks.append(
                {
                    "id": task.id,
                    "name": task.description if task.description else task.task_name,
                    "status": task.status,
                }
            )
    return tasks


def get_celery_task(task_id: str | None) -> "CeleryTask | None":
    """Retrieve a single CeleryTask by its UUID. Returns None if not found."""
    if task_id is None:
        return None
    return db.session.get(CeleryTask, task_id)


def get_started_celery_tasks() -> list["CeleryTask"]:
    """Return all CeleryTask records currently in STARTED status."""
    return CeleryTask.query.filter(CeleryTask.status == "STARTED").all()


def persist_celery_task(task: "CeleryTask") -> None:
    """Add a new CeleryTask record to the session and commit."""
    db.session.add(task)
    db.session.commit()


# endregion


# region Learning Task Management
# -------------------------------
def new_learning_task(
    name: str,
    state: str,
    initial_setup: dict,
    user_id: int,
    project_id: int,
    data: dict | None = None,
    assigned_to: int | None = None,
) -> LearningTask:
    """Create a new learning task.

    Args:
        name: Task name
        state: Initial state of the task
        initial_setup: Initial configuration for the task
        user_id: ID of creating user
        project_id: ID of the project this task belongs to
        data: Optional initial task data (defaults to empty dict)
        assigned_to: Optional user ID to assign the task to

    Returns:
        New LearningTask object
    """
    task = LearningTask(
        name=name,
        state=state,
        project_id=project_id,
        initial_setup=initial_setup,
        data=data or {},
        created=datetime.now(),
        created_by=user_id,
        is_deleted=False,
        assigned_to=assigned_to,
    )
    db.session.add(task)
    db.session.commit()
    return task


def get_learning_task(task_id: int) -> LearningTask | None:
    """Retrieve a learning task by ID.

    Args:
        task_id: Task ID

    Returns:
        LearningTask object or None if not found
    """
    return get_by(LearningTask, "id", task_id, True)


def get_learning_tasks(
    project_id: int,
    state: str | None = None,
    assigned_to: int | None = None,
) -> list[LearningTask]:
    """Retrieve all active learning tasks for a project with optional filtering.

    Args:
        project_id: Project ID to filter by
        state: Optional state to filter by
        assigned_to: Optional user ID to filter by assignee

    Returns:
        List of LearningTask objects ordered by creation date (newest first)
    """
    query = db.select(LearningTask).filter_by(is_deleted=False, project_id=project_id)

    if state is not None:
        query = query.filter_by(state=state)

    if assigned_to is not None:
        query = query.filter_by(assigned_to=assigned_to)

    return list(
        db.session.execute(query.order_by(LearningTask.created.desc())).scalars()
    )


def assign_learning_task(task_id: int, assigned_to: int | None) -> LearningTask | None:
    """Assign (or unassign) a learning task to a user.

    Args:
        task_id: Task ID to update
        assigned_to: User ID to assign to, or None to unassign

    Returns:
        Updated LearningTask or None if not found
    """
    return update_learning_task(task_id, assigned_to=assigned_to)


def update_learning_task(task_id: int, **params) -> LearningTask | None:
    """Update a learning task.

    Args:
        task_id: Task ID to update
        **params: Fields to update (name, state, data)

    Returns:
        Updated LearningTask object or None if not found
    """
    task = get_learning_task(task_id)
    if not task:
        return None

    for key, value in params.items():
        if hasattr(task, key):
            setattr(task, key, value)

    db.session.commit()
    return task


def delete_learning_task(task_id: int, user_id: int) -> bool:
    """Soft-delete a learning task.

    Args:
        task_id: Task ID to delete
        user_id: ID of user performing deletion

    Returns:
        True if deleted successfully, False otherwise
    """
    task = get_learning_task(task_id)
    if task:
        del_controled(task, user_id)
        return True
    return False


# endregion


# region Global Settings Management
# --------------------------------
def get_setting(key: str) -> GlobalSetting | None:
    """Retrieve a global setting by key.

    Args:
        key: Setting key to retrieve

    Returns:
        GlobalSetting object if found, None otherwise
    """
    return get_by(GlobalSetting, "key", key, True)


def get_settings(category: str | None = None) -> list[GlobalSetting]:
    """Retrieve all global settings with optional category filtering.

    Args:
        category: Optional category to filter by

    Returns:
        List of GlobalSetting objects ordered by category, then key
    """
    query = db.select(GlobalSetting).filter_by(is_deleted=False)

    if category is not None:
        query = query.filter_by(category=category)

    return list(
        db.session.execute(query.order_by(GlobalSetting.category, GlobalSetting.key)).scalars()
    )


def set_setting(
    key: str,
    value: str,
    display_name: str,
    setting_type: str,
    default_value: str,
    description: str | None = None,
    category: str | None = None,
    user_id: int | None = None,
) -> GlobalSetting:
    """Create or update a global setting.

    Args:
        key: Setting key (unique identifier)
        value: Setting value (stored as string)
        display_name: Human-readable name for UI
        setting_type: Type of the setting ('str', 'int', 'float', 'bool', 'json')
        default_value: Default value (stored as string)
        description: Optional description
        category: Optional category for grouping
        user_id: ID of user creating/updating (defaults to session user)

    Returns:
        Created or updated GlobalSetting object
    """
    if user_id is None:
        user_id = session.get("user_id", 1)  # Fallback to user 1 if no session

    setting = get_setting(key)
    if setting:
        # Update existing setting
        setting.value = value
        setting.display_name = display_name
        setting.type = setting_type
        setting.default_value = default_value
        setting.description = description
        setting.category = category
        db.session.commit()
        return setting
    else:
        # Create new setting
        setting = GlobalSetting(
            key=key,
            display_name=display_name,
            value=value,
            default_value=default_value,
            type=setting_type,
            description=description,
            category=category,
            created=datetime.now(),
            created_by=user_id,
            is_deleted=False,
        )
        db.session.add(setting)
        db.session.commit()
        return setting


def delete_setting(key: str, user_id: int | None = None) -> GlobalSetting | None:
    """Soft-delete a global setting.

    Args:
        key: Setting key to delete
        user_id: ID of user performing deletion

    Returns:
        Deleted GlobalSetting object or None if not found
    """
    if user_id is None:
        user_id = session.get("user_id", 1)

    setting = get_setting(key)
    if setting:
        del_controled(setting, user_id)  # type: ignore
        return setting
    return None


def get_setting_value(key: str, default: str | None = None) -> str | None:
    """Get the raw string value of a setting.

    Args:
        key: Setting key
        default: Default value if setting not found

    Returns:
        Setting value as string or default
    """
    setting = get_setting(key)
    if setting:
        return setting.value
    return default


# endregion


# region ML Model CRUD
# --------------------


def _ml_slugify(text: str) -> str:
    """Convert text to a URL-friendly slug for ML model names."""
    text = text.lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def new_ml_model(
    *,
    name: str,
    project_id: int,
    created_by: int,
    algorithm: str = "TfidfXGBoostClassifier",
    model_type: str = "classification",
    model_config: dict | None = None,
    training_config: dict | None = None,
    policy_type: str | None = None,
    subsample_config: dict | list | None = None,
    label_id: int | None = None,
    description: str | None = None,
) -> "MLModel":
    """Create a new ML model with a unique slug.

    Returns:
        Created MLModel instance
    """
    from olim.ml.models import MLModel as _MLModel

    base_slug = _ml_slugify(name)
    slug = base_slug
    counter = 1
    while db.session.query(_MLModel).filter_by(slug=slug).first() is not None:
        slug = f"{base_slug}-{counter}"
        counter += 1

    model = _MLModel(
        slug=slug,
        name=name,
        description=description,
        project_id=project_id,
        label_id=label_id,
        model_type=model_type,
        algorithm=algorithm,
        model_config=model_config or {},
        training_config=training_config or {},
        policy_type=policy_type,
        subsample_config=subsample_config,
        status="draft",
        created=datetime.now(),
        created_by=created_by,
        is_deleted=False,
    )
    db.session.add(model)
    db.session.commit()
    return model


def get_ml_model(model_id: int) -> "MLModel | None":
    """Retrieve an ML model by ID (excludes soft-deleted)."""
    from olim.ml.models import MLModel as _MLModel

    return db.session.query(_MLModel).filter_by(id=model_id, is_deleted=False).first()


def get_ml_model_by_slug(slug: str) -> "MLModel | None":
    """Retrieve an ML model by slug (excludes soft-deleted)."""
    from olim.ml.models import MLModel as _MLModel

    return db.session.query(_MLModel).filter_by(slug=slug, is_deleted=False).first()


def get_ml_models(
    *,
    project_id: int | None = None,
    status: str | None = None,
    label_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> "list[MLModel]":
    """List ML models with optional filters, ordered by creation date descending."""
    from sqlalchemy import desc

    from olim.ml.models import MLModel as _MLModel

    query = db.session.query(_MLModel).filter_by(is_deleted=False)
    if project_id is not None:
        query = query.filter_by(project_id=project_id)
    if status is not None:
        query = query.filter_by(status=status)
    if label_id is not None:
        query = query.filter_by(label_id=label_id)
    return query.order_by(desc(_MLModel.created)).limit(limit).offset(offset).all()


def update_ml_model(model_id: int, **kwargs: Any) -> "MLModel":
    """Update allowed fields on an ML model and commit.

    Allowed fields: name, description, model_config, training_config,
                    policy_type, subsample_config, status

    Raises:
        ValueError: If model not found
    """
    from olim.ml.models import MLModel as _MLModel

    model = db.session.query(_MLModel).filter_by(id=model_id, is_deleted=False).first()
    if model is None:
        raise ValueError(f"Model {model_id} not found")

    allowed = {"name", "description", "model_config", "training_config", "policy_type", "subsample_config", "status"}
    for key, value in kwargs.items():
        if key in allowed:
            setattr(model, key, value)
    db.session.commit()
    return model


def delete_ml_model(model_id: int, deleted_by: int) -> None:
    """Soft-delete an ML model.

    Raises:
        ValueError: If model not found
    """
    from olim.ml.models import MLModel as _MLModel

    model = db.session.query(_MLModel).filter_by(id=model_id, is_deleted=False).first()
    if model is None:
        raise ValueError(f"Model {model_id} not found")
    model.is_deleted = True
    model.deleted = datetime.now()
    model.deleted_by = deleted_by
    db.session.commit()


# endregion


# region ML Version CRUD
# ----------------------


def new_ml_version(
    *,
    model_id: int,
    artifact_path: str,
    n_train_samples: int,
    n_val_samples: int,
    metrics: dict,
    created_by: int,
    trained_at: datetime | None = None,
    training_duration: float | None = None,
    class_distribution: dict | None = None,
    conformal_threshold: float | None = None,
    cache_entries: list | None = None,
    auto_activate: bool = True,
) -> "MLModelVersion":
    """Create a new ML model version, optionally auto-activating it."""
    from sqlalchemy import desc

    from olim.ml.models import MLModel as _MLModel, MLModelVersion as _MLModelVersion

    last_version = (
        db.session.query(_MLModelVersion)
        .filter_by(model_id=model_id)
        .order_by(desc(_MLModelVersion.version))
        .first()
    )
    version_number = 1 if last_version is None else last_version.version + 1

    version = _MLModelVersion(
        model_id=model_id,
        version=version_number,
        artifact_path=artifact_path,
        trained_at=trained_at or datetime.now(),
        training_duration=training_duration,
        n_train_samples=n_train_samples,
        n_val_samples=n_val_samples,
        class_distribution=class_distribution,
        metrics=metrics,
        conformal_threshold=conformal_threshold,
        cache_entries=cache_entries,
        is_active=False,
        created=datetime.now(),
        created_by=created_by,
        is_deleted=False,
    )
    db.session.add(version)
    db.session.flush()

    if auto_activate:
        activate_ml_version(version.id)

    model = db.session.query(_MLModel).filter_by(id=model_id).first()
    if model and version_number == 1:
        model.status = "active"

    db.session.commit()
    return version


def get_ml_version(version_id: int) -> "MLModelVersion | None":
    """Retrieve an ML model version by ID."""
    from olim.ml.models import MLModelVersion as _MLModelVersion

    return db.session.query(_MLModelVersion).filter_by(id=version_id).first()


def get_active_ml_version(model_id: int) -> "MLModelVersion | None":
    """Retrieve the currently active version for a model."""
    from olim.ml.models import MLModelVersion as _MLModelVersion

    return (
        db.session.query(_MLModelVersion)
        .filter_by(model_id=model_id, is_active=True, is_deleted=False)
        .first()
    )


def get_ml_versions(model_id: int, *, limit: int = 100, offset: int = 0) -> "list[MLModelVersion]":
    """List all versions for a model, ordered by version number descending."""
    from sqlalchemy import desc

    from olim.ml.models import MLModelVersion as _MLModelVersion

    return (
        db.session.query(_MLModelVersion)
        .filter_by(model_id=model_id, is_deleted=False)
        .order_by(desc(_MLModelVersion.version))
        .limit(limit)
        .offset(offset)
        .all()
    )


def activate_ml_version(version_id: int) -> "MLModelVersion":
    """Activate a version, deactivating all others for the same model.

    Raises:
        ValueError: If version not found
    """
    from sqlalchemy import and_

    from olim.ml.models import MLModelVersion as _MLModelVersion

    version = db.session.query(_MLModelVersion).filter_by(id=version_id).first()
    if version is None:
        raise ValueError(f"Version {version_id} not found")

    db.session.query(_MLModelVersion).filter(
        and_(
            _MLModelVersion.model_id == version.model_id,
            _MLModelVersion.id != version_id,
        )
    ).update({"is_active": False})
    version.is_active = True
    db.session.commit()
    return version


# endregion


# region Label helpers
# --------------------


def update_label(label_id: int, **kwargs: Any) -> "Label | None":
    """Update fields on a Label and commit.

    Returns the updated Label, or None if not found.
    """
    label = get_label(label_id)
    if label is None:
        return None
    for key, value in kwargs.items():
        setattr(label, key, value)
    db.session.commit()
    return label


def link_label_to_model(label_id: int, model_id: int) -> None:
    """Set label.ml_model_id and model.label_id, then commit."""
    from olim.ml.models import MLModel as _MLModel

    label = get_label(label_id)
    model = db.session.query(_MLModel).filter_by(id=model_id, is_deleted=False).first()
    if label is not None:
        label.ml_model_id = model_id
    if model is not None:
        model.label_id = label_id
    db.session.commit()


def unlink_label_from_model(label_id: int, model_id: int) -> None:
    """Clear label.ml_model_id and model.label_id, then commit."""
    from olim.ml.models import MLModel as _MLModel

    label = get_label(label_id)
    model = db.session.query(_MLModel).filter_by(id=model_id, is_deleted=False).first()
    if label is not None:
        label.ml_model_id = None
    if model is not None:
        model.label_id = None
    db.session.commit()


# endregion


# region CeleryTask helpers
# -------------------------


def get_celery_task(task_id: str | None) -> "CeleryTask | None":
    """Retrieve a CeleryTask by its ID."""
    if task_id is None:
        return None
    return db.session.get(CeleryTask, task_id)


def get_started_celery_tasks() -> list["CeleryTask"]:
    """Return all CeleryTask records currently in STARTED status."""
    return CeleryTask.query.filter_by(status="STARTED").all()


def get_celery_tasks_for_model(model_id: int | None = None, limit: int = 50) -> list["CeleryTask"]:
    """Return training CeleryTask records, optionally filtered to a specific ML model.

    When model_id is given, matches tasks whose kwargs or result JSON contains it.
    """
    query = db.session.query(CeleryTask).filter(CeleryTask.task_name == "learner.train_model")
    if model_id is not None:
        from sqlalchemy import String, cast, or_

        kwargs_filter = cast(CeleryTask.kwargs["model_id"], String) == str(model_id)
        result_filter = cast(CeleryTask.result["model_id"], String) == str(model_id)
        query = query.filter(or_(kwargs_filter, result_filter))
    return query.order_by(CeleryTask.created.desc()).limit(limit).all()


def persist_celery_task(task: "CeleryTask") -> None:
    """Add a new CeleryTask to the session and commit."""
    db.session.add(task)
    db.session.commit()


# endregion


# region Entry helpers
# --------------------


def get_entries_by_dataset(dataset_id: int) -> list["Entry"]:
    """Return all Entry records for a given dataset."""
    return db.session.query(Entry).filter_by(dataset_id=dataset_id).all()


def get_entries_by_ids(entry_ids: list[int]) -> list["Entry"]:
    """Return Entry records for a list of DB primary-key IDs."""
    return db.session.query(Entry).filter(Entry.id.in_(entry_ids)).all()


def get_dataset_entry_type(dataset_id: int) -> str | None:
    """Return the entry type string for the first entry in a dataset, or None."""
    return db.session.execute(
        db.select(Entry.type).filter_by(dataset_id=dataset_id).limit(1)
    ).scalar_one_or_none()


def get_project_entries_page(project_id: int, offset: int, limit: int) -> list["Entry"]:
    """Return a page of Entry records that belong to a project via its datasets."""
    return (
        db.session.query(Entry)
        .join(Dataset, Entry.dataset_id == Dataset.id)
        .join(ProjectDataset, Dataset.id == ProjectDataset.dataset_id)
        .filter(ProjectDataset.project_id == project_id)
        .filter(ProjectDataset.is_deleted.is_(False))
        .limit(limit)
        .offset(offset)
        .all()
    )


# endregion


# region Dataset cascade cleanup
# --------------------------------


def cleanup_dataset(dataset_id: int, user_id: int) -> dict:
    """Cascade-delete a failed/unwanted dataset upload.

    Soft-deletes the dataset, its project associations, and its label entry
    associations; hard-deletes the bare Entry rows (which have no soft-delete).

    Returns:
        dict with keys success, entries_deleted, associations_deleted (or error)
    """
    try:
        dataset = db.session.get(Dataset, dataset_id)
        if not dataset:
            return {"success": False, "error": "Dataset not found"}

        entries = (
            db.session.execute(db.select(Entry).filter_by(dataset_id=dataset_id))
            .scalars()
            .all()
        )
        entries_deleted = 0
        for entry in entries:
            label_entries = (
                db.session.execute(db.select(LabelEntry).filter_by(entry_id=entry.id, is_deleted=False))
                .scalars()
                .all()
            )
            for le in label_entries:
                del_controled(le, user_id)
            db.session.delete(entry)
            entries_deleted += 1

        project_datasets = (
            db.session.execute(db.select(ProjectDataset).filter_by(dataset_id=dataset_id, is_deleted=False))
            .scalars()
            .all()
        )
        associations_deleted = 0
        for pd_row in project_datasets:
            del_controled(pd_row, user_id)
            associations_deleted += 1

        del_controled(dataset, user_id)
        db.session.commit()

        return {"success": True, "entries_deleted": entries_deleted, "associations_deleted": associations_deleted}

    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return {"success": False, "error": str(e)}


# endregion


# region ML Audit Prediction
# --------------------------


def store_ml_audit_prediction(
    model_id: int,
    version_id: int,
    input_text: str,
    predicted_class: str | None,
    prediction_set: list | None,
    confidence: float | None,
    class_probabilities: dict | None,
    entry_id: int | None = None,
    external_request_id: str | None = None,
) -> "MLModelPrediction":
    """Store a prediction in the ML audit log (MLModelPrediction table).

    Returns:
        Created MLModelPrediction instance
    """
    from olim.ml.models import MLModelPrediction as _MLModelPrediction

    prediction = _MLModelPrediction(
        model_id=model_id,
        version_id=version_id,
        input_text=input_text,
        predicted_class=predicted_class,
        prediction_set=prediction_set,
        confidence=confidence,
        class_probabilities=class_probabilities,
        predicted_at=datetime.now(),
        external_request_id=external_request_id,
        entry_id=entry_id,
    )
    db.session.add(prediction)
    db.session.commit()
    return prediction


# endregion
