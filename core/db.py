import streamlit as st
import pandas as pd
import psycopg2


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

try:
    DB_HOST = st.secrets["DB_HOST"]
    DB_PORT = int(st.secrets["DB_PORT"])
    DB_NAME = st.secrets["DB_NAME"]
    DB_USER = st.secrets["DB_USER"]
    DB_PASSWORD = st.secrets["DB_PASSWORD"]

except Exception:
    st.error("Параметры подключения к базе данных не настроены.")
    st.stop()


@st.cache_resource
def get_connection():

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
        options="-c lock_timeout=5000 -c statement_timeout=15000",
        sslmode="require",
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3
    )


def run_query(query, params=None, fetch=False):
    """Execute one DB statement safely.

    SELECT statements are committed after fetch as well, preventing
    the cached Supabase/Supavisor connection from remaining idle in
    transaction after every read.
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()

        # Streamlit caches the psycopg2 connection as a resource. Supabase/Supavisor
        # can close an idle pooled connection; in that case the cached object must
        # be discarded before asking Streamlit for a replacement.
        if getattr(conn, "closed", 0):
            try:
                get_connection.clear()
            except Exception:
                pass
            conn = get_connection()

        try:
            cursor = conn.cursor()
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            # The cached connection became stale before any SQL was executed.
            try:
                conn.close()
            except Exception:
                pass
            try:
                get_connection.clear()
            except Exception:
                pass
            conn = get_connection()
            cursor = conn.cursor()

        cursor.execute(query, params)

        if fetch:

            rows = cursor.fetchall()

            columns = [
                description[0]
                for description in cursor.description
            ]

            result = pd.DataFrame(
                rows,
                columns=columns
            )

            # SELECT also opens a PostgreSQL transaction.
            conn.commit()

            return result

        conn.commit()

        return None

    except Exception:

        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        raise

    finally:

        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


def run_transaction(statements):
    """Execute a batch of SQL statements atomically."""
    conn = None
    cursor = None
    try:
        conn = get_connection()

        if getattr(conn, "closed", 0):
            try:
                get_connection.clear()
            except Exception:
                pass
            conn = get_connection()

        try:
            cursor = conn.cursor()
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            try:
                conn.close()
            except Exception:
                pass
            try:
                get_connection.clear()
            except Exception:
                pass
            conn = get_connection()
            cursor = conn.cursor()

        for query, params in statements:
            cursor.execute(query, params)
        conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
