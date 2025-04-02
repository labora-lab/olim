import random
import string
from datetime import datetime

from sqlalchemy import ScalarResult, Select
from sqlalchemy.orm import Mapped, declared_attr
from werkzeug.security import generate_password_hash

from . import db


## DB tables
class CreationControl:
    created: Mapped[datetime] = db.mapped_column(nullable=False)
    created_by: Mapped[int] = db.mapped_column(db.ForeignKey("users.id"))
    is_deleted: Mapped[bool] = db.mapped_column(nullable=False)
    deleted: Mapped[datetime] = db.mapped_column(nullable=True)
    deleted_by: Mapped[int] = db.mapped_column(db.Integer, nullable=True)

    # Relations
    # https://docs.sqlalchemy.org/en/20/orm/mapping_api.html#sqlalchemy.orm.declared_attr justifies
    # the use of `cls` instead of `self`
    @declared_attr
    def creator(cls) -> Mapped["User"]:  # noqa: N805
        return db.relationship("User", uselist=False)


class User(db.Model, CreationControl):
    __tablename__ = "users"

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    name: Mapped[str] = db.mapped_column(nullable=False)
    username: Mapped[str] = db.mapped_column(unique=True, nullable=False)
    password: Mapped[str] = db.mapped_column(nullable=False)
    role: Mapped[str] = db.mapped_column(nullable=False)
    language: Mapped[str] = db.mapped_column(nullable=True)


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
    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    entry_id: Mapped[str] = db.mapped_column(nullable=False, unique=True)
    type: Mapped[str] = db.mapped_column(nullable=False)

    # Relations
    labels: Mapped[list["LabelEntry"]] = db.relationship(back_populates="entry")


class Label(db.Model, CreationControl):
    __tablename__ = "labels"

    # Columns
    id: Mapped[int] = db.mapped_column(primary_key=True)
    name: Mapped[str] = db.mapped_column(db.String, nullable=False)
    al_key: Mapped[str] = db.mapped_column(nullable=True)
    priority: Mapped[float] = db.mapped_column(default=1.0, nullable=False)

    # Relations
    entries: Mapped[list["LabelEntry"]] = db.relationship(back_populates="label")


## Manipulation functions
def del_controled(obj, user_id) -> None:
    if not obj.is_deleted:
        obj.is_deleted = True
        obj.deleted = datetime.now()
        obj.deleted_by = user_id
        db.session.commit()


def new_label(label, user_id, al_id=None) -> Label:
    label = Label(
        name=label,
        created_by=user_id,
        created=datetime.now(),
        is_deleted=False,
        al_key=al_id,
    )
    db.session.add(label)
    db.session.commit()
    return label


def del_label(label_id, user_id) -> Label:
    label = db.get_or_404(Label, label_id)
    for le in label.entries:
        del_controled(le, user_id)
    del_controled(label, user_id)
    return label


def get_labels() -> list[Label]:
    labels = db.session.execute(
        db.select(Label).filter_by(is_deleted=False).order_by(Label.name)
    ).scalars()
    return labels


def get_labeled(label_id) -> Select:
    return (
        db.select(
            LabelEntry.created,
            Entry.entry_id,
            Label.name.label("label"),
            LabelEntry.value,
            User.username.label("created_by"),
        )
        .filter_by(is_deleted=False, label_id=label_id)
        .join(LabelEntry.entry)
        .join(LabelEntry.label)
        .join(LabelEntry.creator)
    )


def add_entry_label(label_id, entry_id, user_id, value, created=None) -> LabelEntry | None:
    entry = get_entry(entry_id)
    if entry is None:
        raise Exception("Entry not found")
    label = get_label(label_id)
    if label is None:
        raise Exception("Label not found")
    for le in db.session.execute(
        db.select(LabelEntry).filter_by(label=label, entry=entry, is_deleted=False)
    ).scalars():
        del_controled(le, user_id)
    if value != "":
        created = created or datetime.now()
        label_entry = LabelEntry(
            value=value,
            created=created,
            created_by=user_id,
            is_deleted=False,
            entry_id=entry.id,
            label_id=label.id,
        )
        db.session.add(label_entry)
        db.session.commit()
        return label_entry


def get_entry(entry_id, by=None) -> Entry | None:
    if by is None:
        return get_by(Entry, "entry_id", entry_id, False)
    else:
        return get_by(Entry, by, entry_id, False)


def random_entries(number: int) -> list[Entry]:
    return db.session.execute(db.select(Entry).order_by(db.func.random()).limit(number)).scalars()


def get_label(idt: int, by: str = "id") -> Label | None:
    return get_by(Label, by, idt, True)


def get_user(idt: int | str, by: str = "id") -> User | None:
    return get_by(User, by, idt, True)


def get_by(table: ..., col: str, idt: int | str, filter_deleted=False) -> ...:
    """
    Retrieves a user from the database by either their ID or username.

    :param identification: An integer representing the user's ID or a string representing their
        username.
    :param by: A string indicating whether to search by ID or username. Defaults to "id".
    :return: A tuple representing the user's information from the database or None if not found.
    :raises: Exception if an invalid 'by' parameter is provided.
    """
    if col == "id":
        return db.session.get(table, idt)
    else:
        filter_pars = {col: idt}
        if filter_deleted:
            filter_pars["is_deleted"] = False
        try:
            return db.session.execute(db.select(table).filter_by(**filter_pars)).scalar_one()
        except db.orm.exc.NoResultFound:
            return None


def insert_user(username: str, hashed_password: str, role: str, creator: int, **kwargs) -> User:
    """
    Inserts a user into the database.

    :param username: A string representing the user's username.
    :param hashed_password: A string representing the user's hashed password.
    :param role: A string representing the user's role. Can be "user" or "admin".
    :param kwargs: Additional parameters where "name" is the user's name.
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


def update_user_password(identification: int | str, new_password: str, by: str = "id") -> User:
    """
    Updates a user's password.
    """
    user = get_user(identification, by)
    if user is None:
        raise Exception("User not found")
    user.password = generate_password_hash(new_password)
    db.session.commit()
    return user


def update_user(identification: int | str, by: str = "id", **parameters) -> User:
    """Update user data

    Args:
        identification (int): User identification
        by (str): User column to identify user
        **parameters: Values to be updated
    """
    user = get_user(identification, by)
    if user is None:
        raise Exception("User not found")
    for key, value in parameters.items():
        setattr(user, key, value)
    db.session.commit()
    return user


def get_users() -> list[User]:
    """
    Retrieves all users from the database.

    :return: A list of dictionaries, where each dict represents a row in the users table.
    """
    users = db.session.execute(
        db.select(User).filter_by(is_deleted=False).order_by(User.username)
    ).scalars()
    return users


def get_entries(type=None) -> ScalarResult:
    """
    Retrieves entries from the database.

    :return: A list of dictionaries, where each dict represents a row in the users table.
    """
    if type is None:
        return db.session.execute(db.select(Entry.id)).scalars()
    else:
        return db.session.execute(db.select(Entry.id).filter_by(type=type)).scalars()


def register_entries(entries_ids: list[str], entries_type: str) -> None:
    entries = [Entry(entry_id=str(eid), type=entries_type) for eid in entries_ids]
    db.session.add_all(entries)
    db.session.commit()


def init_db(
    admin_user: str = "admin",
    admin_name: str = "Administrator",
    admin_passwd: str | None = None,
) -> ...:
    """Initializes the database."""
    print("Initializing database...")
    db.create_all()

    if not get_user(admin_user, "username"):
        print("Creatting administrator user.")
        if admin_passwd is None:
            password = "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
        else:
            password = admin_passwd
        print("----------------------------------")
        print("Username:", admin_user)
        if admin_passwd is not None:
            print("Password: [set via web interface]")
        else:
            print("Password:", password)
        print("----------------------------------")
        user = insert_user(
            name=admin_name,
            username=admin_user,
            hashed_password=generate_password_hash(password),
            role="admin",
            creator=1,
        )
        user.created_by = user.id
        db.session.commit()
    print("Database initialized.")
