"""Add queues table and migrate file-based queues

Revision ID: d2e8740f1dbf
Revises: e12788d3b67d
Create Date: 2025-10-29 13:37:55.992856

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm
from datetime import datetime
import json
import os
from pathlib import Path


# revision identifiers, used by Alembic.
revision = 'd2e8740f1dbf'
down_revision = 'e12788d3b67d'
branch_labels = None
depends_on = None


def generate_migration_name(queue_list, highlight, extra_data):
    """Generate a descriptive name for migrated queues."""
    queue_length = len(queue_list)

    # Check if it's a random queue
    if extra_data and extra_data.get('Randomly generated'):
        return f"Random Sample ({queue_length} entries)"

    # Check if it has search terms in extra_data
    if extra_data:
        include_terms = extra_data.get('Include', [])
        exclude_terms = extra_data.get('Exclude', [])

        if include_terms or exclude_terms:
            parts = []
            if include_terms:
                terms_str = ", ".join(include_terms[:3])
                if len(include_terms) > 3:
                    terms_str += "..."
                parts.append(terms_str)

            if exclude_terms:
                exclude_str = "excluding " + ", ".join(exclude_terms[:2])
                if len(exclude_terms) > 2:
                    exclude_str += "..."
                parts.append(exclude_str)

            if parts:
                return f"Search: {' - '.join(parts)}"

    # Check if it has highlights (likely a search)
    if highlight:
        highlight_str = ", ".join(highlight[:3])
        if len(highlight) > 3:
            highlight_str += "..."
        return f"Search: {highlight_str}"

    # Default name for manual/unknown queues
    return f"Migrated Queue ({queue_length} entries)"


def migrate_queue_files():
    """Migrate existing queue files from filesystem to database."""
    # Get queue path - try multiple possible locations
    possible_paths = [
        Path('/app/queues'),  # Production path
        Path(os.environ.get('WORK_PATH', './work')) / 'queues',  # WORK_PATH based
        Path('./queues'),  # Relative path
    ]

    queues_base_path = None
    for path in possible_paths:
        if path.exists():
            queues_base_path = path
            break

    if queues_base_path is None:
        print("No existing queue files found to migrate.")
        return

    # Setup database session
    bind = op.get_bind()
    session = orm.Session(bind=bind)

    migrated_count = 0
    error_count = 0

    print(f"Searching for queue files in: {queues_base_path}")

    # Iterate through project directories
    for project_dir in queues_base_path.iterdir():
        if not project_dir.is_dir():
            continue

        try:
            project_id = int(project_dir.name)
        except ValueError:
            print(f"Skipping non-numeric directory: {project_dir.name}")
            continue

        print(f"Processing queues for project {project_id}...")

        # Check if project exists
        project_exists = session.execute(
            sa.text("SELECT id FROM projects WHERE id = :project_id AND is_deleted = FALSE"),
            {"project_id": project_id}
        ).first()

        if not project_exists:
            print(f"  ⚠ Project {project_id} does not exist, skipping all queues for this project")
            continue

        # Get first user ID once per project
        creator_id = session.execute(
            sa.text("SELECT id FROM users WHERE is_deleted = FALSE ORDER BY id LIMIT 1")
        ).scalar()

        if not creator_id:
            creator_id = 1  # Fallback

        # Process each queue file in the project directory
        for queue_file in project_dir.glob('queue_*.json'):
            try:
                # Read queue file
                with open(queue_file, 'r') as f:
                    queue_data = json.load(f)

                # Extract queue information
                queue_id = queue_data.get('id')
                queue_list = queue_data.get('queue', [])
                highlight = queue_data.get('highlight')
                extra_data = queue_data.get('extra_data', {})

                if not queue_id or not queue_list:
                    print(f"  ⚠ Skipping invalid queue file: {queue_file.name}")
                    error_count += 1
                    continue

                # Check if queue already exists in database
                existing = session.execute(
                    sa.text("SELECT id FROM queues WHERE id = :queue_id"),
                    {"queue_id": queue_id}
                ).first()

                if existing:
                    print(f"  ⊘ Queue {queue_id} already exists, skipping...")
                    continue

                # Generate a name for the migrated queue
                queue_name = generate_migration_name(queue_list, highlight, extra_data)

                # Get file creation time for created timestamp
                file_stat = queue_file.stat()
                created_time = datetime.fromtimestamp(file_stat.st_ctime)

                # Insert queue into database
                session.execute(
                    sa.text("""
                        INSERT INTO queues
                        (id, name, project_id, queue_data, highlight, extra_data, length,
                         created, created_by, is_deleted)
                        VALUES
                        (:id, :name, :project_id, :queue_data, :highlight, :extra_data, :length,
                         :created, :created_by, :is_deleted)
                    """),
                    {
                        "id": queue_id,
                        "name": queue_name,
                        "project_id": project_id,
                        "queue_data": json.dumps(queue_list),
                        "highlight": json.dumps(highlight) if highlight else None,
                        "extra_data": json.dumps(extra_data) if extra_data else None,
                        "length": len(queue_list),
                        "created": created_time,
                        "created_by": creator_id,
                        "is_deleted": False,
                    }
                )

                # Commit after each successful queue insertion
                session.flush()

                migrated_count += 1
                print(f"  ✓ Migrated queue {queue_id}: {queue_name}")

            except Exception as e:
                error_count += 1
                print(f"  ✗ Error migrating {queue_file.name}: {e}")
                # Rollback just this queue, continue with others
                session.rollback()
                continue

    # Commit all migrations
    session.commit()
    session.close()

    print(f"\nMigration complete:")
    print(f"  - Successfully migrated: {migrated_count} queues")
    print(f"  - Errors: {error_count} queues")
    print(f"\nNote: Original queue files are preserved in {queues_base_path}")
    print(f"      You can safely delete them after verifying the migration.")


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('queues',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('queue_data', sa.JSON(), nullable=False),
    sa.Column('highlight', sa.JSON(), nullable=True),
    sa.Column('extra_data', sa.JSON(), nullable=True),
    sa.Column('length', sa.Integer(), nullable=False),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted', sa.DateTime(), nullable=True),
    sa.Column('deleted_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_created_by'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('queues', schema=None) as batch_op:
        batch_op.create_index('ix_queues_created', ['created'], unique=False)
        batch_op.create_index('ix_queues_project_id', ['project_id'], unique=False)

    # ### end Alembic commands ###

    # Migrate existing queue files to database
    migrate_queue_files()


def downgrade():
    """Downgrade by dropping the queues table.

    WARNING: This will delete all queue data from the database.
    Original queue files should still exist in the filesystem if not deleted.
    """
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('queues', schema=None) as batch_op:
        batch_op.drop_index('ix_queues_project_id')
        batch_op.drop_index('ix_queues_created')

    op.drop_table('queues')
    # ### end Alembic commands ###

    print("\nQueues table dropped. Original queue files in filesystem remain unchanged.")
