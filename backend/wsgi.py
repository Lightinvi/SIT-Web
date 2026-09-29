"""Expose the Flask application for Gunicorn and the Flask development CLI."""
from app import create_app

app = create_app()
