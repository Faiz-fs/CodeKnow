import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alembic.config import Config
from alembic import command

config = Config("alembic.ini")
command.upgrade(config, "head")
print("Migrations completed successfully!")