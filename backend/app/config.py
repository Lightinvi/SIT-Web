"""Provide base Flask settings read from the process environment."""
import os


class Config:
    """Base application configuration; the factory supplies runtime overrides."""
    SECRET_KEY = os.environ.get("SECRET_KEY")
