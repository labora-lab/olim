import random
import string
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TypedDict

from flask import session
from sqlalchemy import ScalarResult, Select, func
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, declared_attr
from werkzeug.security import generate_password_hash

from . import db


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

    # Relations
    label: Mapped["Label"] = db.relationship(back_populates="entries")
    entry: Mapped["Entry"] = db.relationship(back_populates="labels")


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

    metrics: Mapped[list] = db.mapped_column(db.JSON, nullable=True)
    cache: Mapped[list] = db.mapped_column(db.JSON, nullable=True)
    training_counter: Mapped[int] = db.mapped_column(db.Integer, default=0)

    # Learner parameters for active learning configuration
    learner_parameters: Mapped[dict] = db.mapped_column(db.JSON, nullable=True)

    # Auto-labels stored as {COMPOSITE_ID: value} for automatic labeling during active learning
    auto_labels: Mapped[dict] = db.mapped_column(db.JSON, nullable=True)

    # Relationships
    entries: Mapped[list["LabelEntry"]] = db.relationship(
        back_populates="label", foreign_keys="[LabelEntry.label_id]"
    )
    project: Mapped["Project"] = db.relationship(back_populates="labels")


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
        return db.session.get(table, idt)
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
        db.select(User).filter_by(is_deleted=False).order_by(User.username)
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
def new_dataset(dataset_name, user_id, learner_key=None) -> Dataset:
    """Create new dataset.

    Args:
        dataset_name: Name for new dataset
        user_id: ID of creating user

    Returns:
        New Dataset object
    """
    dataset = Dataset(
        name=dataset_name,
        learner_key=learner_key,
        created_by=user_id,
        created=datetime.now(),
        is_deleted=False,
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
def new_label(label, user_id, project_id, al_id=None) -> Label:
    """Create new classification label.

    Args:
        label: Display name for label
        user_id: ID of creating user
        project_id: Associated project ID
        al_id: Active learning identifier (optional)

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

    return db.session.execute(query.order_by(Label.name)).scalars()


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
            db.select(Entry.entry_id).filter(Entry.dataset_id == dataset_id, Entry.entry_id.in_(entry_ids))
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
def add_entry_label(label_id, entry_uid, user_id, value, created=None) -> LabelEntry | None:
    """Apply label to data entry.

    Args:
        label_id: Target label ID
        entry_uid: Entry to label
        user_id: ID of labeling user
        value: Label value/text
        created: Optional timestamp override

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
        )
        db.session.add(label_entry)
        db.session.commit()
        return label_entry


def get_labeled(label_id) -> Select:
    """Retrieve labeling history for a label.

    Args:
        label_id: Target label ID

    Returns:
        SQLAlchemy Select query
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
        )
        .filter_by(is_deleted=False, label_id=label_id)
        .join(LabelEntry.entry)
        .join(LabelEntry.label)
        .join(LabelEntry.creator)
        .join(Entry.dataset)
    )


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


# endregion
