from . import db, app
from werkzeug.security import generate_password_hash
import random, string
from datetime import datetime
from typing import List


## DB tables
class CreationControl:
    created: db.Mapped[datetime] = db.mapped_column(nullable=False)
    created_by: db.Mapped[int] = db.mapped_column(db.ForeignKey("users.id"))
    is_deleted: db.Mapped[bool] = db.mapped_column(nullable=False)
    deleted: db.Mapped[datetime] = db.mapped_column(nullable=True)
    deleted_by: db.Mapped[int] = db.mapped_column(db.Integer, nullable=True)

    # Relations
    @db.declared_attr
    def creator(cls):
        return db.relationship("User", uselist=False)


class User(CreationControl, db.Model):
    __tablename__ = "users"

    # Columns
    id: db.Mapped[int] = db.mapped_column(primary_key=True)
    name: db.Mapped[str] = db.mapped_column(nullable=False)
    username: db.Mapped[str] = db.mapped_column(unique=True, nullable=False)
    password: db.Mapped[str] = db.mapped_column(nullable=False)
    role: db.Mapped[str] = db.mapped_column(nullable=False)


class LabelEntry(CreationControl, db.Model):
    __tablename__ = "label-patient"

    # Columns
    id: db.Mapped[int] = db.mapped_column(primary_key=True)
    entry_id: db.Mapped[int] = db.mapped_column(db.ForeignKey("entries.id"))
    label_id: db.Mapped[int] = db.mapped_column(db.ForeignKey("labels.id"))
    value: db.Mapped[str] = db.mapped_column(nullable=True)

    # Relations
    label: db.Mapped["Label"] = db.relationship(back_populates="entries")
    entry: db.Mapped["Entry"] = db.relationship(back_populates="labels")


class Entry(db.Model):
    __tablename__ = "entries"
    # Columns
    id: db.Mapped[int] = db.mapped_column(primary_key=True)
    entry_id: db.Mapped[str] = db.mapped_column(nullable=False, unique=True)
    type: db.Mapped[str] = db.mapped_column(nullable=False)

    # Relations
    labels: db.Mapped[List["LabelEntry"]] = db.relationship(back_populates="entry")


class Label(CreationControl, db.Model):
    __tablename__ = "labels"

    # Columns
    id: db.Mapped[int] = db.mapped_column(primary_key=True)
    name: db.Mapped[str] = db.mapped_column(db.String, nullable=False)

    # Relations
    entries: db.Mapped[List["LabelEntry"]] = db.relationship(back_populates="label")


## Manipulation functions
def del_controled(obj, user_id):
    if not obj.is_deleted:
        obj.is_deleted = True
        obj.deleted = datetime.now()
        obj.deleted_by = user_id
        db.session.commit()


def new_label(label, user_id):
    label = Label(
        name=label,
        created_by=user_id,
        created=datetime.now(),
        is_deleted=False,
    )
    db.session.add(label)
    db.session.commit()
    return label


def del_label(label_id, user_id):
    label = db.get_or_404(Label, label_id)
    for le in label.entries:
        del_controled(le, user_id)
    del_controled(label, user_id)
    return label


def get_labels():
    labels = db.session.execute(
        db.select(Label).filter_by(is_deleted=False).order_by(Label.name)
    ).scalars()
    return labels


def add_entry_label(label_id, entry_id, user_id, value):
    entry = get_entry(entry_id)
    label = get_label(label_id)
    for le in db.session.execute(
        db.select(LabelEntry).filter_by(label=label, entry=entry, is_deleted=False)
    ).scalars():
        del_controled(le, user_id)
    label_entry = LabelEntry(
        value=value,
        created=datetime.now(),
        created_by=user_id,
        is_deleted=False,
        entry_id=entry.id,
        label_id=label.id,
    )
    db.session.add(label_entry)
    db.session.commit()
    return label_entry


def get_entry(entry_id):
    return get_by(Entry, "entry_id", entry_id, False)


def get_label(idt: int, by: str = "id"):
    return get_by(Label, by, idt, True)


def get_user(idt: int, by: str = "id"):
    return get_by(User, by, idt, True)


def get_by(table: db.Model, col: str, idt: int, filter_deleted=False):
    """
    Retrieves a user from the database by either their ID or username.

    :param identification: An integer representing the user's ID or a string representing their username.
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
            return db.session.execute(
                db.select(table).filter_by(**filter_pars)
            ).scalar_one()
        except db.orm.exc.NoResultFound:
            return None


def insert_user(username: str, hashed_password: str, role: str, creator: int, **kwargs):
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


def update_user_password(identification: int, new_password: str, by: str = "id"):
    """
    Updates a user's password.
    """
    user = get_user(identification, by)
    user.password = generate_password_hash(new_password)
    db.session.commit()


def get_users():
    """
    Retrieves all users from the database.

    :return: A list of dictionaries, where each dict represents a row in the users table.
    """
    users = db.session.execute(
        db.select(User).filter_by(is_deleted=False).order_by(User.username)
    ).scalars()
    return users


def register_entries(entries_ids: List[str], entries_type: str):
    entries = [Entry(entry_id=str(eid), type=entries_type) for eid in entries_ids]
    db.session.add_all(entries)
    db.session.commit()


def init_db():
    """Initializes the database."""
    print("Initializing database...")
    db.create_all()
    if not get_user("admin", "username"):
        print("Creatting administrator user.")
        password = "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
        print("----------------------------------")
        print("Username: admin")
        print("Password:", password)
        print("----------------------------------")
        user = insert_user(
            name="Adminstrator",
            username="admin",
            hashed_password=generate_password_hash(password),
            role="admin",
            creator=1,
        )
        user.created_by = user.id
        db.session.commit()
    print("Database initialized.")
