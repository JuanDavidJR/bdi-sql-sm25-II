#!/usr/bin/env python3
import os
import sys
import argparse
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import logging

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('sql_pipeline')

def parse_arguments():
    parser = argparse.ArgumentParser(description='PostgreSQL Database Pipeline')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', default=5433, type=int)
    parser.add_argument('--user', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--db-name', default='fintech_cards')
    parser.add_argument('--schema-name', default='fintech')
    parser.add_argument('--sql-dir', default='.')
    parser.add_argument('--use-sql-for-db-creation', action='store_true')
    return parser.parse_args()

def connect_postgres(host, port, user, password, dbname=None, autocommit=False):
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname if dbname else "postgres",
            client_encoding='utf8'
        )
        conn.autocommit = autocommit
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        logger.info(f"Connected to PostgreSQL{' - ' + dbname if dbname else ''}")
        return conn
    except Exception as e:
        logger.error(f"Error connecting to PostgreSQL: {e}")
        sys.exit(1)

def database_exists(conn, db_name):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        return cur.fetchone() is not None

def create_database(conn, db_name):
    if database_exists(conn, db_name):
        logger.info(f"Database '{db_name}' already exists")
        return
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}" ).format(sql.Identifier(db_name)))
        logger.info(f"Database '{db_name}' created successfully")
    except Exception as e:
        logger.error(f"Error creating database: {e}")
        sys.exit(1)

def schema_exists(conn, schema_name):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema_name,))
        return cur.fetchone() is not None

def create_schema(conn, schema_name):
    if schema_exists(conn, schema_name):
        logger.info(f"Schema '{schema_name}' already exists")
        return
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}" ).format(sql.Identifier(schema_name)))
        logger.info(f"Schema '{schema_name}' created successfully")
    except Exception as e:
        logger.error(f"Error creating schema: {e}")
        sys.exit(1)

def execute_sql_file(conn, file_path):
    """Execute SQL commands from file with fallback encoding."""
    for encoding in ['utf-8', 'latin-1']:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                sql_commands = f.read()
            break
        except UnicodeDecodeError:
            logger.warning(f"Failed to read {file_path} with encoding {encoding}. Trying next encoding...")
    else:
        logger.error(f"Could not decode file {file_path} with known encodings.")
        sys.exit(1)

    statements = []
    buffer = ""
    for line in sql_commands.splitlines():
        line = line.strip()
        if not line or line.startswith('--'):
            continue
        buffer += " " + line
        if line.endswith(";"):
            statements.append(buffer.strip())
            buffer = ""

    try:
        with conn.cursor() as cur:
            for i, statement in enumerate(statements):
                logger.info(f"Executing SQL statement {i + 1} of {len(statements)}")
                cur.execute(statement)
        logger.info(f"Successfully executed SQL file: {file_path}")
    except Exception as e:
        logger.error(f"Error executing SQL file {file_path}: {e}")
        sys.exit(1)


def get_project_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while True:
        parent_dir = os.path.dirname(current_dir)
        if os.path.basename(current_dir) == 'scripts' or parent_dir == current_dir:
            break
        current_dir = parent_dir
    if os.path.basename(current_dir) == 'scripts':
        return os.path.dirname(current_dir)
    return os.path.dirname(os.path.abspath(__file__))

def find_sql_files(base_dir, filename):
    for root, _, files in os.walk(base_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None

def main():
    args = parse_arguments()
    logger.info(f"Connecting to PostgreSQL at {args.host}:{args.port} with user {args.user}")
    logger.info(f"Using database: {args.db_name}, schema: {args.schema_name}")
    logger.info(f"SQL directory: {args.sql_dir}")

    sql_dir = args.sql_dir
    if sql_dir == '.':
        project_root = get_project_root()
        logger.info(f"Project root determined as: {project_root}")
        potential_sql_dir = os.path.join(project_root, 'scripts', 'ddl')
        if os.path.exists(potential_sql_dir):
            sql_dir = potential_sql_dir
            logger.info(f"Found SQL directory at: {sql_dir}")

    logger.info(f"Using SQL directory: {sql_dir}")

    sql_files = [
        '01-create-database.sql',
        '02-create-tables.sql',
        'countries.sql'
    ]

    if args.use_sql_for_db_creation:
        conn = connect_postgres(args.host, args.port, args.user, args.password, autocommit=True)
        db_creation_file = os.path.join(sql_dir, '01-create-database.sql')
        if os.path.exists(db_creation_file):
            logger.info(f"Executing database creation script: {db_creation_file}")
            execute_sql_file(conn, db_creation_file)
        else:
            logger.warning(f"Database creation script not found: {db_creation_file}")
            create_database(conn, args.db_name)
        conn.close()
        logger.info("Database created!")
    else:
        conn = connect_postgres(args.host, args.port, args.user, args.password, args.db_name)
        create_schema(conn, args.schema_name)
        for i, sql_file in enumerate(sql_files):
            file_path = os.path.join(sql_dir, sql_file)
            if not os.path.exists(file_path):
                logger.warning(f"File not found: {file_path}")
                continue
            if i == 0 and "create-database" in sql_file:
                logger.info(f"Skipping {file_path} - Database already created via code")
                continue
            logger.info(f"Executing {file_path}")
            execute_sql_file(conn, file_path)
        conn.close()

    logger.info("SQL Pipeline completed successfully")

if __name__ == "__main__":
    main()
