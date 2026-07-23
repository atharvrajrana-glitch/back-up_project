import os
import re
import psycopg2
import psycopg2.extras
from sqlalchemy.orm import Session

import model
from utils.backup import BACKUP_DIR, download_from_s3


def get_pg_connection(db_profile):
    """Direct connection to the live client database."""
    return psycopg2.connect(
        host=db_profile.db_host,
        port=db_profile.db_port,
        user=db_profile.db_user,
        password=db_profile.db_password,
        dbname=db_profile.db_name
    )


def get_live_tables(conn) -> list:
    """Returns a list of table names that currently exist in the live database."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """)
        return [row[0] for row in cur.fetchall()]


def get_primary_key_columns(conn, table_name) -> list:
    """Returns the primary key column(s) for a table, needed for ON CONFLICT."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
        """, (table_name,))
        return [row[0] for row in cur.fetchall()]


def parse_backup_file(sql_text: str) -> dict:
    """
    Parses a pg_dump file using the COPY ... FROM stdin format (tab-separated).
    Returns: { table_name: {"columns": [...], "rows": [(...), ...]} }
    """
    tables = {}

    copy_pattern = re.compile(
        r'COPY (?:public\.)?"?(\w+)"?\s*\(([^)]+)\)\s*FROM stdin;\n(.*?)\n\\\.',
        re.DOTALL
    )

    for match in copy_pattern.finditer(sql_text):
        table_name = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",")]
        data_block = match.group(3)

        rows = []
        if data_block.strip():
            for line in data_block.split("\n"):
                if not line:
                    continue
                values = line.split("\t")
                converted = [None if v == r"\N" else v for v in values]
                rows.append(tuple(converted))

        tables[table_name] = {"columns": columns, "rows": rows}

    return tables


def run_backup_reconcile(db_id: int, s3_filename: str, db: Session) -> dict:
    """
    Compares a backup file against the live client database using
    INSERT ... ON CONFLICT DO NOTHING.

    - Only INSERTs into tables that already exist in the live DB.
    - Never creates, alters, or drops tables (no schema permission assumed).
    - Never copies data into any staging/shadow table.
    - Rows that already exist (matched by primary key) are left untouched.
    - Rows missing from live (deleted) get added back from the backup.
    """
    db_profile = db.query(model.RegisteredDatabase).filter(model.RegisteredDatabase.id == db_id).first()
    if not db_profile:
        return {"status": "error", "message": "Database profile not found"}

    # 1. Download the backup file from S3
    local_filename = os.path.basename(s3_filename)
    local_path = os.path.join(BACKUP_DIR, local_filename)
    if not download_from_s3(s3_filename, local_path):
        return {"status": "error", "message": "Failed to download backup from s3"}

    conn = None
    try:
        # 2. Parse the backup file
        with open(local_path, "r", encoding="utf-8") as f:
            sql_text = f.read()

        backup_tables = parse_backup_file(sql_text)

        if not backup_tables:
            return {
                "status": "failed",
                "message": "No tables found in backup file — check the backup format"
            }

        # 3. Connect directly to the live client database
        conn = get_pg_connection(db_profile)
        conn.autocommit = False
        live_tables = get_live_tables(conn)

        rows_added = {}
        tables_skipped_missing_schema = []
        warnings = []

        for table_name, table_data in backup_tables.items():
            if not table_data["rows"]:
                continue  # nothing to restore for this table

            # Table doesn't exist in live DB — we don't have permission to create it
            if table_name not in live_tables:
                tables_skipped_missing_schema.append(table_name)
                continue

            # Need a primary key for ON CONFLICT to know what "already exists" means
            pk_cols = get_primary_key_columns(conn, table_name)
            if not pk_cols:
                warnings.append(f"Skipped '{table_name}': no primary key found, ON CONFLICT requires one")
                continue

            cols_sql = ", ".join(f'"{c}"' for c in table_data["columns"])
            pk_sql = ", ".join(f'"{c}"' for c in pk_cols)

            try:
                with conn.cursor() as cur:
                    query = f'''
                        INSERT INTO "{table_name}" ({cols_sql})
                        VALUES %s
                        ON CONFLICT ({pk_sql}) DO NOTHING
                    '''
                    psycopg2.extras.execute_values(
                        cur,
                        query,
                        table_data["rows"],
                        page_size=1000
                    )
                    rows_added[table_name] = cur.rowcount
            except Exception as table_err:
                conn.rollback()
                warnings.append(f"Failed to insert into '{table_name}': {str(table_err)}")
                continue

        conn.commit()

        return {
            "status": "success",
            "message": "Reconciliation complete — missing rows restored where possible",
            "rows_added": rows_added,
            "tables_skipped_missing_schema": tables_skipped_missing_schema,
            "warnings": warnings
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {
            "status": "failed",
            "message": "Reconciliation failed",
            "error": str(e)
        }

    finally:
        if conn:
            conn.close()
        if os.path.exists(local_path):
            os.remove(local_path)