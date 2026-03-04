"""
Application factory for SESA.
"""
import os
import click
from flask import Flask, render_template
from flask.cli import with_appcontext

from config import config
from app.extensions import db, migrate, login_manager, csrf


def create_app(config_name: str = None) -> Flask:
    """Create and configure the Flask application."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Initialize extensions
    _init_extensions(app)

    # Register blueprints
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register CLI commands
    _register_cli(app)

    return app


def _init_extensions(app: Flask) -> None:
    """Initialize Flask extensions."""
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    from app.models.account import Accounts

    @login_manager.user_loader
    def load_user(user_id: str):
        return Accounts.query.get(int(user_id))


def _register_blueprints(app: Flask) -> None:
    """Register all application blueprints."""
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.test import test_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp, url_prefix='/')
    app.register_blueprint(test_bp, url_prefix='/test')
    app.register_blueprint(admin_bp, url_prefix='/admin')


def _register_error_handlers(app: Flask) -> None:
    """Register custom error pages."""
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403


def _register_cli(app: Flask) -> None:
    """Register CLI commands."""
    @app.cli.command('init-db')
    @with_appcontext
    def init_db():
        """Initialize the database."""
        db.create_all()
        click.echo('Database initialized.')

    @app.cli.command('import-students')
    @click.argument('school_id')
    @click.argument('excel_path')
    @with_appcontext
    def import_students(school_id, excel_path):
        """Import student accounts from an Excel file."""
        import pandas as pd
        from werkzeug.security import generate_password_hash
        from app.models.account import Accounts
        from datetime import datetime

        try:
            df = pd.read_excel(excel_path, engine='openpyxl')
            df.columns = [c.strip().lower() for c in df.columns]

            expected = {'first name', 'last name', 'email', 'username', 'password', 'level', 'gender', 'birthdate'}
            missing = expected - set(df.columns)
            if missing:
                click.echo(f'Missing columns: {missing}')
                return

            count = 0
            for _, row in df.iterrows():
                if Accounts.query.filter_by(email=row['email']).first():
                    continue
                acc = Accounts(
                    fname=row['first name'],
                    lname=row['last name'],
                    email=row['email'],
                    username=row['username'],
                    password=generate_password_hash(str(row['password'])),
                    level=str(row['level']).strip().lower(),
                    gender=row.get('gender', ''),
                    birthdate=pd.to_datetime(row['birthdate']).date() if not pd.isna(row['birthdate']) else None,
                    school_id=int(school_id)
                )
                db.session.add(acc)
                count += 1

            db.session.commit()
            click.echo(f'Imported {count} students for school {school_id}.')
        except Exception as e:
            click.echo(f'Error: {e}')
