import getpass

from app import create_app, db
from app.models import User


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        print("Database tables created.")
        if not User.query.first():
            name = input("Admin name: ")
            email = input("Admin email: ")
            password = getpass.getpass("Admin password: ")
            admin = User(name=name, email=email, is_admin=True)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            print("Admin user created.")
        else:
            print("Users already exist; skipping admin creation.")


if __name__ == "__main__":
    main()
