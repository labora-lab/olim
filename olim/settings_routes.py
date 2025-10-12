"""Global settings management routes.

This module provides admin-only routes for managing global system settings.
"""

from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app
from .database import (
    delete_setting,
    get_setting,
    get_settings,
    set_setting,
)
from .utils.settings import validate_setting_value


@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings() -> ...:
    """Admin interface for managing global settings."""
    # Check admin role
    if session.get("role") != "admin":
        abort(403)

    if request.method == "POST":
        # Handle form submission
        action = request.form.get("action")

        if action == "create":
            _handle_create_setting()
        elif action == "update":
            _handle_update_setting()
        elif action == "delete":
            _handle_delete_setting()
        elif action == "reset":
            _handle_reset_setting()

        return redirect(url_for("admin_settings"))

    # Get all settings grouped by category
    settings = get_settings()
    settings_by_category = {}

    for setting in settings:
        category = setting.category or _("General")
        if category not in settings_by_category:
            settings_by_category[category] = []
        settings_by_category[category].append(setting)

    return render_template("admin-settings.html", settings_by_category=settings_by_category)


@app.route("/admin/settings/<key>", methods=["GET", "POST"])
def admin_setting_detail(key: str) -> ...:
    """Get or update a specific setting."""
    # Check admin role
    if session.get("role") != "admin":
        abort(403)

    setting = get_setting(key)
    if not setting:
        flash(_("Setting not found"), category="error")
        return redirect(url_for("admin_settings"))

    if request.method == "POST":
        return _handle_update_setting(key)

    return render_template("admin-setting-detail.html", setting=setting)


def _handle_create_setting() -> ...:
    """Handle creation of new setting."""
    try:
        key = request.form.get("key", "").strip()
        display_name = request.form.get("display_name", "").strip()
        value = request.form.get("value", "").strip()
        setting_type = request.form.get("type", "str")
        default_value = request.form.get("default_value", "").strip()
        description = request.form.get("description", "").strip() or None
        category = request.form.get("category", "").strip() or None

        # Validation
        if not key:
            flash(_("Setting key is required"), category="error")
            return

        if not display_name:
            flash(_("Display name is required"), category="error")
            return

        # Validate value based on type
        if not validate_setting_value(value, setting_type):
            flash(_("Invalid value for type {type}").format(type=setting_type), category="error")
            return

        # Check if key already exists
        if get_setting(key):
            flash(_("Setting with key '{key}' already exists").format(key=key), category="error")
            return

        # Create setting
        set_setting(
            key=key,
            value=value,
            display_name=display_name,
            setting_type=setting_type,
            default_value=default_value,
            description=description,
            category=category,
        )

        flash(_("Setting '{key}' created successfully").format(key=key), category="success")

    except Exception as e:
        flash(_("Error creating setting: {error}").format(error=str(e)), category="error")


def _handle_update_setting(key: str | None = None) -> ...:
    """Handle updating an existing setting."""
    try:
        # Get key from form data (for updates, use setting_key from hidden field)
        if key is None:
            key = request.form.get("setting_key", "").strip()
            if not key:
                key = request.form.get("key", "").strip()

        setting = get_setting(key)
        if not setting:
            flash(_("Setting not found"), category="error")
            return

        # Get form data
        display_name = request.form.get("display_name", "").strip()
        value = request.form.get("value", "").strip()
        setting_type = request.form.get("type", setting.type)
        default_value = request.form.get("default_value", "").strip()
        description = request.form.get("description", "").strip() or None
        category = request.form.get("category", "").strip() or None

        # Validation
        if not display_name:
            flash(_("Display name is required"), category="error")
            return

        # Validate value based on type
        if not validate_setting_value(value, setting_type):
            flash(_("Invalid value for type {type}").format(type=setting_type), category="error")
            return

        # Update setting
        set_setting(
            key=key,
            value=value,
            display_name=display_name,
            setting_type=setting_type,
            default_value=default_value,
            description=description,
            category=category,
        )

        flash(_("Setting '{key}' updated successfully").format(key=key), category="success")

    except Exception as e:
        flash(_("Error updating setting: {error}").format(error=str(e)), category="error")


def _handle_delete_setting() -> ...:
    """Handle deletion of a setting."""
    try:
        key = request.form.get("key", "").strip()

        if not key:
            flash(_("Setting key is required"), category="error")
            return

        setting = get_setting(key)
        if not setting:
            flash(_("Setting not found"), category="error")
            return

        delete_setting(key)
        flash(_("Setting '{key}' deleted successfully").format(key=key), category="success")

    except Exception as e:
        flash(_("Error deleting setting: {error}").format(error=str(e)), category="error")


def _handle_reset_setting() -> ...:
    """Handle resetting a setting to its default value."""
    try:
        key = request.form.get("key", "").strip()

        if not key:
            flash(_("Setting key is required"), category="error")
            return

        setting = get_setting(key)
        if not setting:
            flash(_("Setting not found"), category="error")
            return

        # Reset to default value
        set_setting(
            key=key,
            value=setting.default_value,
            display_name=setting.display_name,
            setting_type=setting.type,
            default_value=setting.default_value,
            description=setting.description,
            category=setting.category,
        )

        flash(_("Setting '{key}' reset to default value").format(key=key), category="success")

    except Exception as e:
        flash(_("Error resetting setting: {error}").format(error=str(e)), category="error")


@app.route("/api/settings/<key>", methods=["GET"])
def api_get_setting(key: str) -> ...:
    """API endpoint to get setting data for AJAX requests."""
    # Check admin role
    if session.get("role") != "admin":
        return {"error": _("Unauthorized")}, 403

    setting = get_setting(key)
    if not setting:
        return {"error": _("Setting not found")}, 404

    return {
        "key": setting.key,
        "display_name": setting.display_name,
        "value": setting.value,
        "default_value": setting.default_value,
        "type": setting.type,
        "description": setting.description,
        "category": setting.category,
    }
