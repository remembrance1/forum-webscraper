from flask import Blueprint
bp = Blueprint("crawler", __name__)
from . import routes  # noqa
