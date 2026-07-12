import sys
sys.path.insert(0, '.')
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

# Try to connect and check versions
try:
    config = Config()
    config.set_main_option('sqlalchemy.url', 'postgresql+asyncpg://postgres:postgres@localhost:5432/codeknow_db')

    # Get the script directory
    script = ScriptDirectory.from_config(config)

    print('Available migrations:')
    for rev in script.walk_revisions():
        print(f'  {rev.revision}: {rev.path.stem}')

except Exception as e:
    print(f'Error getting migrations: {e}')
    import traceback
    traceback.print_exc()

print('Done')