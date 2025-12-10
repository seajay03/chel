from flask import Blueprint, render_template

from .models import Project

public_bp = Blueprint("public", __name__)


@public_bp.route("/track/<public_code>")
def track_project(public_code):
    project = Project.query.filter_by(public_code=public_code).first_or_404()
    tasks_by_status = {
        "Todo": [],
        "In Progress": [],
        "Done": [],
    }
    for task in project.tasks:
        tasks_by_status.setdefault(task.status, []).append(task)
    return render_template("track_public.html", project=project, tasks_by_status=tasks_by_status)
