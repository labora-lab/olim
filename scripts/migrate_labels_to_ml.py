#!/usr/bin/env python3
"""
Migrate existing Labels from old AL system to new MLModel system

This script:
1. Finds labels with al_key but no ml_model_id
2. Creates MLModel for each label
3. Migrates artifacts from old path to new path (if they exist)
4. Creates MLModelVersion with existing metrics
5. Links label to model

Usage:
    python scripts/migrate_labels_to_ml.py --all
    python scripts/migrate_labels_to_ml.py --label-id 1
    python scripts/migrate_labels_to_ml.py --project-id 1
    python scripts/migrate_labels_to_ml.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from olim import app as flask_app, db
from olim.database import Label
from olim.ml.artifacts import ArtifactManager
from olim.ml.services import MLModelService
from olim.settings import WORK_PATH


def migrate_label(label_id: int, dry_run: bool = False) -> bool:
    """Migrate single label to MLModel system

    Args:
        label_id: Label ID to migrate
        dry_run: If True, don't make any changes

    Returns:
        True if migration successful, False otherwise
    """
    with flask_app.app_context():
        label = db.session.query(Label).filter_by(id=label_id).first()
        if not label:
            print(f"❌ Label {label_id} not found")
            return False

        print(f"\n📋 Label {label_id}: {label.name}")

        # Check if already migrated
        if label.ml_model_id:
            print(f"✅ Already migrated (MLModel {label.ml_model_id})")
            return True

        # Check if label has AL initialized
        if not label.al_key or label.al_key == "setup":
            print("⚠️  Active Learning not initialized (al_key empty or 'setup')")
            return False

        # Check for free text labels
        if label.al_key == "free_text_disabled":
            print("⚠️  Free text label - skipping ML migration")
            return False

        # Check for old artifacts
        old_path = WORK_PATH / f"project_{label.project_id}" / f"label_{label_id}"
        has_artifacts = old_path.exists()

        if has_artifacts:
            print(f"✅ Found artifacts at {old_path}")
        else:
            print(f"⚠️  No artifacts found at {old_path}")

        if dry_run:
            print("🔍 DRY RUN - would create MLModel and migrate")
            return True

        # Create MLModel
        service = MLModelService(WORK_PATH)
        model = service.create_model_for_label(
            label=label,
            user_id=label.created_by,
        )
        print(f"✅ Created MLModel {model.id}: {model.name}")

        # Migrate artifacts if they exist
        version_created = False
        if has_artifacts:
            try:
                artifact_manager = ArtifactManager(WORK_PATH / "ml_models")
                new_path = artifact_manager.migrate_from_label_path(
                    old_path=old_path,
                    model_id=model.id,
                    version=1,
                )
                print(f"✅ Migrated artifacts to {new_path}")

                # Parse metrics from label.metrics (old format: list of strings)
                metrics = {}
                if label.metrics:
                    for metric_str in label.metrics:
                        if ": " in metric_str:
                            key, val = metric_str.split(": ", 1)
                            try:
                                metrics[key] = float(val)
                            except ValueError:
                                metrics[key] = val

                # Create MLModelVersion for migrated artifacts
                version = service.registry.create_version(
                    model_id=model.id,
                    artifact_path=str(new_path),
                    n_train_samples=0,  # Unknown from old system
                    n_val_samples=0,
                    metrics=metrics,
                    created_by=label.created_by,
                    cache_entries=label.cache,
                    auto_activate=True,
                )
                print(f"✅ Created MLModelVersion {version.id} (v{version.version})")
                version_created = True

            except Exception as e:
                print(f"⚠️  Error migrating artifacts: {e}")
                print("   Model created but no version - will retrain on next use")

        # Link label to model
        label.ml_model_id = model.id
        db.session.commit()

        if version_created:
            print(f"✅ Migration complete for Label {label_id}")
        else:
            print("⚠️  Partial migration - model created without initial version")

        return True


def main() -> None:
    """Main migration function"""
    parser = argparse.ArgumentParser(
        description="Migrate labels from old AL system to new MLModel system"
    )
    parser.add_argument("--label-id", type=int, help="Migrate specific label ID")
    parser.add_argument("--project-id", type=int, help="Migrate all labels in project")
    parser.add_argument("--all", action="store_true", help="Migrate all labels")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no changes)")

    args = parser.parse_args()

    if not any([args.label_id, args.project_id, args.all]):
        parser.print_help()
        sys.exit(1)

    with flask_app.app_context():
        if args.label_id:
            # Migrate single label
            success = migrate_label(args.label_id, dry_run=args.dry_run)
            sys.exit(0 if success else 1)

        elif args.project_id:
            # Migrate all labels in project
            labels = db.session.query(Label).filter_by(project_id=args.project_id).all()
            print(f"\n🔍 Found {len(labels)} labels in project {args.project_id}")

            success_count = 0
            for label in labels:
                if migrate_label(label.id, dry_run=args.dry_run):
                    success_count += 1

            print(f"\n📊 Summary: {success_count}/{len(labels)} labels migrated")
            sys.exit(0 if success_count == len(labels) else 1)

        elif args.all:
            # Migrate all labels
            labels = db.session.query(Label).filter(Label.al_key.isnot(None)).all()
            print(f"\n🔍 Found {len(labels)} labels with active learning")

            success_count = 0
            for label in labels:
                if migrate_label(label.id, dry_run=args.dry_run):
                    success_count += 1

            print(f"\n📊 Summary: {success_count}/{len(labels)} labels migrated")
            sys.exit(0 if success_count == len(labels) else 1)


if __name__ == "__main__":
    main()
