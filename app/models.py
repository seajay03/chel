import secrets
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


PROJECT_CATEGORIES = [
    "Custom Builds",
    "Lighting & Electrical",
    "Detailing & Aesthetics",
    "Performance & Mechanical",
    "Diagnostics & Inspection",
    "Fabrication / Design",
    "Parts Procurement",
    "Business Operations",
    "Customer Experience",
    "Internal Projects",
]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    projects = db.relationship("Project", backref="assigned_user", lazy=True)
    tasks = db.relationship("Task", backref="assigned_user", lazy=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default="Open")
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    public_code = db.Column(db.String(12), unique=True, nullable=False, default=lambda: secrets.token_hex(4))
    cover_image_path = db.Column(db.String(255))

    tasks = db.relationship("Task", backref="project", cascade="all, delete-orphan", lazy=True)
    photos = db.relationship(
        "ProjectPhoto", backref="project", cascade="all, delete-orphan", lazy=True
    )


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default="Todo")
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
