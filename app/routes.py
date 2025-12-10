import os
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from . import db
from .auth import admin_required
from .models import PROJECT_CATEGORIES, Project, ProjectPhoto, Task, User

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    return redirect(url_for("main.projects_list"))


@main_bp.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config[
        "ALLOWED_EXTENSIONS"
    ]


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


@main_bp.route("/projects")
@login_required
def projects_list():
    category_filter = request.args.get("category")
    search = request.args.get("search")
    query = Project.query
    if category_filter:
        query = query.filter_by(category=category_filter)
    if search:
        query = query.filter(Project.name.ilike(f"%{search}%"))
    projects = query.order_by(Project.created_at.desc()).all()
    users = User.query.all()
    return render_template(
        "projects_list.html",
        projects=projects,
        users=users,
        categories=PROJECT_CATEGORIES,
        selected_category=category_filter,
        search=search,
    )


@main_bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def new_project():
    users = User.query.all()
    if request.method == "POST":
        name = request.form.get("name")
        category = request.form.get("category")
        status = request.form.get("status")
        assigned_to = request.form.get("assigned_to") or None
        description = request.form.get("description")
        start_date = parse_date(request.form.get("start_date"))
        due_date = parse_date(request.form.get("due_date"))

        if category not in PROJECT_CATEGORIES:
            flash("Invalid category", "danger")
            return redirect(url_for("main.new_project"))

        project = Project(
            name=name,
            category=category,
            status=status,
            assigned_to=int(assigned_to) if assigned_to else None,
            description=description,
            start_date=start_date,
            due_date=due_date,
        )
        db.session.add(project)
        db.session.commit()
        flash("Project created", "success")
        return redirect(url_for("main.project_detail", project_id=project.id))

    return render_template(
        "project_form.html", project=None, users=users, categories=PROJECT_CATEGORIES
    )


@main_bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)
    users = User.query.all()
    if request.method == "POST":
        project.name = request.form.get("name")
        project.category = request.form.get("category")
        project.status = request.form.get("status")
        project.assigned_to = int(request.form.get("assigned_to")) if request.form.get("assigned_to") else None
        project.description = request.form.get("description")
        project.start_date = parse_date(request.form.get("start_date"))
        project.due_date = parse_date(request.form.get("due_date"))
        db.session.commit()
        flash("Project updated", "success")
        return redirect(url_for("main.project_detail", project_id=project.id))

    return render_template(
        "project_form.html", project=project, users=users, categories=PROJECT_CATEGORIES
    )


@main_bp.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    tasks_by_status = {
        "Todo": [],
        "In Progress": [],
        "Done": [],
    }
    for task in project.tasks:
        tasks_by_status.setdefault(task.status, []).append(task)
    tracking_url = url_for("public.track_project", public_code=project.public_code, _external=True)
    return render_template(
        "project_detail.html",
        project=project,
        tasks_by_status=tasks_by_status,
        tracking_url=tracking_url,
    )


@main_bp.route("/projects/<int:project_id>/upload", methods=["POST"])
@login_required
def upload_photo(project_id):
    project = Project.query.get_or_404(project_id)
    files = request.files.getlist("photos")
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            project_folder = os.path.join(current_app.config["UPLOAD_FOLDER"], str(project.id))
            os.makedirs(project_folder, exist_ok=True)
            filepath = os.path.join(project_folder, filename)
            file.save(filepath)
            rel_path = os.path.relpath(filepath, current_app.config["UPLOAD_FOLDER"])
            photo = ProjectPhoto(project_id=project.id, file_path=rel_path)
            db.session.add(photo)
            if not project.cover_image_path:
                project.cover_image_path = rel_path
    db.session.commit()
    flash("Photos uploaded", "success")
    return redirect(url_for("main.project_detail", project_id=project.id))


@main_bp.route("/projects/<int:project_id>/tasks/new", methods=["GET", "POST"])
@login_required
def new_task(project_id):
    project = Project.query.get_or_404(project_id)
    users = User.query.all()
    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        status = request.form.get("status")
        assigned_to = request.form.get("assigned_to") or None
        due_date = parse_date(request.form.get("due_date"))
        task = Task(
            project_id=project.id,
            title=title,
            description=description,
            status=status,
            assigned_to=int(assigned_to) if assigned_to else None,
            due_date=due_date,
        )
        db.session.add(task)
        db.session.commit()
        flash("Task added", "success")
        return redirect(url_for("main.project_detail", project_id=project.id))
    return render_template("task_form.html", project=project, task=None, users=users)


@main_bp.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)
    project = task.project
    users = User.query.all()
    if request.method == "POST":
        task.title = request.form.get("title")
        task.description = request.form.get("description")
        task.status = request.form.get("status")
        assigned_to = request.form.get("assigned_to") or None
        task.assigned_to = int(assigned_to) if assigned_to else None
        task.due_date = parse_date(request.form.get("due_date"))
        db.session.commit()
        flash("Task updated", "success")
        return redirect(url_for("main.project_detail", project_id=project.id))
    return render_template("task_form.html", project=project, task=task, users=users)


@main_bp.route("/tasks/<int:task_id>/status/<status>", methods=["POST"])
@login_required
def update_task_status(task_id, status):
    task = Task.query.get_or_404(task_id)
    task.status = status
    db.session.commit()
    flash("Task status updated", "success")
    return redirect(url_for("main.project_detail", project_id=task.project_id))


@main_bp.route("/users")
@login_required
@admin_required
def users_list():
    users = User.query.all()
    return render_template("users_list.html", users=users)


@main_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_user():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        is_admin = bool(request.form.get("is_admin"))
        if User.query.filter_by(email=email).first():
            flash("Email already exists", "danger")
            return redirect(url_for("main.new_user"))
        user = User(name=name, email=email, is_admin=is_admin)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("User created", "success")
        return redirect(url_for("main.users_list"))
    return render_template("user_form.html")
