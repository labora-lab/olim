"""Analytics routes for user labeling statistics."""

from collections import defaultdict

from flask import jsonify, render_template, request
from flask_babel import _
from sqlalchemy import func

from . import app, db
from .database import Label, LabelEntry, Project, User
from .project import update_session_project


@app.route("/<int:project_id>/analytics", methods=["GET"])
def analytics(project_id: int) -> ...:
    """Display analytics page with user labeling statistics chart."""
    # Check project_id and require data
    res = update_session_project(project_id, require_data=True)
    if res is not None:
        return res

    project = db.session.get(Project, project_id)
    if not project or project.is_deleted:
        return render_template("error.html", message=_("Project not found")), 404

    return render_template(
        "analytics.html",
        project_id=project_id,
        project_name=project.name,
    )


@app.route("/<int:project_id>/analytics/data", methods=["GET"])
def analytics_data(project_id: int) -> ...:
    """API endpoint returning user labeling statistics by day.

    Returns JSON with format:
    {
        "dates": ["2024-01-01", "2024-01-02", ...],
        "users": [
            {
                "user_id": 1,
                "username": "john",
                "name": "John Doe",
                "data": [5, 12, 8, ...]  // labels per day
            },
            ...
        ],
        "totals": [15, 25, 18, ...]  // total labels per day
    }
    """
    # Check project access
    res = update_session_project(project_id, require_data=True)
    if res is not None:
        return jsonify({"error": "Unauthorized"}), 403

    project = db.session.get(Project, project_id)
    if not project or project.is_deleted:
        return jsonify({"error": "Project not found"}), 404

    # Query for label entries in this project, grouped by user and day.
    # Mode controls whether we count labels ('labels') or unique entries ('entries').
    mode = request.args.get("mode", "labels").lower()
    if mode not in ("labels", "entries"):
        mode = "labels"

    # Choose aggregation: count labels or count distinct entry IDs
    if mode == "entries":
        count_expr = func.count(func.distinct(LabelEntry.entry_id))
    else:
        count_expr = func.count(LabelEntry.id)

    query = (
        db.session.query(
            func.date(LabelEntry.created).label("date"),
            LabelEntry.created_by.label("user_id"),
            count_expr.label("count"),
        )
        .join(Label, LabelEntry.label_id == Label.id)
        .filter(
            Label.project_id == project_id,
            LabelEntry.is_deleted == False,  # noqa: E712
            Label.is_deleted == False,  # noqa: E712
        )
        .group_by(func.date(LabelEntry.created), LabelEntry.created_by)
        .order_by(func.date(LabelEntry.created))
        .all()
    )

    if not query:
        # No data yet
        return jsonify(
            {
                "dates": [],
                "users": [],
                "totals": [],
            }
        )

    # Get all users who have labeled in this project
    user_ids = {row.user_id for row in query}
    users = db.session.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {user.id: user for user in users}

    # Build date range
    dates = sorted({row.date for row in query})
    date_strings = [d.strftime("%Y-%m-%d") for d in dates]

    # Build user data structure
    user_data = defaultdict(lambda: defaultdict(int))
    for row in query:
        user_data[row.user_id][row.date] = row.count

    # Format response
    users_response = []
    totals = [0] * len(dates)

    for user_id in sorted(user_ids):
        user = user_map.get(user_id)
        if not user:
            continue

        data = []
        for i, date in enumerate(dates):
            count = user_data[user_id].get(date, 0)
            data.append(count)
            totals[i] += count

        users_response.append(
            {
                "user_id": user_id,
                "username": user.username,
                "name": user.name,
                "data": data,
            }
        )

    return jsonify(
        {
            "dates": date_strings,
            "users": users_response,
            "totals": totals,
        }
    )
