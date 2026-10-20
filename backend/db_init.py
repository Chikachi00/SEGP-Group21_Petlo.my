"""Initialize additive API tables or print a MySQL extension migration."""
import argparse

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from .config import Settings
from .db import Base, database, initialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mysql-ddl', action='store_true')
    args = parser.parse_args()
    if args.mysql_ddl:
        print('-- Additive Petlo API extension. Import petlo.sql first; no legacy table is altered.\n')
        for table in Base.metadata.sorted_tables:
            if table.name.startswith('analysis_'):
                print(str(CreateTable(table, if_not_exists=True).compile(dialect=mysql.dialect())) + ';\n')
        return
    settings = Settings()
    settings.validate()
    engine, sessions = database(settings)
    try:
        initialize(engine, sessions, settings)
        print('API schema initialized. Existing tables were not dropped or altered.')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
