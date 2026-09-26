import streamlit as st
import pandas as pd
import psycopg2
from html import escape


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Reklet — Управление производством",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

# All database credentials are stored in Streamlit Cloud Secrets.
#
# Требуется secrets:
#
# DB_HOST = "aws-0-us-west-2.pooler.supabase.com"
# DB_PORT = "5432"
# DB_NAME = "postgres"
# DB_USER = "postgres.lnkaohubtchmsiniepoc"
# DB_PASSWORD = "YOUR_DATABASE_PASSWORD"

try:
    DB_HOST = st.secrets["DB_HOST"]
    DB_PORT = int(st.secrets["DB_PORT"])
    DB_NAME = st.secrets["DB_NAME"]
    DB_USER = st.secrets["DB_USER"]
    DB_PASSWORD = st.secrets["DB_PASSWORD"]

except Exception as e:

    st.error("Параметры подключения к базе данных не настроены.")

    st.code(
        """
DB_HOST = "aws-0-us-west-2.pooler.supabase.com"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "postgres.lnkaohubtchmsiniepoc"
DB_PASSWORD = "YOUR_DATABASE_PASSWORD"
        """
    )

    st.caption(
        "Добавьте эти значения в Streamlit Cloud → Settings → Secrets."
    )

    st.stop()


# ============================================================
# DATABASE CONNECTION
# ============================================================

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

        try:
            cursor = conn.cursor()
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            # Cached connection became stale. No SQL has executed yet,
            # so reconnecting here cannot duplicate a write.
            try:
                conn.close()
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
        try:
            cursor = conn.cursor()
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            try:
                conn.close()
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



def ensure_stage_movement_tables():
    """Create stage history tables once per Streamlit session when needed."""
    if st.session_state.get("_stage_movement_tables_ready"):
        return
    statements = [
        ("""
        CREATE TABLE IF NOT EXISTS reklet.production_transactions (
            id serial4 PRIMARY KEY,
            object_item_id int4 NULL REFERENCES reklet.object_items(id) ON DELETE SET NULL,
            object_id int4 NULL REFERENCES reklet.objects(id) ON DELETE SET NULL,
            operation_type text NOT NULL,
            quantity int4 NOT NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.transport_transactions (
            id serial4 PRIMARY KEY,
            object_item_id int4 NULL REFERENCES reklet.object_items(id) ON DELETE SET NULL,
            object_id int4 NULL REFERENCES reklet.objects(id) ON DELETE SET NULL,
            operation_type text NOT NULL,
            quantity int4 NOT NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.installation_transactions (
            id serial4 PRIMARY KEY,
            object_item_id int4 NULL REFERENCES reklet.object_items(id) ON DELETE SET NULL,
            object_id int4 NULL REFERENCES reklet.objects(id) ON DELETE SET NULL,
            operation_type text NOT NULL,
            quantity int4 NOT NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
        )
        """, ())
    ]
    run_transaction(statements)
    st.session_state["_stage_movement_tables_ready"] = True


# ============================================================
# DATABASE MIGRATION
# ============================================================

def initialize_database():

    statements = [

        """
        CREATE TABLE IF NOT EXISTS reklet.material_suppliers (

            id serial4 PRIMARY KEY,

            material_id int4 NOT NULL,

            supplier_id int4 NOT NULL,

            supplier_code text NULL,

            purchase_price numeric(12,2)
                DEFAULT 0,

            is_preferred boolean
                DEFAULT false,

            conditions text NULL,

            created_at timestamptz
                DEFAULT timezone('utc'::text, now())
                NOT NULL,

            CONSTRAINT material_suppliers_material_fk

                FOREIGN KEY (material_id)

                REFERENCES reklet.materials(id)

                ON DELETE CASCADE,

            CONSTRAINT material_suppliers_supplier_fk

                FOREIGN KEY (supplier_id)

                REFERENCES reklet.suppliers(id)

                ON DELETE CASCADE,

            CONSTRAINT material_suppliers_unique

                UNIQUE(material_id, supplier_id)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS reklet.finished_goods (

            id serial4 PRIMARY KEY,

            object_item_id int4 NOT NULL,

            object_id int4 NULL,

            quantity int4 NOT NULL DEFAULT 0,

            status text NOT NULL DEFAULT 'ready',

            created_at timestamptz
                DEFAULT timezone('utc'::text, now())
                NOT NULL,

            CONSTRAINT finished_goods_object_item_fk

                FOREIGN KEY (object_item_id)

                REFERENCES reklet.object_items(id)

                ON DELETE CASCADE,

            CONSTRAINT finished_goods_object_fk

                FOREIGN KEY (object_id)

                REFERENCES reklet.objects(id)

                ON DELETE SET NULL,

            CONSTRAINT finished_goods_status_check

                CHECK (
                    status IN (
                        'ready',
                        'shipped',
                        'arrived'
                    )
                )
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS
        reklet.finished_goods_transactions (

            id serial4 PRIMARY KEY,

            finished_goods_id int4 NULL,

            object_item_id int4 NULL,

            object_id int4 NULL,

            operation_type text NOT NULL,

            quantity int4 NOT NULL,

            created_at timestamptz
                DEFAULT timezone('utc'::text, now())
                NOT NULL,

            CONSTRAINT finished_goods_operation_check

                CHECK (
                    operation_type IN (
                        'ready',
                        'ship',
                        'arrive'
                    )
                ),

            CONSTRAINT finished_goods_tx_fg_fk

                FOREIGN KEY (finished_goods_id)

                REFERENCES reklet.finished_goods(id)

                ON DELETE SET NULL,

            CONSTRAINT finished_goods_tx_item_fk

                FOREIGN KEY (object_item_id)

                REFERENCES reklet.object_items(id)

                ON DELETE SET NULL,

            CONSTRAINT finished_goods_tx_object_fk

                FOREIGN KEY (object_id)

                REFERENCES reklet.objects(id)

                ON DELETE SET NULL
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_material_suppliers_material

        ON reklet.material_suppliers(material_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_material_suppliers_supplier

        ON reklet.material_suppliers(supplier_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_finished_goods_object

        ON reklet.finished_goods(object_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_finished_goods_item

        ON reklet.finished_goods(object_item_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_material_transactions_material

        ON reklet.material_transactions(material_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_object_items_object

        ON reklet.object_items(object_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_object_items_template

        ON reklet.object_items(product_template_id)
        """
    ]

    for statement in statements:

        run_query(statement)


def ensure_material_planning_tables():
    """Ensure direct warehouse planning/cost snapshot tables exist.

    The reservation workflow has been removed from the application. Legacy
    reservation tables, if they still exist in PostgreSQL, are deliberately
    left untouched and are no longer read or written by Reklet.
    """
    try:
        check = run_query(
            """
            SELECT
                to_regclass('reklet.purchase_orders') AS purchase_orders,
                to_regclass('reklet.purchase_order_items') AS purchase_order_items,
                to_regclass('reklet.material_consumption') AS material_consumption,
                to_regclass('reklet.object_item_material_costs') AS object_item_material_costs
            """,
            fetch=True,
        )
        ready = not check.empty and all(pd.notna(check.iloc[0][c]) for c in check.columns)
        if ready:
            col_check = run_query(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='reklet'
                  AND table_name='material_consumption'
                  AND column_name='unit_cost_snapshot'
                """,
                fetch=True,
            )
            if not col_check.empty:
                st.session_state['_material_planning_tables_ready'] = True
                if not st.session_state.get('_material_cost_snapshot_backfill_attempted'):
                    try:
                        run_query(
                            """
                            INSERT INTO reklet.object_item_material_costs
                                (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
                            SELECT oi.id, ptm.material_id,
                                   COALESCE(ptm.quantity_per_unit,0),
                                   COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1),
                                   COALESCE(m.cost_per_unit,0)
                            FROM reklet.object_items oi
                            JOIN reklet.product_template_materials ptm
                              ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                            JOIN reklet.materials m ON m.id=ptm.material_id
                            ON CONFLICT(object_item_id,material_id) DO NOTHING
                            """
                        )
                    except Exception:
                        pass
                    st.session_state['_material_cost_snapshot_backfill_attempted'] = True
                return
    except Exception:
        pass

    schema_statements = [
        ("""
        CREATE TABLE IF NOT EXISTS reklet.purchase_orders (
            id serial4 PRIMARY KEY,
            supplier_id int4 NOT NULL REFERENCES reklet.suppliers(id) ON DELETE RESTRICT,
            order_date date NOT NULL DEFAULT CURRENT_DATE,
            status text NOT NULL DEFAULT 'ordered',
            notes text NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT purchase_orders_status_check CHECK (status IN ('ordered','partial','received','cancelled'))
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.purchase_order_items (
            id serial4 PRIMARY KEY,
            purchase_order_id int4 NOT NULL REFERENCES reklet.purchase_orders(id) ON DELETE CASCADE,
            object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
            material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
            quantity_ordered numeric NOT NULL,
            quantity_received numeric NOT NULL DEFAULT 0,
            unit_price numeric NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT purchase_order_items_ordered_positive_check CHECK (quantity_ordered > 0),
            CONSTRAINT purchase_order_items_received_nonnegative_check CHECK (quantity_received >= 0),
            CONSTRAINT purchase_order_items_received_limit_check CHECK (quantity_received <= quantity_ordered)
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.material_consumption (
            id serial4 PRIMARY KEY,
            object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE RESTRICT,
            object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
            material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
            quantity numeric NOT NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT material_consumption_positive_check CHECK (quantity > 0)
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.object_item_material_costs (
            id serial4 PRIMARY KEY,
            object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE CASCADE,
            material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
            quantity_per_unit numeric NOT NULL,
            waste_coefficient numeric NOT NULL,
            unit_cost numeric NOT NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT object_item_material_costs_unique UNIQUE (object_item_id, material_id),
            CONSTRAINT object_item_material_costs_quantity_check CHECK (quantity_per_unit >= 0),
            CONSTRAINT object_item_material_costs_waste_check CHECK (waste_coefficient >= 0),
            CONSTRAINT object_item_material_costs_cost_check CHECK (unit_cost >= 0)
        )
        """, ()),
        ("ALTER TABLE reklet.material_consumption ADD COLUMN IF NOT EXISTS unit_cost_snapshot numeric NULL", ()),
        ("CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON reklet.purchase_orders(supplier_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_purchase_order_items_order ON reklet.purchase_order_items(purchase_order_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_purchase_order_items_object_material ON reklet.purchase_order_items(object_id, material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_consumption_object ON reklet.material_consumption(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_consumption_item ON reklet.material_consumption(object_item_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_consumption_material ON reklet.material_consumption(material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_object_item_material_costs_item ON reklet.object_item_material_costs(object_item_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_object_item_material_costs_material ON reklet.object_item_material_costs(material_id)", ()),
    ]
    run_transaction(schema_statements)
    st.session_state['_material_planning_tables_ready'] = True
    if not st.session_state.get('_material_cost_snapshot_backfill_attempted'):
        try:
            run_query(
                """
                INSERT INTO reklet.object_item_material_costs
                    (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
                SELECT oi.id, ptm.material_id,
                       COALESCE(ptm.quantity_per_unit,0),
                       COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1),
                       COALESCE(m.cost_per_unit,0)
                FROM reklet.object_items oi
                JOIN reklet.product_template_materials ptm
                  ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                JOIN reklet.materials m ON m.id=ptm.material_id
                ON CONFLICT(object_item_id,material_id) DO NOTHING
                """
            )
        except Exception:
            pass
        st.session_state['_material_cost_snapshot_backfill_attempted'] = True

def ensure_task_three_tables():
    """Create persistent tables required by Tasks 1-3. Idempotent migration."""
    if st.session_state.get("_task_three_tables_ready"):
        return
    statements = [
        (
            """
            ALTER TABLE reklet.purchase_order_items
            ALTER COLUMN object_id DROP NOT NULL
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.material_production_requests (
                id serial4 PRIMARY KEY,
                object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
                object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE RESTRICT,
                material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
                quantity_requested numeric NOT NULL,
                quantity_supplied numeric NOT NULL DEFAULT 0,
                status text NOT NULL DEFAULT 'sent',
                created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                notes text NULL,
                CONSTRAINT material_production_requests_quantity_check CHECK (quantity_requested > 0),
                CONSTRAINT material_production_requests_supplied_check CHECK (quantity_supplied >= 0 AND quantity_supplied <= quantity_requested),
                CONSTRAINT material_production_requests_status_check CHECK (status IN ('sent','purchasing','ready','completed','cancelled'))
            )
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.material_waste_transactions (
                id serial4 PRIMARY KEY,
                material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
                object_id int4 NULL REFERENCES reklet.objects(id) ON DELETE SET NULL,
                source_type text NOT NULL,
                quantity numeric NOT NULL,
                unit_cost_snapshot numeric NOT NULL DEFAULT 0,
                reason text NULL,
                created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                CONSTRAINT material_waste_source_check CHECK (source_type IN ('stock','production')),
                CONSTRAINT material_waste_quantity_check CHECK (quantity > 0)
            )
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.work_time_calculations (
                id serial4 PRIMARY KEY,
                object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
                distance_km numeric NOT NULL DEFAULT 0,
                loading_minutes numeric NOT NULL DEFAULT 240,
                road_minutes numeric NOT NULL DEFAULT 240,
                unloading_minutes numeric NOT NULL DEFAULT 240,
                production_minutes numeric NOT NULL DEFAULT 0,
                installation_minutes numeric NOT NULL DEFAULT 0,
                transport_minutes numeric NOT NULL DEFAULT 720,
                total_minutes numeric NOT NULL DEFAULT 0,
                calculated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                CONSTRAINT work_time_distance_check CHECK (distance_km >= 0),
                CONSTRAINT work_time_minutes_check CHECK (production_minutes >= 0 AND installation_minutes >= 0 AND transport_minutes >= 0 AND total_minutes >= 0)
            )
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.work_time_calculation_items (
                id serial4 PRIMARY KEY,
                calculation_id int4 NOT NULL REFERENCES reklet.work_time_calculations(id) ON DELETE CASCADE,
                object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE RESTRICT,
                item_name text NOT NULL,
                quantity int4 NOT NULL,
                unit_cost numeric NOT NULL DEFAULT 0,
                base_production_minutes numeric NOT NULL DEFAULT 0,
                quantity_class text NOT NULL,
                time_multiplier numeric NOT NULL DEFAULT 1,
                production_minutes numeric NOT NULL DEFAULT 0,
                installation_minutes numeric NOT NULL DEFAULT 0,
                CONSTRAINT work_time_item_quantity_check CHECK (quantity > 0),
                CONSTRAINT work_time_item_minutes_check CHECK (unit_cost >= 0 AND base_production_minutes >= 0 AND time_multiplier > 0 AND production_minutes >= 0 AND installation_minutes >= 0)
            )
            """,
            (),
        ),
        ("CREATE INDEX IF NOT EXISTS idx_material_production_requests_object ON reklet.material_production_requests(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_production_requests_item ON reklet.material_production_requests(object_item_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_production_requests_material ON reklet.material_production_requests(material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_waste_material ON reklet.material_waste_transactions(material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_waste_object ON reklet.material_waste_transactions(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_work_time_calculations_object ON reklet.work_time_calculations(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_work_time_calculation_items_calc ON reklet.work_time_calculation_items(calculation_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_work_time_calculation_items_item ON reklet.work_time_calculation_items(object_item_id)", ()),
    ]
    run_transaction(statements)
    st.session_state["_task_three_tables_ready"] = True


def ensure_object_item_material_costs(object_id):
    """Create missing frozen material-cost snapshots for one object only."""
    ensure_material_planning_tables()
    run_query(
        """
        INSERT INTO reklet.object_item_material_costs
            (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
        SELECT
            oi.id,
            ptm.material_id,
            COALESCE(ptm.quantity_per_unit, 0),
            COALESCE(ptm.waste_coefficient, m.default_waste_coefficient, 1),
            COALESCE(m.cost_per_unit, 0)
        FROM reklet.object_items oi
        JOIN reklet.product_template_materials ptm
          ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
        JOIN reklet.materials m ON m.id = ptm.material_id
        WHERE oi.object_id=%s
        ON CONFLICT (object_item_id, material_id) DO NOTHING
        """,
        (object_id,),
    )


# ============================================================
# DATABASE STARTUP
# ============================================================

# The production database schema is already present.
# Do not execute CREATE TABLE/INDEX statements on every Streamlit rerun:
# PostgreSQL DDL may wait on a lock and make the app appear to load forever.
# initialize_database() remains available above for controlled migrations.


# ============================================================
# AUTHENTICATION
# ============================================================

if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None

if "demo_mode" not in st.session_state:
    st.session_state["demo_mode"] = False


if not st.session_state["authentication_status"]:

    st.title("Reklet — Управление производством")
    st.subheader("Войти")

    with st.form("login_form"):

        username_input = st.text_input("Логин")

        password_input = st.text_input(
            "Пароль",
            type="password"
        )

        submit_login = st.form_submit_button("Войти")

        if submit_login:

            # ==================================================
            # ADMIN LOGIN
            # ==================================================

            if (
                username_input == "admin"
                and password_input == "qwert12345"
            ):

                st.session_state["authentication_status"] = True
                st.session_state["username"] = "admin"
                st.session_state["name"] = "Administrator"

                # Admin works with real database changes
                st.session_state["demo_mode"] = False

                st.rerun()


            # ==================================================
            # DEMO LOGIN
            # ==================================================

            elif (
                username_input == "demo"
                and password_input == "demo"
            ):

                st.session_state["authentication_status"] = True
                st.session_state["username"] = "demo"
                st.session_state["name"] = "Demo User"

                # Demo flag.
                # Transaction logic will be added in Step 4.
                st.session_state["demo_mode"] = True

                st.rerun()


            # ==================================================
            # INVALID LOGIN
            # ==================================================

            else:

                st.session_state["authentication_status"] = False

                st.error(
                    "Неверный логин или пароль"
                )

    st.stop()


try:
    ensure_material_planning_tables()
    ensure_task_three_tables()
except Exception as e:
    st.error("Не удалось подготовить складскую модель данных.")
    st.code(str(e))
    st.stop()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_int(value, default=0):

    try:

        if pd.isna(value):

            return default

        return int(value)

    except Exception:

        return default


def safe_float(value, default=0.0):

    try:

        if pd.isna(value):

            return default

        return float(value)

    except Exception:

        return default


def data_editor_ru(df, **kwargs):
    return st.data_editor(df, **kwargs)


def money(value):

    try:

        return f"{float(value):,.2f}"

    except Exception:

        return "0.00"


def printable_html(title, df=None, body_html=None, subtitle=None):
    """Build a self-contained printable HTML document from a dataframe/body."""
    if df is not None:
        if df.empty:
            table_html = "<p>Нет данных для печати.</p>"
        else:
            clean = df.copy()
            for col in clean.columns:
                if pd.api.types.is_datetime64_any_dtype(clean[col]):
                    clean[col] = clean[col].dt.strftime("%d.%m.%Y %H:%M").fillna("")
            clean = clean.where(pd.notna(clean), "")
            table_html = clean.to_html(index=False, border=0, classes="data-table")
    else:
        table_html = body_html or ""

    subtitle_html = f"<p class='subtitle'>{escape(str(subtitle))}</p>" if subtitle else ""
    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(str(title))}</title>
<style>
    @page {{ margin: 14mm; }}
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 0; color: #111; font-size: 12px; }}
    h1 {{ font-size: 20px; margin: 0 0 8px; }}
    .subtitle {{ margin: 0 0 14px; color: #444; }}
    table.data-table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
    table.data-table th, table.data-table td {{ border: 1px solid #777; padding: 5px 7px; text-align: left; vertical-align: top; }}
    table.data-table th {{ background: #eee; font-weight: 700; }}
    .toolbar {{ margin: 0 0 16px; }}
    .print-btn {{ padding: 7px 14px; border: 1px solid #555; background: #f3f3f3; cursor: pointer; }}
    .sign {{ margin-top: 35px; display: flex; justify-content: space-between; gap: 40px; }}
    @media print {{ .toolbar {{ display: none; }} }}
</style>
</head>
<body>
<div class="toolbar"><button class="print-btn" onclick="window.print()">Печать</button></div>
<h1>{escape(str(title))}</h1>
{subtitle_html}
{table_html}
</body>
</html>
"""


def render_print_html(title, df, key, subtitle=None):
    """Render the compact page-level HTML print option."""
    st.download_button(
        "Печать HTML",
        data=printable_html(title, df=df, subtitle=subtitle),
        file_name="".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(title))[:120] + ".html",
        mime="text/html",
        key=key,
        use_container_width=False,
    )


# ============================================================
# DATA FUNCTIONS
# ============================================================

def get_clients():

    return run_query(
        """
        SELECT
            id,
            name,
            phone,
            address,
            email,
            website,
            notes,
            contact_info
        FROM reklet.clients
        ORDER BY name
        """,
        fetch=True
    )


def get_objects():

    return run_query(
        """
        SELECT
            o.id,
            o.object_name,
            o.client_id,
            c.name AS client_name,
            o.address,
            o.transport_distance_km,
            o.created_at,
            o.phone,
            o.contact_person,
            o.notes,
            o.contract_date,
            o.production_start_date,
            o.production_end_date,
            o.installation_date,
            o.installation_end_date
        FROM reklet.objects o

        LEFT JOIN reklet.clients c
            ON c.id = o.client_id

        ORDER BY o.id DESC
        """,
        fetch=True
    )



def get_stage_objects(stage):
    """Объекты только с актуальными изделиями для конкретного этапа."""
    conditions = {
        "production": """
            COALESCE(oi.qty_new, 0) > 0
            OR COALESCE(oi.qty_production, 0) > 0
        """,
        "finished_goods": """
            COALESCE(oi.qty_ready, 0) > 0
        """,
        "transport": """
            COALESCE(oi.qty_shipped, 0) > COALESCE(oi.qty_arrived, 0)
        """,
        "installation": """
            COALESCE(oi.qty_arrived, 0) > 0
        """
    }
    if stage not in conditions:
        raise ValueError(f"Unknown work stage: {stage}")
    return run_query(
        f"""
        SELECT DISTINCT o.id, o.object_name, o.client_id,
               c.name AS client_name, o.address
        FROM reklet.objects o
        LEFT JOIN reklet.clients c ON c.id = o.client_id
        JOIN reklet.object_items oi ON oi.object_id = o.id
        WHERE {conditions[stage]}
        ORDER BY o.id DESC
        """,
        fetch=True
    )

def get_materials():

    # Keep this query limited to the core columns used by the product/material picker.
    materials = run_query(
        """
        SELECT
            m.id,
            m.name,
            m.unit_id,
            u.name AS unit_name,
            m.cost_per_unit,
            m.stock_quantity
        FROM reklet.materials m
        LEFT JOIN reklet.units u
            ON u.id = m.unit_id
        ORDER BY m.name
        """,
        fetch=True
    )

    if "default_waste_coefficient" not in materials.columns:
        materials["default_waste_coefficient"] = 1.20

    return materials


def get_materials_with_categories():
    try:
        return run_query(
            """
            SELECT
                m.id,
                m.name,
                m.unit_id,
                u.name AS unit_name,
                m.cost_per_unit,
                m.stock_quantity,
                m.default_waste_coefficient,
                m.category_id,
                mc.name AS category_name
            FROM reklet.materials m
            LEFT JOIN reklet.material_categories mc
                ON mc.id = m.category_id
            LEFT JOIN reklet.units u
                ON u.id = m.unit_id
            ORDER BY m.name
            """,
            fetch=True
        )
    except Exception:
        materials = get_materials().copy()
        materials["category_id"] = None
        materials["category_name"] = None
        return materials


def get_material_categories():
    try:
        return run_query(
            """
            SELECT id, name
            FROM reklet.material_categories
            ORDER BY name
            """,
            fetch=True
        )
    except Exception:
        return pd.DataFrame(columns=["id", "name"])


def get_suppliers():

    return run_query(
        """
        SELECT *
        FROM reklet.suppliers
        ORDER BY name
        """,
        fetch=True
    )


def get_templates():

    return run_query(
        """
        SELECT
            id,
            name,
            type,
            client_name,
            category

        FROM reklet.product_templates

        ORDER BY name
        """,
        fetch=True
    )


def ensure_product_category_table():
    """Create and seed the product category dictionary once per Streamlit session."""
    if st.session_state.get("_product_categories_ready"):
        return
    statements = [
        """
        CREATE TABLE IF NOT EXISTS reklet.product_categories (
            id serial4 PRIMARY KEY,
            name text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
        )
        """,
        """
        INSERT INTO reklet.product_categories (name)
        SELECT DISTINCT trim(category)
        FROM reklet.product_templates
        WHERE category IS NOT NULL
          AND trim(category) <> ''
        ON CONFLICT (name) DO NOTHING
        """
    ]
    try:
        run_transaction([(statements[0], ()), (statements[1], ())])
        st.session_state["_product_categories_ready"] = True
    except Exception:
        # The app can still work with the legacy text category field.
        st.session_state["_product_categories_ready"] = False
        raise


def get_product_categories():
    ensure_product_category_table()
    return run_query(
        "SELECT id, name FROM reklet.product_categories ORDER BY name",
        fetch=True
    )


def get_product_category_names():
    cats = get_product_categories()
    return cats["name"].astype(str).tolist() if not cats.empty else []

def get_object_items(object_id):

    return run_query(
        """
        SELECT
            oi.id,
            oi.object_id,
            oi.product_template_id,
            oi.template_id,
            oi.item_name,
            oi.quantity,
            oi.quantity_needed,
            oi.qty_new,
            oi.qty_production,
            oi.qty_ready,
            oi.qty_shipped,
            oi.qty_arrived,
            oi.qty_installing,
            oi.qty_installed,
            oi.production_status,
            oi.production_progress_pct,
            oi.installation_status,
            oi.installation_progress_pct

        FROM reklet.object_items oi

        WHERE oi.object_id = %s

        ORDER BY oi.id
        """,
        (object_id,),
        fetch=True
    )


def get_object_material_planning(object_id):
    """Return object material plan using direct stock/purchase/issue, no reservation."""
    ensure_material_planning_tables()
    ensure_task_three_tables()
    ensure_object_item_material_costs(object_id)
    df=run_query(
        """
        WITH demand AS (
            SELECT ptm.material_id,
                   SUM(COALESCE(oi.quantity_needed,0)*COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)) AS base_required_quantity,
                   SUM(COALESCE(oi.quantity_needed,0)*COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)*COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)) AS required_quantity
            FROM reklet.object_items oi
            JOIN reklet.product_template_materials ptm ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
            JOIN reklet.materials m ON m.id=ptm.material_id
            LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=oi.id AND oimc.material_id=ptm.material_id
            WHERE oi.object_id=%s
            GROUP BY ptm.material_id
        ),
        issued AS (
            SELECT material_id,SUM(quantity) AS issued_quantity
            FROM reklet.material_transactions
            WHERE object_id=%s AND operation_type='production_transfer' AND transaction_type='OUT'
            GROUP BY material_id
        ),
        consumed AS (
            SELECT material_id,SUM(quantity) AS consumed_quantity
            FROM reklet.material_consumption
            WHERE object_id=%s
            GROUP BY material_id
        ),
        production_waste AS (
            SELECT material_id,SUM(quantity) AS production_waste_quantity
            FROM reklet.material_waste_transactions
            WHERE object_id=%s AND source_type='production'
            GROUP BY material_id
        ),
        open_orders AS (
            SELECT poi.material_id,SUM(GREATEST(poi.quantity_ordered-poi.quantity_received,0)) AS ordered_outstanding
            FROM reklet.purchase_order_items poi
            JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
            WHERE poi.object_id=%s AND po.status<>'cancelled' AND poi.quantity_received<poi.quantity_ordered
            GROUP BY poi.material_id
        )
        SELECT d.material_id,m.name AS material_name,u.name AS unit_name,
               COALESCE(m.stock_quantity,0) AS stock_quantity,
               COALESCE(d.base_required_quantity,0) AS base_required_quantity,
               GREATEST(COALESCE(d.required_quantity,0)-COALESCE(d.base_required_quantity,0),0) AS waste_quantity,
               COALESCE(d.required_quantity,0) AS required_quantity,
               COALESCE(i.issued_quantity,0) AS issued_quantity,
               COALESCE(c.consumed_quantity,0) AS consumed_quantity,
               GREATEST(COALESCE(i.issued_quantity,0)-COALESCE(c.consumed_quantity,0)-COALESCE(pw.production_waste_quantity,0),0) AS work_in_process_quantity,
               COALESCE(oo.ordered_outstanding,0) AS ordered_outstanding,
               COALESCE(pw.production_waste_quantity,0) AS production_waste_quantity
        FROM demand d
        JOIN reklet.materials m ON m.id=d.material_id
        LEFT JOIN reklet.units u ON u.id=m.unit_id
        LEFT JOIN issued i ON i.material_id=d.material_id
        LEFT JOIN consumed c ON c.material_id=d.material_id
        LEFT JOIN production_waste pw ON pw.material_id=d.material_id
        LEFT JOIN open_orders oo ON oo.material_id=d.material_id
        ORDER BY m.name
        """,
        (object_id,object_id,object_id,object_id,object_id),fetch=True
    )
    if df.empty:
        return df
    for col in ['stock_quantity','base_required_quantity','waste_quantity','required_quantity','issued_quantity','consumed_quantity','work_in_process_quantity','ordered_outstanding','production_waste_quantity']:
        df[col]=pd.to_numeric(df[col],errors='coerce').fillna(0.0)
    df['remaining_need']=(df['required_quantity']-df['issued_quantity']).clip(lower=0)
    df['available_quantity']=df['stock_quantity'].clip(lower=0)
    df['need_to_buy']=(df['remaining_need']-df['stock_quantity']-df['ordered_outstanding']).clip(lower=0)
    return df

def calculate_production_time(unit_cost, quantity):
    """Task 3: base = cost/2; 1-5 x2, 6-20 x1, 21+ x2/3."""
    cost=max(float(unit_cost or 0),0.0)
    qty=max(int(quantity or 0),0)
    base=cost/2.0
    if 1 <= qty <= 5:
        quantity_class="Кастомное"
        multiplier=2.0
    elif 6 <= qty <= 20:
        quantity_class="Стандартное"
        multiplier=1.0
    elif qty >= 21:
        quantity_class="Потоковое"
        multiplier=2.0/3.0
    else:
        quantity_class="Нет количества"
        multiplier=0.0
    production=base*multiplier
    installation=production/2.0
    return base, quantity_class, multiplier, production, installation


def calculate_transport_time(distance_km):
    """Task 3: 4h loading + road + 4h unloading; road min 4h, +3 min/km after 120 km."""
    distance=max(float(distance_km or 0),0.0)
    road=240.0 + max(distance-120.0,0.0)*3.0
    total=240.0 + road + 240.0
    return 240.0, road, 240.0, total


def get_default_supplier_id():
    """Return the technical fallback supplier, creating it only when needed."""
    name='ООО «Поставщик»'
    found=run_query("SELECT id FROM reklet.suppliers WHERE name=%s ORDER BY id LIMIT 1",(name,),fetch=True)
    if not found.empty:
        return safe_int(found.iloc[0]['id'])
    created=run_query(
        """INSERT INTO reklet.suppliers(name,type,conditions) VALUES (%s,'material_supplier','Условный поставщик по умолчанию') RETURNING id""",
        (name,),fetch=True
    )
    return safe_int(created.iloc[0]['id'])


def get_supplier_choices_for_material(material_id, include_all=True):
    suppliers=get_suppliers()
    labels={}
    if suppliers.empty:
        return [], labels, None
    for _,r in suppliers.iterrows():
        labels[int(r['id'])]=f"{int(r['id'])} — {r['name']}"
    links=run_query(
        """SELECT supplier_id,is_preferred,purchase_price FROM reklet.material_suppliers WHERE material_id=%s ORDER BY is_preferred DESC,id""",
        (material_id,),fetch=True
    )
    preferred=None
    if not links.empty:
        preferred=safe_int(links.iloc[0]['supplier_id'])
    else:
        legacy=run_query("SELECT supplier_id FROM reklet.materials WHERE id=%s",(material_id,),fetch=True)
        if not legacy.empty and pd.notna(legacy.iloc[0]['supplier_id']):
            preferred=safe_int(legacy.iloc[0]['supplier_id'])
    if preferred is None:
        try:
            preferred=get_default_supplier_id()
            labels.setdefault(preferred, f"{preferred} — ООО «Поставщик»")
        except Exception:
            pass
    choice_ids=sorted(labels)
    if preferred in choice_ids:
        choice_ids=[preferred]+[x for x in choice_ids if x!=preferred]
    return [labels[i] for i in choice_ids], labels, preferred


def get_purchase_scope_needs(client_id=None, object_id=None):
    """Aggregate open material demand with direct stock coverage and no reservations."""
    objs=run_query("SELECT id,client_id,object_name FROM reklet.objects ORDER BY id",fetch=True)
    if objs.empty:
        return pd.DataFrame()
    if client_id is not None:
        objs=objs[objs['client_id'].eq(client_id)].copy()
    if object_id is not None:
        objs=objs[objs['id'].eq(object_id)].copy()
    if objs.empty:
        return pd.DataFrame()
    ids=[safe_int(x) for x in objs['id'].tolist()]
    for oid in ids:
        ensure_object_item_material_costs(oid)
    placeholders=','.join(['%s']*len(ids))
    q=f"""
    WITH target_objects AS (SELECT id FROM reklet.objects WHERE id IN ({placeholders})),
    demand AS (
        SELECT oi.object_id,ptm.material_id,
               SUM(COALESCE(oi.quantity_needed,0)*COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)*COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)) AS required_quantity
        FROM reklet.object_items oi
        JOIN target_objects tobj ON tobj.id=oi.object_id
        JOIN reklet.product_template_materials ptm ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
        JOIN reklet.materials m ON m.id=ptm.material_id
        LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=oi.id AND oimc.material_id=ptm.material_id
        WHERE COALESCE(oi.qty_installed,0)<COALESCE(oi.quantity_needed,0)
        GROUP BY oi.object_id,ptm.material_id
    ),
    issued AS (
        SELECT mt.object_id,mt.material_id,SUM(mt.quantity) issued_quantity
        FROM reklet.material_transactions mt
        JOIN target_objects tobj ON tobj.id=mt.object_id
        WHERE mt.operation_type='production_transfer' AND mt.transaction_type='OUT'
        GROUP BY mt.object_id,mt.material_id
    ),
    outstanding AS (
        SELECT poi.object_id,poi.material_id,SUM(GREATEST(poi.quantity_ordered-poi.quantity_received,0)) ordered_outstanding
        FROM reklet.purchase_order_items poi
        JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
        WHERE poi.object_id IN ({placeholders}) AND po.status<>'cancelled'
        GROUP BY poi.object_id,poi.material_id
    ),
    central_outstanding AS (
        SELECT poi.material_id,SUM(GREATEST(poi.quantity_ordered-poi.quantity_received,0)) ordered_outstanding
        FROM reklet.purchase_order_items poi
        JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
        WHERE poi.object_id IS NULL AND po.status<>'cancelled'
        GROUP BY poi.material_id
    ),
    scope AS (
        SELECT d.material_id,
               SUM(GREATEST(d.required_quantity-COALESCE(i.issued_quantity,0),0)) remaining_need,
               SUM(COALESCE(o.ordered_outstanding,0)) selected_ordered
        FROM demand d
        LEFT JOIN issued i USING(object_id,material_id)
        LEFT JOIN outstanding o USING(object_id,material_id)
        GROUP BY d.material_id
    )
    SELECT s.material_id,m.name AS material_name,u.name AS unit_name,
           s.remaining_need,s.selected_ordered,COALESCE(m.stock_quantity,0) AS stock_quantity,
           GREATEST(s.remaining_need-s.selected_ordered-COALESCE(m.stock_quantity,0)-CASE WHEN %s THEN COALESCE(co.ordered_outstanding,0) ELSE 0 END,0) AS need_to_buy,
           COALESCE(m.cost_per_unit,0) AS default_price
    FROM scope s
    JOIN reklet.materials m ON m.id=s.material_id
    LEFT JOIN reklet.units u ON u.id=m.unit_id
    LEFT JOIN central_outstanding co ON co.material_id=s.material_id
    WHERE s.remaining_need>0
    ORDER BY m.name
    """
    df=run_query(q,tuple(ids+ids+[object_id is None]),fetch=True)
    if not df.empty:
        for c in ['remaining_need','selected_ordered','stock_quantity','need_to_buy','default_price']:
            df[c]=pd.to_numeric(df[c],errors='coerce').fillna(0.0)
    return df

def get_open_production_requests():
    ensure_task_three_tables()
    return run_query(
        """
        SELECT r.id,r.object_id,o.object_name,c.name AS client_name,r.object_item_id,oi.item_name,
               r.material_id,m.name AS material_name,u.name AS unit_name,
               r.quantity_requested,r.quantity_supplied,
               GREATEST(r.quantity_requested-r.quantity_supplied,0) AS remaining_quantity,
               r.status,r.created_at,r.updated_at
        FROM reklet.material_production_requests r
        JOIN reklet.objects o ON o.id=r.object_id
        LEFT JOIN reklet.clients c ON c.id=o.client_id
        JOIN reklet.object_items oi ON oi.id=r.object_item_id
        JOIN reklet.materials m ON m.id=r.material_id
        LEFT JOIN reklet.units u ON u.id=m.unit_id
        WHERE r.status IN ('sent','purchasing','ready')
          AND r.quantity_supplied<r.quantity_requested
        ORDER BY r.created_at,r.id
        """,fetch=True
    )


def get_production_wip_for_material(material_id):
    ensure_task_three_tables()
    q=run_query(
        """
        SELECT
            o.id AS object_id,
            COALESCE(c.name,'') AS client_name,
            o.object_name,
            GREATEST(
                COALESCE((SELECT SUM(mt.quantity) FROM reklet.material_transactions mt WHERE mt.object_id=o.id AND mt.material_id=%s AND mt.operation_type='production_transfer' AND mt.transaction_type='OUT'),0)
                - COALESCE((SELECT SUM(mc.quantity) FROM reklet.material_consumption mc WHERE mc.object_id=o.id AND mc.material_id=%s),0)
                - COALESCE((SELECT SUM(mw.quantity) FROM reklet.material_waste_transactions mw WHERE mw.object_id=o.id AND mw.material_id=%s AND mw.source_type='production'),0),
                0
            ) AS wip_quantity
        FROM reklet.objects o
        LEFT JOIN reklet.clients c ON c.id=o.client_id
        WHERE EXISTS (
            SELECT 1 FROM reklet.material_transactions mt2 WHERE mt2.object_id=o.id AND mt2.material_id=%s AND mt2.operation_type='production_transfer' AND mt2.transaction_type='OUT'
        )
        ORDER BY o.id
        """,
        (material_id,material_id,material_id,material_id),fetch=True
    )
    if not q.empty:
        q['wip_quantity']=pd.to_numeric(q['wip_quantity'],errors='coerce').fillna(0.0)
    return q[q['wip_quantity']>1e-9].copy() if not q.empty else q


def get_material_stock_and_wip():
    ensure_task_three_tables()
    df=run_query(
        """
        SELECT m.id,m.name,u.name AS unit_name,COALESCE(m.stock_quantity,0) AS stock_quantity,
               GREATEST(
                   COALESCE((SELECT SUM(mt.quantity) FROM reklet.material_transactions mt WHERE mt.material_id=m.id AND mt.operation_type='production_transfer' AND mt.transaction_type='OUT'),0)
                   - COALESCE((SELECT SUM(mc.quantity) FROM reklet.material_consumption mc WHERE mc.material_id=m.id),0)
                   - COALESCE((SELECT SUM(mw.quantity) FROM reklet.material_waste_transactions mw WHERE mw.material_id=m.id AND mw.source_type='production'),0),0
               ) AS production_wip
        FROM reklet.materials m
        LEFT JOIN reklet.units u ON u.id=m.unit_id
        ORDER BY m.name
        """,fetch=True
    )
    if not df.empty:
        for c in ['stock_quantity','production_wip']:
            df[c]=pd.to_numeric(df[c],errors='coerce').fillna(0.0)
    return df


def get_object_cost_per_unit_map(object_id):
    ensure_object_item_material_costs(object_id)
    df=run_query(
        """
        SELECT oi.id AS object_item_id,oi.item_name,COALESCE(oi.quantity_needed,0) AS quantity_needed,
               COALESCE(SUM(COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)*COALESCE(oimc.unit_cost,m.cost_per_unit,0)*COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)),0) AS unit_cost
        FROM reklet.object_items oi
        LEFT JOIN reklet.product_template_materials ptm ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
        LEFT JOIN reklet.materials m ON m.id=ptm.material_id
        LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=oi.id AND oimc.material_id=ptm.material_id
        WHERE oi.object_id=%s
        GROUP BY oi.id,oi.item_name,oi.quantity_needed
        ORDER BY oi.id
        """,(object_id,),fetch=True
    )
    if not df.empty:
        df['quantity_needed']=pd.to_numeric(df['quantity_needed'],errors='coerce').fillna(0).astype(int)
        df['unit_cost']=pd.to_numeric(df['unit_cost'],errors='coerce').fillna(0.0)
    return df


# ============================================================
# SIMPLE RECTANGULAR NAVIGATION
# ============================================================
# Navigation uses real Streamlit buttons, not radio widgets.
# Therefore there are no radio circles/dots and no radio selection
# animation.  All navigation controls are plain rectangular buttons.
st.markdown("""
<style>
.stButton > button {
    border-radius: 0 !important;
    box-shadow: none !important;
    transition: none !important;
    animation: none !important;
    transform: none !important;
    min-height: 38px !important;
    padding: 0.35rem 0.75rem !important;
    font-weight: 400 !important;
}
.stButton > button:hover,
.stButton > button:focus,
.stButton > button:active {
    border-radius: 0 !important;
    box-shadow: none !important;
    transition: none !important;
    animation: none !important;
    transform: none !important;
}

/* ===== Управление объектами: визуальное разделение этапов ===== */
.stage-guide {
    margin: 0.35rem 0 0.85rem 0;
    border: 1px solid rgba(120,140,165,.35);
    border-radius: 4px;
    overflow: hidden;
    background: rgba(20,25,35,.18);
}
.stage-title {
    padding: .55rem .8rem;
    font-size: .86rem;
    font-weight: 700;
    letter-spacing: .03em;
}
.stage-groups {
    display: grid;
    grid-template-columns: 16% 12% 14% 21% 14% 23%;
    min-height: 58px;
}
.stage-spacer, .stage-group {
    padding: .55rem .45rem;
    border-right: 1px solid rgba(100,120,145,.35);
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
}
.stage-spacer {
    text-align: left;
    font-weight: 600;
    background: rgba(100,120,145,.10);
}
.stage-group b { font-size: .84rem; }
.stage-group span { font-size: .70rem; opacity: .78; margin-top: .18rem; }
.stage-order { background: rgba(80,120,190,.10); }
.stage-production { background: rgba(80,160,220,.12); }
.stage-warehouse { background: rgba(70,175,175,.11); }
.stage-transport { background: rgba(210,170,70,.12); }
.stage-installation { background: rgba(80,165,100,.12); border-right: 0; }
.stage-legend {
    display: flex;
    flex-wrap: wrap;
    gap: .7rem 1.1rem;
    padding: .48rem .75rem;
    border-top: 1px solid rgba(100,120,145,.30);
    font-size: .74rem;
}
.legend-system { color: #2b75d6; }
.legend-action { color: #218c45; }
.legend-flow { opacity: .78; }

/* Make the data editor feel like one continuous process table. */
[data-testid="stDataEditor"] {
    border-top: 2px solid rgba(100,120,145,.30);
}
</style>
""", unsafe_allow_html=True)


def _select_nav_item(state_key, option):
    # Store the active section in both session state and the URL.
    # The URL copy prevents a form/data_editor submit or a Streamlit
    # reconnect from falling back to the first menu item.
    st.session_state[state_key] = option
    st.query_params[f"nav_{state_key}"] = option


def render_button_nav(options, state_key, key_prefix, columns_per_row=None):
    """Render rectangular navigation with persistent section selection."""
    param_key = f"nav_{state_key}"
    url_value = st.query_params.get(param_key)

    if url_value in options:
        st.session_state[state_key] = url_value
    elif state_key not in st.session_state or st.session_state[state_key] not in options:
        st.session_state[state_key] = options[0]
        st.query_params[param_key] = options[0]

    if columns_per_row is None:
        columns_per_row = len(options)

    for start in range(0, len(options), columns_per_row):
        row = options[start:start + columns_per_row]
        cols = st.columns(len(row), gap="small")
        for col, option in zip(cols, row):
            with col:
                st.button(
                    option,
                    key=f"{key_prefix}_{start}_{option}",
                    use_container_width=True,
                    on_click=_select_nav_item,
                    args=(state_key, option),
                )

    return st.session_state[state_key]


# ============================================================
# MAIN NAVIGATION
# ============================================================

menu_options = [
    "Клиенты",
    "Объекты",
    "Изделия",
    "Склад материалов",
    "Поставщики",
    "Производство",
    "Готовая продукция",
    "Транспорт и логистика",
    "Монтаж",
    "Зарплата",
    "Отчёты"
]

menu = render_button_nav(
    menu_options,
    "main_menu",
    "main_nav",
    columns_per_row=11
)

st.markdown("---")


# ============================================================
# CLIENTS
# ============================================================


def build_auto_material_reconciliation_statements(object_id, production_items):
    """Reconcile direct warehouse postings for production already reached by an item.

    No reservation is used. The rule is:
      required material -> use current stock -> automatically purchase shortage ->
      issue the complete required quantity to production -> record consumption.

    The reconciliation is idempotent and also backfills legacy items that reached
    later stages before the direct warehouse workflow existed.
    """
    ensure_material_planning_tables()
    ensure_object_item_material_costs(object_id)

    requested={}
    for item_id, produced_qty in production_items:
        item_id=safe_int(item_id); produced_qty=float(produced_qty or 0)
        if item_id>0 and produced_qty>0:
            requested[item_id]=max(requested.get(item_id,0.0),produced_qty)
    if not requested:
        return []

    material_targets={}
    for item_id, produced_qty in requested.items():
        req=run_query(
            """
            SELECT ptm.material_id,
                   COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)::numeric AS quantity_per_unit,
                   COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)::numeric AS waste_coefficient,
                   COALESCE(oimc.unit_cost,m.cost_per_unit,0)::numeric AS unit_cost
            FROM reklet.object_items oi
            JOIN reklet.product_template_materials ptm ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
            JOIN reklet.materials m ON m.id=ptm.material_id
            LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=oi.id AND oimc.material_id=ptm.material_id
            WHERE oi.id=%s
            """,(item_id,),fetch=True)
        for _,rr in req.iterrows():
            mid=safe_int(rr['material_id'])
            target=produced_qty*safe_float(rr['quantity_per_unit'])*safe_float(rr['waste_coefficient'],1.0)
            if mid<=0 or target<=1e-9: continue
            b=material_targets.setdefault(mid,{'target_total':0.0,'items':[]})
            b['target_total']+=target; b['items'].append((item_id,target,safe_float(rr['unit_cost'])))

    statements=[]
    for material_id,bucket in material_targets.items():
        target_increment=bucket['target_total']
        current=run_query(
            """
            SELECT
                COALESCE((SELECT SUM(quantity) FROM reklet.material_consumption WHERE object_id=%s AND material_id=%s),0)::numeric AS consumed_qty,
                COALESCE((SELECT SUM(quantity) FROM reklet.material_transactions WHERE object_id=%s AND material_id=%s AND operation_type='production_transfer' AND transaction_type='OUT'),0)::numeric AS issued_qty,
                COALESCE((SELECT stock_quantity FROM reklet.materials WHERE id=%s),0)::numeric AS stock_quantity
            """,(object_id,material_id,object_id,material_id,material_id),fetch=True)
        if current.empty: continue
        row=current.iloc[0]
        issued_qty=safe_float(row['issued_qty']); consumed_qty=safe_float(row['consumed_qty']); stock_quantity=safe_float(row['stock_quantity'])

        existing_item_consumption=0.0
        for item_id,target_qty,_ in bucket['items']:
            ex=run_query("SELECT COALESCE(SUM(quantity),0)::numeric AS qty FROM reklet.material_consumption WHERE object_item_id=%s AND material_id=%s",(item_id,material_id),fetch=True)
            if not ex.empty: existing_item_consumption+=safe_float(ex.iloc[0]['qty'])
        missing_increment=max(target_increment-existing_item_consumption,0.0)
        if missing_increment<=1e-9: continue

        required_issued_total=consumed_qty+missing_increment
        additional_issue=max(required_issued_total-issued_qty,0.0)
        purchase_qty=max(additional_issue-stock_quantity,0.0)

        if purchase_qty>1e-9:
            supplier=run_query(
                """
                SELECT ms.supplier_id,COALESCE(NULLIF(ms.purchase_price,0),m.cost_per_unit,0)::numeric AS unit_price
                FROM reklet.material_suppliers ms
                JOIN reklet.materials m ON m.id=ms.material_id
                WHERE ms.material_id=%s
                ORDER BY ms.is_preferred DESC,ms.id
                LIMIT 1
                """,(material_id,),fetch=True)
            if not supplier.empty:
                sid=safe_int(supplier.iloc[0]['supplier_id']); price=safe_float(supplier.iloc[0]['unit_price'])
            else:
                sid=get_default_supplier_id()
                pdf=run_query("SELECT COALESCE(cost_per_unit,0)::numeric AS price FROM reklet.materials WHERE id=%s",(material_id,),fetch=True)
                price=safe_float(pdf.iloc[0]['price']) if not pdf.empty else 0.0
            statements.append((
                "WITH new_po AS (INSERT INTO reklet.purchase_orders(supplier_id,status,notes) VALUES (%s,'received',%s) RETURNING id) "
                "INSERT INTO reklet.purchase_order_items(purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price) "
                "SELECT id,%s,%s,%s,%s,%s FROM new_po",
                (sid,'Автоматическая закупка из Управления объектами',object_id,material_id,purchase_qty,purchase_qty,price)
            ))
            statements.extend([
                ("INSERT INTO reklet.material_transactions(material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')",(material_id,sid,object_id,purchase_qty,price)),
                ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(purchase_qty,material_id)),
                ("INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price",(material_id,sid,price))
            ])
            stock_quantity+=purchase_qty

        if additional_issue>1e-9:
            if stock_quantity+1e-9<additional_issue:
                raise ValueError(f"Недостаточно материала для автоматической выдачи: материал ID {material_id}, нужно {additional_issue:.4f}, на складе {stock_quantity:.4f}.")
            statements.extend([
                ("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",(material_id,object_id,additional_issue)),
                ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(additional_issue,material_id))
            ])

        remaining_to_write=missing_increment
        for item_id,target_qty,unit_cost in bucket['items']:
            if remaining_to_write<=1e-9: break
            ex=run_query("SELECT COALESCE(SUM(quantity),0)::numeric AS qty FROM reklet.material_consumption WHERE object_item_id=%s AND material_id=%s",(item_id,material_id),fetch=True)
            existing_qty=safe_float(ex.iloc[0]['qty']) if not ex.empty else 0.0
            item_missing=max(target_qty-existing_qty,0.0); write_qty=min(item_missing,remaining_to_write)
            if write_qty>1e-9:
                statements.append(("INSERT INTO reklet.material_consumption(object_item_id,object_id,material_id,quantity,unit_cost_snapshot) VALUES (%s,%s,%s,%s,%s)",(item_id,object_id,material_id,write_qty,unit_cost)))
                remaining_to_write-=write_qty
    return statements


if menu == "Клиенты":

    st.header("Клиенты")

    client_sub = render_button_nav(
        ["Клиенты", "Добавить клиента", "Корректировка"],
        "clients_navigation",
        "clients_nav",
        columns_per_row=3
    )

    clients_all = get_clients()

    if client_sub == "Клиенты":
        clients = clients_all.copy()
        client_options = ["Все клиенты"] + (
            clients["name"].fillna("").astype(str).str.strip().loc[lambda x: x != ""].sort_values().unique().tolist()
            if not clients.empty else []
        )
        selected_client = st.selectbox(
            "Отбор по клиенту",
            client_options,
            key="client_filter_list"
        )
        if selected_client != "Все клиенты":
            clients = clients[
                clients["name"].fillna("").astype(str).str.strip().eq(selected_client)
            ].copy()

        st.subheader("Перечень клиентов")
        if clients.empty:
            st.info("Клиентов нет.")
        else:
            display = clients[["id", "name", "phone", "address", "email", "website", "notes"]].copy()
            display.columns = ["ID", "Наименование", "Телефон", "Адрес", "Email", "Веб-сайт", "Примечание"]
            st.dataframe(display, width="stretch", hide_index=True)
            render_print_html("Перечень клиентов", display, "print_clients_list")

    elif client_sub == "Добавить клиента":
        st.subheader("Добавить клиента")
        with st.form("add_client_form"):
            name = st.text_input("Наименование")
            phone = st.text_input("Телефон")
            address = st.text_input("Адрес")
            email = st.text_input("Email")
            website = st.text_input("Веб-сайт")
            notes = st.text_area("Примечание")
            submit = st.form_submit_button("Добавить клиента")
            if submit:
                if not name.strip():
                    st.warning("Необходимо указать наименование клиента.")
                else:
                    run_query(
                        """
                        INSERT INTO reklet.clients
                            (name, phone, address, email, website, notes, contact_info)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (name.strip(), phone.strip() or None, address.strip() or None,
                         email.strip() or None, website.strip() or None, notes.strip() or None,
                         phone.strip() or None)
                    )
                    st.success("Клиент добавлен.")
                    st.rerun()

    elif client_sub == "Корректировка":
        # До выбора клиента в этом разделе отображается только отбор.
        client_rows = clients_all[["id", "name", "phone", "address", "email", "website", "notes"]].copy()
        client_rows["name"] = client_rows["name"].fillna("").astype(str).str.strip()
        client_rows = client_rows[client_rows["name"] != ""].sort_values("name")

        client_options = ["— Выберите клиента —"] + [
            f"{int(row['id'])} — {row['name']}"
            for _, row in client_rows.iterrows()
        ]

        selected_client_label = st.selectbox(
            "Отбор по клиенту",
            client_options,
            index=0,
            key="client_edit_filter"
        )

        if selected_client_label == "— Выберите клиента —":
            st.info("Выберите клиента для корректировки.")
        else:
            client_id = int(selected_client_label.split(" — ")[0])
            row = client_rows[client_rows["id"] == client_id].iloc[0]
            st.subheader("Корректировка клиента")
            pending_key = f"client_edit_pending_{client_id}"

            with st.form(f"edit_client_form_{client_id}", clear_on_submit=False):
                name = st.text_input("Наименование", value=str(row["name"] or ""))
                phone = st.text_input("Телефон", value=str(row["phone"] or ""))
                address = st.text_input("Адрес", value=str(row["address"] or ""))
                email = st.text_input("Email", value=str(row["email"] or ""))
                website = st.text_input("Веб-сайт", value=str(row["website"] or ""))
                notes = st.text_area("Примечание", value=str(row["notes"] or ""))
                execute_client_changes = st.form_submit_button("Выполнить", use_container_width=True)

            if execute_client_changes:
                new_values = {
                    "name": name.strip(),
                    "phone": phone.strip() or None,
                    "address": address.strip() or None,
                    "email": email.strip() or None,
                    "website": website.strip() or None,
                    "notes": notes.strip() or None,
                }
                errors = []
                if not new_values["name"]:
                    errors.append("Наименование клиента не может быть пустым.")

                comparisons = [
                    ("name", "Наименование", str(row["name"] or "").strip(), new_values["name"]),
                    ("phone", "Телефон", str(row["phone"] or "").strip(), new_values["phone"] or ""),
                    ("address", "Адрес", str(row["address"] or "").strip(), new_values["address"] or ""),
                    ("email", "Email", str(row["email"] or "").strip(), new_values["email"] or ""),
                    ("website", "Веб-сайт", str(row["website"] or "").strip(), new_values["website"] or ""),
                    ("notes", "Примечание", str(row["notes"] or "").strip(), new_values["notes"] or ""),
                ]
                changes = []
                for _, label, old_val, new_val in comparisons:
                    if str(old_val or "") != str(new_val or ""):
                        changes.append({
                            "Поле": label,
                            "Было": old_val if old_val not in (None, "") else "—",
                            "Станет": new_val if new_val not in (None, "") else "—",
                        })

                if errors:
                    for err in errors:
                        st.error(err)
                elif changes:
                    st.session_state[pending_key] = {
                        "client_id": client_id,
                        "values": new_values,
                        "changes": changes,
                    }
                else:
                    st.info("Изменений нет.")

            pending = st.session_state.get(pending_key)
            if pending:
                st.markdown("---")
                st.subheader("Подтверждение изменений")
                st.dataframe(pd.DataFrame(pending["changes"]), width="stretch", hide_index=True)
                c1, c2 = st.columns(2)
                with c1:
                    confirm_client_changes = st.button(
                        "Подтвердить", key=f"confirm_client_edit_{client_id}",
                        type="primary", use_container_width=True
                    )
                with c2:
                    cancel_client_changes = st.button(
                        "Отмена", key=f"cancel_client_edit_{client_id}",
                        use_container_width=True
                    )

                if confirm_client_changes:
                    v = pending["values"]
                    try:
                        run_transaction([
                            (
                                """
                                UPDATE reklet.clients
                                SET name=%s,
                                    phone=%s,
                                    address=%s,
                                    email=%s,
                                    website=%s,
                                    notes=%s,
                                    contact_info=%s
                                WHERE id=%s
                                """,
                                (
                                    v["name"], v["phone"], v["address"], v["email"],
                                    v["website"], v["notes"], v["phone"], client_id
                                )
                            )
                        ])
                        st.session_state.pop(pending_key, None)
                        st.success("Данные клиента изменены.")
                        st.rerun()
                    except Exception as e:
                        st.error("Изменения не сохранены. Транзакция отменена.")
                        st.code(str(e))

                if cancel_client_changes:
                    st.session_state.pop(pending_key, None)
                    st.rerun()

            with st.expander("Безопасное удаление клиента"):
                st.warning(
                    "Удаление необратимо. Клиента нельзя удалить, если он используется хотя бы одним объектом."
                )
                delete_confirm = st.checkbox(
                    "Я подтверждаю удаление выбранного клиента.",
                    key=f"confirm_delete_client_{client_id}"
                )
                if st.button(
                    "Удалить клиента",
                    key=f"delete_client_{client_id}",
                    disabled=not delete_confirm,
                    use_container_width=True
                ):
                    used = run_query(
                        "SELECT COUNT(*) AS cnt FROM reklet.objects WHERE client_id=%s",
                        (client_id,), fetch=True
                    )
                    if int(used.iloc[0]["cnt"]) > 0:
                        st.error("Удаление невозможно: этот клиент используется объектами.")
                    else:
                        run_query("DELETE FROM reklet.clients WHERE id=%s", (client_id,))
                        st.success("Клиент удалён.")
                        st.rerun()


# OBJECTS
# ============================================================
elif menu == "Объекты":
    st.header("Объекты")

    sub = render_button_nav(
        [
            "Перечень объектов",
            "Создать новый объект",
            "Данные объекта",
            "Добавить изделия в объект",
            "Материалы объекта",
            "Управление объектами"
        ],
        "objects_navigation",
        "objects_nav",
        columns_per_row=7
    )

    st.markdown("---")

    # Двойной отбор для разделов, где данные должны быть пустыми
    # до выбора конкретного заказчика и конкретного объекта.
    def select_object_by_customer(prefix):
        clients = get_clients()
        objects = get_objects().sort_values("id", ascending=False).copy()

        if clients.empty:
            st.info("Заказчики отсутствуют.")
            return None, None
        if objects.empty:
            st.info("Объектов нет.")
            return None, None

        client_rows = clients[["id", "name"]].copy()
        client_rows["name"] = client_rows["name"].fillna("").astype(str).str.strip()
        client_rows = client_rows[client_rows["name"] != ""].drop_duplicates(subset=["id"])
        client_options = [
            f"{int(r['id'])} — {r['name']}"
            for _, r in client_rows.iterrows()
        ]

        selected_client = st.selectbox(
            "Заказчик",
            ["— Выберите заказчика —"] + client_options,
            index=0,
            key=f"{prefix}_customer_select"
        )

        if selected_client == "— Выберите заказчика —":
            st.info("Сначала выберите заказчика.")
            return None, None

        client_id = int(selected_client.split(" — ")[0])
        client_objects = objects[
            pd.to_numeric(objects["client_id"], errors="coerce").eq(client_id)
        ].copy()

        if client_objects.empty:
            st.info("У выбранного заказчика нет объектов.")
            return None, None

        object_options = [
            f"{int(r['id'])} — {str(r['object_name'] or '').strip()}"
            for _, r in client_objects.iterrows()
        ]

        selected_object = st.selectbox(
            "Объект",
            ["— Выберите объект —"] + object_options,
            index=0,
            key=f"{prefix}_object_select_{client_id}"
        )

        if selected_object == "— Выберите объект —":
            st.info("Теперь выберите объект.")
            return None, None

        object_id = int(selected_object.split(" — ")[0])
        object_row = client_objects[client_objects["id"] == object_id].iloc[0]
        return object_id, object_row

    # ------------------------------------------------------------
    # СПИСОК ОБЪЕКТОВ
    # ------------------------------------------------------------
    if sub == "Перечень объектов":
        df = get_objects()
        if df.empty:
            st.info("Объектов нет.")
        else:
            customer_options = ["Все заказчики"] + (
                sorted(
                    df["client_name"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .loc[lambda x: x != ""]
                    .unique()
                    .tolist()
                )
            )
            customer_filter = st.selectbox(
                "Отбор по заказчику",
                customer_options,
                key="object_list_customer_filter"
            )
            if customer_filter != "Все заказчики":
                df = df[
                    df["client_name"].fillna("").astype(str).str.strip().eq(customer_filter)
                ].copy()
            display = df[["id", "client_name", "object_name", "address"]].copy()
            display.columns = ["ID", "Заказчик", "Объект", "Адрес"]
            st.dataframe(display, width="stretch", hide_index=True)
            render_print_html("Перечень объектов", display, "print_object_list")

    # ------------------------------------------------------------
    # ДАННЫЕ ОБЪЕКТА — ДВОЙНОЙ ОТБОР + EXCEL-LIKE КОРРЕКЦИЯ
    # ------------------------------------------------------------
    elif sub == "Данные объекта":
        clients = get_clients()
        objects = get_objects().sort_values("id", ascending=False).copy()

        if clients.empty or objects.empty:
            st.info("Для просмотра данных объекта нужен хотя бы один заказчик и объект.")
        else:
            client_rows = clients[["id", "name"]].copy()
            client_rows["name"] = client_rows["name"].fillna("").astype(str).str.strip()
            client_rows = client_rows[client_rows["name"] != ""]
            client_options = [f"{int(r['id'])} — {r['name']}" for _, r in client_rows.iterrows()]

            selected_client_label = st.selectbox(
                "Заказчик",
                ["— Выберите заказчика —"] + client_options,
                index=0,
                key="object_data_customer_filter"
            )

            if selected_client_label == "— Выберите заказчика —":
                st.info("Сначала выберите заказчика.")
            else:
                selected_client_id = int(selected_client_label.split(" — ")[0])
                client_objects = objects[
                    pd.to_numeric(objects["client_id"], errors="coerce").eq(selected_client_id)
                ].copy()

                if client_objects.empty:
                    st.info("У выбранного заказчика нет объектов.")
                else:
                    object_options = [
                        f"{int(r['id'])} — {str(r['object_name'] or '').strip()}"
                        for _, r in client_objects.iterrows()
                    ]
                    selected_object_label = st.selectbox(
                        "Объект",
                        ["— Выберите объект —"] + object_options,
                        index=0,
                        key=f"object_data_object_filter_{selected_client_id}"
                    )

                    if selected_object_label == "— Выберите объект —":
                        st.info("Теперь выберите объект.")
                    else:
                        object_id = int(selected_object_label.split(" — ")[0])
                        object_data = run_query(
                            """
                            SELECT
                                o.id,
                                o.client_id,
                                c.name AS client_name,
                                o.object_name,
                                o.address,
                                o.transport_distance_km,
                                o.created_at,
                                o.phone,
                                o.contact_person,
                                o.notes,
                                o.contract_date,
                                o.production_start_date,
                                o.production_end_date,
                                o.installation_date,
                                o.installation_end_date
                            FROM reklet.objects o
                            LEFT JOIN reklet.clients c ON c.id = o.client_id
                            WHERE o.id = %s
                            """,
                            (object_id,), fetch=True
                        )

                        if object_data.empty:
                            st.warning("Выбранный объект не найден.")
                        else:
                            original = object_data.iloc[0].copy()

                            def as_date(value):
                                if value is None or pd.isna(value):
                                    return None
                                ts = pd.to_datetime(value, errors="coerce")
                                return None if pd.isna(ts) else ts.date()

                            original_dates = {
                                "contract_date": as_date(original.get("contract_date")),
                                "production_start_date": as_date(original.get("production_start_date")),
                                "production_end_date": as_date(original.get("production_end_date")),
                                "installation_date": as_date(original.get("installation_date")),
                                "installation_end_date": as_date(original.get("installation_end_date")),
                            }

                            client_name_to_id = {
                                str(r["name"]).strip(): int(r["id"])
                                for _, r in client_rows.iterrows()
                            }
                            client_names = list(client_name_to_id.keys())

                            # Печатное представление сохраняем, но в вертикальном виде.
                            object_view = pd.DataFrame({
                                "Поле": [
                                    "ID", "ID заказчика", "Заказчик", "Объект", "Адрес",
                                    "Расстояние до объекта, км", "Телефон", "Контактное лицо",
                                    "Примечания", "Дата договора", "Начало производства",
                                    "Окончание производства", "Дата монтажа", "Окончание монтажа", "Создан"
                                ],
                                "Значение": [
                                    safe_int(original.get("id")), safe_int(original.get("client_id")),
                                    str(original.get("client_name") or "").strip(),
                                    str(original.get("object_name") or "").strip(),
                                    str(original.get("address") or "").strip(),
                                    safe_float(original.get("transport_distance_km")),
                                    str(original.get("phone") or "").strip(),
                                    str(original.get("contact_person") or "").strip(),
                                    str(original.get("notes") or "").strip(),
                                    original_dates["contract_date"], original_dates["production_start_date"],
                                    original_dates["production_end_date"], original_dates["installation_date"],
                                    original_dates["installation_end_date"],
                                    str(original.get("created_at") or "") if pd.notna(original.get("created_at")) else "",
                                ],
                            })
                            render_print_html(
                                f"Данные объекта — {str(original.get('object_name') or '').strip()}",
                                object_view,
                                f"print_object_data_{object_id}",
                                subtitle=f"Заказчик: {str(original.get('client_name') or '').strip()}"
                            )

                            # Вертикальная форма: параметр слева, значение справа.
                            with st.form(f"object_data_form_{object_id}", clear_on_submit=False):
                                c1, c2 = st.columns([1, 2], gap="small")
                                with c1: st.markdown("**ID**")
                                with c2:
                                    st.text_input("ID", value=str(safe_int(original.get("id"))), disabled=True,
                                                  label_visibility="collapsed", key=f"obj_id_{object_id}")

                                c1, c2 = st.columns([1, 2], gap="small")
                                with c1: st.markdown("**ID заказчика**")
                                with c2:
                                    st.text_input("ID заказчика", value=str(safe_int(original.get("client_id"))), disabled=True,
                                                  label_visibility="collapsed", key=f"obj_client_id_{object_id}")

                                current_client_name = str(original.get("client_name") or "").strip()
                                c1, c2 = st.columns([1, 2], gap="small")
                                with c1: st.markdown("**Заказчик**")
                                with c2:
                                    edited_client_name = st.selectbox(
                                        "Заказчик", client_names,
                                        index=client_names.index(current_client_name) if current_client_name in client_names else 0,
                                        key=f"obj_client_name_{object_id}", label_visibility="collapsed"
                                    )

                                fields = [
                                    ("Объект", "obj_name", str(original.get("object_name") or "").strip()),
                                    ("Адрес", "obj_address", str(original.get("address") or "").strip()),
                                    ("Телефон", "obj_phone", str(original.get("phone") or "").strip()),
                                    ("Контактное лицо", "obj_contact", str(original.get("contact_person") or "").strip()),
                                    ("Примечания", "obj_notes", str(original.get("notes") or "").strip()),
                                ]
                                edited_text = {}
                                for label, key_name, value in fields:
                                    c1, c2 = st.columns([1, 2], gap="small")
                                    with c1: st.markdown(f"**{label}**")
                                    with c2:
                                        edited_text[key_name] = st.text_input(
                                            label, value=value, label_visibility="collapsed",
                                            key=f"{key_name}_{object_id}"
                                        )

                                c1, c2 = st.columns([1, 2], gap="small")
                                with c1: st.markdown("**Расстояние до объекта, км**")
                                with c2:
                                    edited_distance = st.number_input(
                                        "Расстояние до объекта, км", min_value=0.0,
                                        value=max(0.0, safe_float(original.get("transport_distance_km"))), step=0.1,
                                        label_visibility="collapsed", key=f"obj_distance_{object_id}"
                                    )

                                date_fields = [
                                    ("Дата договора", "contract_date", f"obj_contract_{object_id}"),
                                    ("Начало производства", "production_start_date", f"obj_prod_start_{object_id}"),
                                    ("Окончание производства", "production_end_date", f"obj_prod_end_{object_id}"),
                                    ("Дата монтажа", "installation_date", f"obj_install_{object_id}"),
                                    ("Окончание монтажа", "installation_end_date", f"obj_install_end_{object_id}"),
                                ]
                                edited_dates = {}
                                for label, field_name, field_key in date_fields:
                                    c1, c2 = st.columns([1, 2], gap="small")
                                    with c1: st.markdown(f"**{label}**")
                                    with c2:
                                        default_date = original_dates[field_name] or pd.Timestamp.today().date()
                                        edited_dates[field_name] = st.date_input(
                                            label, value=default_date,
                                            label_visibility="collapsed", key=field_key
                                        )

                                c1, c2 = st.columns([1, 2], gap="small")
                                with c1: st.markdown("**Создан**")
                                with c2:
                                    st.text_input(
                                        "Создан",
                                        value=str(original.get("created_at") or "") if pd.notna(original.get("created_at")) else "",
                                        disabled=True, label_visibility="collapsed", key=f"obj_created_{object_id}"
                                    )

                                execute_object_data = st.form_submit_button("Выполнить", use_container_width=True)

                            pending_key = f"object_data_pending_{object_id}"

                            if execute_object_data:
                                new_client_name = str(edited_client_name or "").strip()
                                new_object_name = str(edited_text["obj_name"] or "").strip()
                                new_distance = safe_float(edited_distance)
                                errors = []

                                if new_client_name not in client_name_to_id:
                                    errors.append("Необходимо выбрать существующего заказчика.")
                                if not new_object_name:
                                    errors.append("Название объекта не может быть пустым.")
                                if new_distance < 0:
                                    errors.append("Расстояние до объекта не может быть отрицательным.")

                                new_values = {
                                    "client_id": client_name_to_id.get(new_client_name),
                                    "object_name": new_object_name,
                                    "address": edited_text["obj_address"].strip() or None,
                                    "transport_distance_km": new_distance,
                                    "phone": edited_text["obj_phone"].strip() or None,
                                    "contact_person": edited_text["obj_contact"].strip() or None,
                                    "notes": edited_text["obj_notes"].strip() or None,
                                    "contract_date": edited_dates["contract_date"],
                                    "production_start_date": edited_dates["production_start_date"],
                                    "production_end_date": edited_dates["production_end_date"],
                                    "installation_date": edited_dates["installation_date"],
                                    "installation_end_date": edited_dates["installation_end_date"],
                                }

                                comparisons = [
                                    ("client_id", "Заказчик", str(original.get("client_name") or "").strip(), new_client_name),
                                    ("object_name", "Объект", str(original.get("object_name") or "").strip(), new_values["object_name"]),
                                    ("address", "Адрес", str(original.get("address") or "").strip(), new_values["address"] or ""),
                                    ("transport_distance_km", "Расстояние до объекта, км", safe_float(original.get("transport_distance_km")), new_values["transport_distance_km"]),
                                    ("phone", "Телефон", str(original.get("phone") or "").strip(), new_values["phone"] or ""),
                                    ("contact_person", "Контактное лицо", str(original.get("contact_person") or "").strip(), new_values["contact_person"] or ""),
                                    ("notes", "Примечания", str(original.get("notes") or "").strip(), new_values["notes"] or ""),
                                    ("contract_date", "Дата договора", original_dates["contract_date"], new_values["contract_date"]),
                                    ("production_start_date", "Начало производства", original_dates["production_start_date"], new_values["production_start_date"]),
                                    ("production_end_date", "Окончание производства", original_dates["production_end_date"], new_values["production_end_date"]),
                                    ("installation_date", "Дата монтажа", original_dates["installation_date"], new_values["installation_date"]),
                                    ("installation_end_date", "Окончание монтажа", original_dates["installation_end_date"], new_values["installation_end_date"]),
                                ]
                                changes = []
                                for key, label, old_val, new_val in comparisons:
                                    if key == "transport_distance_km":
                                        old_cmp = round(float(old_val or 0), 6)
                                        new_cmp = round(float(new_val or 0), 6)
                                    elif key in {"contract_date", "production_start_date", "production_end_date", "installation_date", "installation_end_date"}:
                                        old_cmp = old_val.isoformat() if old_val else None
                                        new_cmp = new_val.isoformat() if new_val else None
                                    else:
                                        old_cmp = str(old_val or "")
                                        new_cmp = str(new_val or "")
                                    if old_cmp != new_cmp:
                                        changes.append({
                                            "Поле": label,
                                            "Было": old_val if old_val not in (None, "") else "—",
                                            "Станет": new_val if new_val not in (None, "") else "—",
                                        })

                                if errors:
                                    for err in errors:
                                        st.error(err)
                                elif changes:
                                    st.session_state[pending_key] = {
                                        "object_id": object_id,
                                        "values": new_values,
                                        "changes": changes,
                                    }
                                else:
                                    st.info("Изменений нет.")

                            pending = st.session_state.get(pending_key)
                            if pending:
                                st.markdown("---")
                                st.subheader("Подтверждение изменений")
                                st.dataframe(pd.DataFrame(pending["changes"]), width="stretch", hide_index=True)
                                c1, c2 = st.columns(2)
                                with c1:
                                    confirm_changes = st.button(
                                        "Подтвердить", key=f"confirm_object_data_{object_id}",
                                        type="primary", use_container_width=True
                                    )
                                with c2:
                                    cancel_changes = st.button(
                                        "Отмена", key=f"cancel_object_data_{object_id}", use_container_width=True
                                    )

                                if confirm_changes:
                                    v = pending["values"]
                                    try:
                                        run_transaction([
                                            (
                                                """
                                                UPDATE reklet.objects
                                                SET client_id=%s,
                                                    object_name=%s,
                                                    address=%s,
                                                    transport_distance_km=%s,
                                                    phone=%s,
                                                    contact_person=%s,
                                                    notes=%s,
                                                    contract_date=%s,
                                                    production_start_date=%s,
                                                    production_end_date=%s,
                                                    installation_date=%s,
                                                    installation_end_date=%s
                                                WHERE id=%s
                                                """,
                                                (
                                                    v["client_id"], v["object_name"], v["address"],
                                                    v["transport_distance_km"], v["phone"], v["contact_person"],
                                                    v["notes"], v["contract_date"], v["production_start_date"],
                                                    v["production_end_date"], v["installation_date"],
                                                    v["installation_end_date"], object_id
                                                )
                                            )
                                        ])
                                        st.session_state.pop(pending_key, None)
                                        st.success("Данные объекта изменены.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error("Изменения не сохранены. Транзакция отменена.")
                                        st.code(str(e))

                                if cancel_changes:
                                    st.session_state.pop(pending_key, None)
                                    st.rerun()

                            # Existing safe deletion block remains in its closed expander.
                            with st.expander("Безопасное удаление объекта"):
                                st.warning(
                                    "Удаление необратимо. Объект можно удалить только если в системе нет "
                                    "изделий, готовой продукции и истории производства, отгрузки, доставки, материалов или монтажа."
                                )
                                delete_confirm = st.checkbox(
                                    "Я подтверждаю удаление выбранного объекта.",
                                    key=f"confirm_delete_object_{object_id}"
                                )
                                if st.button(
                                    "Удалить объект",
                                    key=f"delete_object_{object_id}",
                                    disabled=not delete_confirm,
                                    use_container_width=True
                                ):
                                    refs = run_query(
                                        """
                                        SELECT
                                            (SELECT COUNT(*) FROM reklet.object_items WHERE object_id=%s) AS object_items,
                                            (SELECT COUNT(*) FROM reklet.production_transactions WHERE object_id=%s) AS production_transactions,
                                            (SELECT COUNT(*) FROM reklet.finished_goods WHERE object_id=%s) AS finished_goods,
                                            (SELECT COUNT(*) FROM reklet.finished_goods_transactions WHERE object_id=%s) AS finished_goods_transactions,
                                            (SELECT COUNT(*) FROM reklet.transport_transactions WHERE object_id=%s) AS transport_transactions,
                                            (SELECT COUNT(*) FROM reklet.installation_transactions WHERE object_id=%s) AS installation_transactions,
                                            (SELECT COUNT(*) FROM reklet.material_transactions WHERE object_id=%s) AS material_transactions,
                                            (SELECT COUNT(*) FROM reklet.purchase_order_items WHERE object_id=%s) AS purchase_order_items,
                                            (SELECT COUNT(*) FROM reklet.material_consumption WHERE object_id=%s) AS material_consumption,
                                            (SELECT COUNT(*) FROM reklet.material_production_requests WHERE object_id=%s) AS material_production_requests,
                                            (SELECT COUNT(*) FROM reklet.material_waste_transactions WHERE object_id=%s) AS material_waste_transactions,
                                            (SELECT COUNT(*) FROM reklet.work_time_calculations WHERE object_id=%s) AS work_time_calculations
                                        """,
                                        (object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id, object_id),
                                        fetch=True
                                    ).iloc[0]

                                    ref_labels = {
                                        "object_items": "изделия объекта",
                                        "production_transactions": "история производства",
                                        "finished_goods": "готовая продукция",
                                        "finished_goods_transactions": "история движения готовой продукции",
                                        "transport_transactions": "история транспортировки",
                                        "installation_transactions": "история монтажа",
                                        "material_transactions": "движения материалов по объекту",
                                        "purchase_order_items": "закупки материалов по объекту",
                                        "material_consumption": "списание материалов в производстве",
                                        "material_production_requests": "заявки производства на материалы",
                                        "material_waste_transactions": "история списания брака",
                                        "work_time_calculations": "расчёты рабочего времени",
                                    }
                                    blocking_refs = [
                                        label for key, label in ref_labels.items()
                                        if int(refs.get(key, 0) or 0) > 0
                                    ]
                                    if blocking_refs:
                                        st.error(
                                            "Удаление запрещено. Связанные данные: " + ", ".join(blocking_refs) + "."
                                        )
                                    else:
                                        try:
                                            run_query("DELETE FROM reklet.objects WHERE id=%s", (object_id,))
                                            st.success("Объект безопасно удалён.")
                                            st.rerun()
                                        except Exception as e:
                                            st.error("Удаление не выполнено. База данных не изменилась.")
                                            st.code(str(e))

                        st.markdown("---")
                        st.subheader(f"Содержимое объекта: {str(object_row.get('object_name', '') or '').strip()}")
                        items = get_object_items(object_id)
                        if items.empty:
                            st.info("Для этого объекта ещё не созданы изделия.")
                        else:
                            composition = items[["item_name", "quantity"]].copy().reset_index(drop=True)
                            composition.insert(0, "Nп/п", range(1, len(composition) + 1))
                            composition.columns = ["Nп/п", "Изделие", "Количество"]
                            st.dataframe(composition, width="stretch", hide_index=True)
                            render_print_html(
                                f"Содержимое объекта — {str(object_row.get('object_name', '') or '').strip()}",
                                composition,
                                f"print_object_composition_{object_id}"
                            )

    # ------------------------------------------------------------
    # ДОБАВИТЬ ИЗДЕЛИЯ НА ОБЪЕКТ
    # ------------------------------------------------------------
    elif sub == "Добавить изделия в объект":
        object_id, object_row = select_object_by_customer("add_items")

        if object_id is not None:
            client_name = str(object_row.get("client_name", "") or "").strip()
            object_name = str(object_row.get("object_name", "") or "").strip()

            st.subheader(f"Добавить изделия в объект: {object_name}")
            st.caption(f"Заказчик: {client_name}")

            templates = get_templates()
            if client_name:
                templates = templates[
                    templates["client_name"].fillna("").astype(str).str.strip().eq(client_name)
                ].copy()
            else:
                templates = templates.iloc[0:0].copy()

            if templates.empty:
                st.info("Для заказчика этого объекта ещё не созданы изделия.")
            else:
                add_df = templates[["id", "name", "client_name", "category"]].copy()
                add_df.insert(0, "Выбрать", False)
                add_df["Количество"] = 0
                add_df.columns = ["Выбрать", "ID", "Изделие", "Заказчик", "Категория", "Количество"]

                with st.form(f"add_items_form_{object_id}", clear_on_submit=False):
                    edited_add = st.data_editor(
                        add_df,
                        key=f"add_items_editor_{object_id}",
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Выбрать": st.column_config.CheckboxColumn("Выбрать"),
                            "ID": st.column_config.NumberColumn("ID", disabled=True),
                            "Изделие": st.column_config.TextColumn("Изделие", disabled=True),
                            "Заказчик": st.column_config.TextColumn("Заказчик", disabled=True),
                            "Категория": st.column_config.TextColumn("Категория", disabled=True),
                            "Количество": st.column_config.NumberColumn("Количество", min_value=0, step=1, format="%d"),
                        },
                        disabled=["ID", "Изделие", "Заказчик", "Категория"],
                    )
                    execute_add = st.form_submit_button("Добавить выбранные изделия", use_container_width=True)

                if execute_add:
                    selected_rows = edited_add[
                        edited_add["Выбрать"].fillna(False)
                        & (pd.to_numeric(edited_add["Количество"], errors="coerce").fillna(0) > 0)
                    ].copy()

                    if selected_rows.empty:
                        st.warning("Выберите хотя бы одно изделие и укажите количество.")
                    else:
                        # Не делаем st.rerun(): после выполнения остаёмся в этом же разделе и объекте.
                        statements = []
                        for _, r in selected_rows.iterrows():
                            template_id = safe_int(r["ID"])
                            qty = safe_int(r["Количество"])
                            item_name = str(r["Изделие"] or "").strip()

                            # Сначала увеличиваем существующую строку.
                            statements.append((
                                """
                                UPDATE reklet.object_items
                                SET quantity = COALESCE(quantity,0) + %s,
                                    quantity_needed = COALESCE(quantity_needed,0) + %s,
                                    qty_new = COALESCE(qty_new,0) + %s
                                WHERE object_id=%s
                                  AND (product_template_id=%s OR template_id=%s)
                                """,
                                (qty, qty, qty, object_id, template_id, template_id)
                            ))

                            # Если строки нет — создаём её.
                            statements.append((
                                """
                                INSERT INTO reklet.object_items
                                    (object_id, product_template_id, template_id,
                                     quantity_needed, item_name, quantity, qty_new, status)
                                SELECT %s,%s,%s,%s,%s,%s,%s,'New'
                                WHERE NOT EXISTS (
                                    SELECT 1
                                    FROM reklet.object_items
                                    WHERE object_id=%s
                                      AND (product_template_id=%s OR template_id=%s)
                                )
                                """,
                                (
                                    object_id, template_id, template_id,
                                    qty, item_name, qty, qty,
                                    object_id, template_id, template_id
                                )
                            ))
                            statements.append((
                                """
                                INSERT INTO reklet.object_item_material_costs
                                    (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
                                SELECT oi.id,
                                       ptm.material_id,
                                       COALESCE(ptm.quantity_per_unit,0),
                                       COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1),
                                       COALESCE(m.cost_per_unit,0)
                                FROM reklet.object_items oi
                                JOIN reklet.product_template_materials ptm
                                  ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                                JOIN reklet.materials m ON m.id=ptm.material_id
                                WHERE oi.object_id=%s
                                  AND (oi.product_template_id=%s OR oi.template_id=%s)
                                ON CONFLICT (object_item_id,material_id) DO NOTHING
                                """,
                                (object_id, template_id, template_id)
                            ))

                        try:
                            run_transaction(statements)
                            # Проверяем результат сразу, не полагаясь на состояние интерфейса.
                            saved = get_object_items(object_id)
                            saved_ids = set()
                            for _, rr in saved.iterrows():
                                if pd.notna(rr.get("product_template_id")):
                                    saved_ids.add(int(rr["product_template_id"]))
                                if pd.notna(rr.get("template_id")):
                                    saved_ids.add(int(rr["template_id"]))

                            expected_ids = {safe_int(x) for x in selected_rows["ID"].tolist()}
                            if expected_ids.issubset(saved_ids):
                                st.success(f"Добавлено изделий: {len(selected_rows)}.")
                            else:
                                st.error("Операция выполнена не полностью: не все изделия появились в составе объекта.")
                        except Exception as e:
                            st.error(f"Не удалось добавить изделия: {e}")

            st.markdown("---")
            current_items = get_object_items(object_id)
            st.subheader("Изделия объекта")
            if current_items.empty:
                st.info("Для этого объекта ещё не созданы изделия.")
            else:
                view = current_items[["id", "item_name", "quantity", "qty_new", "qty_production", "qty_ready", "qty_shipped", "qty_arrived", "qty_installing", "qty_installed"]].copy()
                view.columns = ["ID", "Изделие", "Количество", "Новые", "Производство", "Готовая продукция", "Отгружено", "Прибыло", "Монтаж", "Смонтировано"]
                st.dataframe(view, width="stretch", hide_index=True)

    # ------------------------------------------------------------
    # УПРАВЛЕНИЕ ОБЪЕКТАМИ — ЕДНА СТРОКА НА ИЗДЕЛИЕ
    # ------------------------------------------------------------
    elif sub == "Управление объектами":
        objects = get_objects().sort_values("id", ascending=False).copy()
        clients = get_clients()
        ensure_stage_movement_tables()

        if objects.empty:
            st.info("Объектов нет.")
        else:
            client_options = ["Все заказчики"] + (
                clients["name"].fillna("").astype(str).str.strip().loc[lambda x: x != ""].sort_values().unique().tolist()
                if not clients.empty else []
            )
            selected_client = st.selectbox(
                "Заказчик",
                client_options,
                key="management_client_filter"
            )

            filtered_objects = objects.copy()
            if selected_client != "Все заказчики":
                client_ids = clients[
                    clients["name"].fillna("").astype(str).str.strip().eq(selected_client)
                ]["id"].tolist()
                filtered_objects = filtered_objects[
                    filtered_objects["client_id"].isin(client_ids)
                ].copy()

            if filtered_objects.empty:
                st.info("У выбранного заказчика нет объектов.")
            else:
                object_options = ["Все объекты"] + [
                    f"{int(r['id'])} — {str(r['object_name'] or '').strip()}"
                    for _, r in filtered_objects.iterrows()
                ]
                object_map = {
                    label: int(label.split(" — ")[0]) for label in object_options
                }
                selected_object_label = st.selectbox(
                    "Объект",
                    object_options,
                    key="management_object_filter"
                )
                if selected_object_label == "Все объекты":
                    all_state = run_query(
                        """SELECT o.id AS object_id,COALESCE(c.name,'') AS client_name,o.object_name,
                                  COALESCE(SUM(oi.quantity_needed),0) AS ordered,
                                  COALESCE(SUM(oi.qty_production),0) AS in_production,
                                  COALESCE(SUM(oi.qty_ready),0) AS ready,
                                  COALESCE(SUM(oi.qty_shipped),0) AS shipped,
                                  COALESCE(SUM(oi.qty_arrived),0) AS arrived,
                                  COALESCE(SUM(oi.qty_installed),0) AS installed
                           FROM reklet.objects o
                           LEFT JOIN reklet.clients c ON c.id=o.client_id
                           JOIN reklet.object_items oi ON oi.object_id=o.id
                           WHERE (%s) OR o.client_id IN (SELECT id FROM reklet.clients WHERE name=%s)
                           GROUP BY o.id,c.name,o.object_name
                           ORDER BY o.object_name""",
                        (selected_client=="Все заказчики",selected_client),fetch=True
                    )
                    if not all_state.empty:
                        all_state["Осталось"]=(pd.to_numeric(all_state["ordered"],errors="coerce").fillna(0)-pd.to_numeric(all_state["installed"],errors="coerce").fillna(0)).clip(lower=0)
                        view=all_state.rename(columns={"object_id":"ID","client_name":"Заказчик","object_name":"Объект","ordered":"Заказано","in_production":"В производстве","ready":"Готовая продукция","shipped":"В пути","arrived":"Получено","installed":"Смонтировано"})
                        st.dataframe(view[["ID","Заказчик","Объект","Заказано","В производстве","Готовая продукция","В пути","Получено","Смонтировано","Осталось"]],width="stretch",hide_index=True)
                        render_print_html("Состояние всех объектов",view[["ID","Заказчик","Объект","Заказано","В производстве","Готовая продукция","В пути","Получено","Смонтировано","Осталось"]],"print_management_all_objects")
                    st.info("Для выполнения команд выберите конкретный объект.")
                    st.stop()

                object_id = object_map[selected_object_label]
                object_row = filtered_objects[filtered_objects["id"] == object_id].iloc[0]

                templates = get_templates()
                client_name = str(object_row.get("client_name", "") or "").strip()
                if client_name:
                    templates = templates[
                        templates["client_name"].fillna("").astype(str).str.strip().eq(client_name)
                    ].copy()
                else:
                    templates = templates.iloc[0:0].copy()

                current = get_object_items(object_id)
                current_map = {}
                if not current.empty:
                    for _, r in current.iterrows():
                        tid = r["product_template_id"] if pd.notna(r["product_template_id"]) else r["template_id"]
                        if pd.notna(tid):
                            current_map[int(tid)] = r

                # One row per product. Existing object items are retained even if
                # the product template is no longer present in the client filter.
                template_rows = {int(t["id"]): t for _, t in templates.iterrows()}
                product_ids = sorted(set(template_rows) | set(current_map))

                rows = []
                for tid in product_ids:
                    t = template_rows.get(tid)
                    old = current_map.get(tid)
                    name = str(
                        (t["name"] if t is not None else old.get("item_name", ""))
                        or ""
                    ).strip()

                    ordered = safe_int(old["quantity_needed"]) if old is not None else 0
                    qty_production = safe_int(old["qty_production"]) if old is not None else 0
                    qty_ready = safe_int(old["qty_ready"]) if old is not None else 0
                    qty_shipped = safe_int(old["qty_shipped"]) if old is not None else 0
                    qty_arrived = safe_int(old["qty_arrived"]) if old is not None else 0
                    qty_installing = safe_int(old["qty_installing"]) if old is not None else 0
                    qty_installed = safe_int(old["qty_installed"]) if old is not None else 0

                    # Keep the quantity identity derived from the physical stages.
                    # Older records may have stale qty_new values; deriving it here
                    # prevents the management screen from displaying a false remainder.
                    physical_allocated = (
                        qty_production + qty_ready + qty_shipped +
                        qty_arrived + qty_installing + qty_installed
                    )
                    qty_new = max(ordered - physical_allocated, 0)
                    remaining_manufacture = qty_new

                    rows.append({
                        "ID": tid,
                        "Изделие": name,
                        "1.1 Всего": ordered,
                        "1.2 Коррекция": 0,
                        "2.1 Осталось изготовить": remaining_manufacture,
                        "2.2 Изготовлено": 0,
                        "3.2 Прибыло": qty_ready,
                        "3.3 Отгружено": 0,
                        "3.4 Осталось": qty_ready,
                        "4.1 В пути": qty_shipped,
                        "4.2 Доставлен": 0,
                        "5.1 Получено": qty_arrived,
                        "5.2 Установлено": 0,
                        "5.4 Всего установлено": qty_installed,
                        "_qty_new": qty_new,
                        "_qty_production": qty_production,
                        "_qty_ready": qty_ready,
                        "_qty_shipped": qty_shipped,
                        "_qty_arrived": qty_arrived,
                        "_qty_installing": qty_installing,
                        "_qty_installed": qty_installed,
                    })

                if not rows:
                    st.info("Для этого заказчика ещё не созданы изделия.")
                else:
                    management_df = pd.DataFrame(rows)
                    editor_columns = [
                        "ID", "Изделие",
                        "1.1 Всего", "1.2 Коррекция",
                        "2.1 Осталось изготовить", "2.2 Изготовлено",
                        "3.2 Прибыло", "3.3 Отгружено", "3.4 Осталось",
                        "4.1 В пути", "4.2 Доставлен",
                        "5.1 Получено", "5.2 Установлено", "5.4 Всего установлено"
                    ]
                    editor_df = management_df[editor_columns].copy()

                    with st.form(f"object_management_form_{object_id}", clear_on_submit=True):
                        edited_management = st.data_editor(
                            editor_df,
                            key=f"object_management_editor_{object_id}",
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "ID": st.column_config.NumberColumn("№", disabled=True),
                                "Изделие": st.column_config.TextColumn("Изделие", disabled=True),
                                "1.1 Всего": st.column_config.NumberColumn("Заказ-Всего", disabled=True, format="%d"),
                                "1.2 Коррекция": st.column_config.NumberColumn("Заказ-Коррекция", min_value=-100000, step=1, format="%d"),
                                "2.1 Осталось изготовить": st.column_config.NumberColumn("Производство-Осталось изготовить", disabled=True, format="%d"),
                                "2.2 Изготовлено": st.column_config.NumberColumn("Производство-Изготовлено", min_value=0, step=1, format="%d"),
                                "3.2 Прибыло": st.column_config.NumberColumn("Склад-Прибыло", disabled=True, format="%d"),
                                "3.3 Отгружено": st.column_config.NumberColumn("Склад-Отгружено", min_value=0, step=1, format="%d"),
                                "3.4 Осталось": st.column_config.NumberColumn("Склад-Осталось", disabled=True, format="%d"),
                                "4.1 В пути": st.column_config.NumberColumn("Транспорт-В пути", disabled=True, format="%d"),
                                "4.2 Доставлен": st.column_config.NumberColumn("Транспорт-Доставлен", min_value=0, step=1, format="%d"),
                                "5.1 Получено": st.column_config.NumberColumn("Объект-Получено", disabled=True, format="%d"),
                                "5.2 Установлено": st.column_config.NumberColumn("Объект-Установлено", min_value=0, step=1, format="%d"),
                                "5.4 Всего установлено": st.column_config.NumberColumn("Объект-Всего установлено", disabled=True, format="%d"),
                            },
                            disabled=[
                                "ID", "Изделие",
                                "1.1 Всего", "2.1 Осталось изготовить",
                                "3.2 Прибыло", "3.4 Осталось",
                                "4.1 В пути", "5.1 Получено", "5.4 Всего установлено"
                            ],
                        )
                        management_execute = st.form_submit_button(
                            "Выполнить",
                            use_container_width=True
                        )

                    management_print = editor_df[[
                        "ID", "Изделие", "1.1 Всего", "2.1 Осталось изготовить",
                        "3.2 Прибыло", "3.4 Осталось", "4.1 В пути",
                        "5.1 Получено", "5.4 Всего установлено"
                    ]].copy()
                    management_print.columns = [
                        "№", "Изделие", "Заказ-Всего", "Производство-Осталось изготовить",
                        "Склад-Прибыло", "Склад-Осталось", "Транспорт-В пути",
                        "Объект-Получено", "Объект-Всего установлено"
                    ]
                    render_print_html(
                        f"Состояние объекта — {str(object_row.get('object_name', '') or '').strip()}",
                        management_print,
                        f"print_object_management_{object_id}"
                    )

                    if management_execute:
                        errors = []
                        pending = []

                        for idx, r in edited_management.iterrows():
                            tid = safe_int(r["ID"])
                            name = str(r["Изделие"] or "").strip()
                            base = management_df.iloc[idx]

                            old_state = {
                                "order": safe_int(base["1.1 Всего"]),
                                "new": safe_int(base["_qty_new"]),
                                "production": safe_int(base["_qty_production"]),
                                "ready": safe_int(base["_qty_ready"]),
                                "shipped": safe_int(base["_qty_shipped"]),
                                "arrived": safe_int(base["_qty_arrived"]),
                                "installing": safe_int(base["_qty_installing"]),
                                "installed": safe_int(base["_qty_installed"]),
                            }
                            state = old_state.copy()
                            commands = []
                            newly_produced_from_new = [0]

                            correction = safe_int(r["1.2 Коррекция"])
                            manufactured_action = safe_int(r["2.2 Изготовлено"])
                            shipped_action = safe_int(r["3.3 Отгружено"])
                            delivered_action = safe_int(r["4.2 Доставлен"])
                            installed_action = safe_int(r["5.2 Установлено"])

                            if any(v < 0 for v in (
                                manufactured_action,
                                shipped_action,
                                delivered_action,
                                installed_action,
                            )):
                                errors.append(f"{name}: действия производства/склада/транспорта/монтажа не могут быть отрицательными.")
                                continue

                            # Order correction changes only the unprocessed part.
                            # A reduction cannot invalidate quantities already in the chain.
                            if correction < 0:
                                decrease = -correction
                                if decrease > state["new"]:
                                    errors.append(
                                        f"{name}: нельзя уменьшить заказ на {decrease}; "
                                        f"необработанный остаток заказа только {state['new']}."
                                    )
                                    continue
                                state["order"] -= decrease
                                state["new"] -= decrease
                            elif correction > 0:
                                state["order"] += correction
                                state["new"] += correction

                            def complete_production(qty):
                                """Complete exactly qty units and put them on the warehouse."""
                                if qty <= 0:
                                    return

                                from_production = min(qty, state["production"])
                                from_new = qty - from_production

                                if from_new > state["new"]:
                                    available = state["production"] + state["new"]
                                    raise ValueError(
                                        f"для изготовления {qty} шт. доступно только {available} шт."
                                    )

                                if from_production:
                                    state["production"] -= from_production
                                if from_new:
                                    state["new"] -= from_new
                                    newly_produced_from_new[0] += from_new

                                state["ready"] += qty
                                commands.append(("production", qty))

                            def ensure_ready(qty):
                                """Ensure qty is physically available in the warehouse."""
                                shortage = max(qty - state["ready"], 0)
                                if shortage:
                                    complete_production(shortage)

                            def move_to_shipped(qty):
                                ensure_ready(qty)
                                state["ready"] -= qty
                                state["shipped"] += qty
                                commands.append(("ship", qty))

                            def ensure_shipped(qty):
                                """Ensure qty is physically in transport."""
                                shortage = max(qty - state["shipped"], 0)
                                if shortage:
                                    move_to_shipped(shortage)

                            def move_to_arrived(qty):
                                ensure_shipped(qty)
                                state["shipped"] -= qty
                                state["arrived"] += qty
                                commands.append(("arrive", qty))

                            def ensure_arrived(qty):
                                """Ensure qty is physically received at the object."""
                                shortage = max(qty - state["arrived"], 0)
                                if shortage:
                                    move_to_arrived(shortage)

                            def install_qty(qty):
                                ensure_arrived(qty)
                                state["arrived"] -= qty
                                state["installed"] += qty
                                commands.append(("install", qty))

                            # Every green field is a one-time movement command.
                            # Missing upstream stock is generated automatically from the
                            # same order, but the order itself is never silently increased.
                            action_failed = False
                            for action_name, action_qty, action_fn in (
                                ("изготовление", manufactured_action, complete_production),
                                ("отгрузка", shipped_action, move_to_shipped),
                                ("доставка", delivered_action, move_to_arrived),
                                ("установка", installed_action, install_qty),
                            ):
                                if not action_qty:
                                    continue
                                try:
                                    action_fn(action_qty)
                                except ValueError as exc:
                                    errors.append(f"{name}: {action_name} {action_qty} шт. — {exc}")
                                    action_failed = True
                                    break

                            if action_failed:
                                continue

                            # Rebuild the unprocessed remainder from the order identity.
                            allocated = (
                                state["production"] + state["ready"] + state["shipped"] +
                                state["arrived"] + state["installing"] + state["installed"]
                            )
                            if allocated > state["order"]:
                                errors.append(
                                    f"{name}: итоговое количество {allocated} шт. превышает заказ {state['order']} шт."
                                )
                                continue
                            state["new"] = state["order"] - allocated

                            changed = (
                                state != old_state or
                                correction != 0 or
                                manufactured_action != 0 or
                                shipped_action != 0 or
                                delivered_action != 0 or
                                installed_action != 0
                            )
                            if changed:
                                pending.append({
                                    "tid": tid,
                                    "name": name,
                                    "old": old_state,
                                    "new": state,
                                    "commands": commands,
                                    "newly_produced_from_new": newly_produced_from_new[0],
                                    "actions": {
                                        "correction": correction,
                                        "manufactured": manufactured_action,
                                        "shipped": shipped_action,
                                        "delivered": delivered_action,
                                        "installed": installed_action,
                                    },
                                })

                        if errors:
                            st.error("Операция не подготовлена:\n" + "\n".join(errors))
                        elif not pending:
                            st.info("Изменений для выполнения нет.")
                        else:
                            st.session_state["object_management_pending"] = {
                                "object_id": object_id,
                                "object_name": str(object_row["object_name"]),
                                "changes": pending,
                            }

                    pending = st.session_state.get("object_management_pending")
                    if pending and pending.get("object_id") == object_id:
                        st.warning("Подтвердить изменения по объекту?")
                        for change in pending["changes"]:
                            old = change["old"]
                            new = change["new"]
                            actions = change.get("actions", {})
                            st.write(f"**{change['name']}**")
                            if actions.get("correction"):
                                st.write(f"• Коррекция заказа: {actions['correction']:+d}")
                            if old["new"] != new["new"]:
                                st.write(f"• Осталось не изготовлено: {old['new']} → {new['new']}")
                            if old["production"] != new["production"]:
                                st.write(f"• В производстве: {old['production']} → {new['production']}")
                            if old["ready"] != new["ready"]:
                                st.write(f"• На складе: {old['ready']} → {new['ready']}")
                            if old["shipped"] != new["shipped"]:
                                st.write(f"• В пути: {old['shipped']} → {new['shipped']}")
                            if old["arrived"] != new["arrived"]:
                                st.write(f"• Получено на объекте: {old['arrived']} → {new['arrived']}")
                            if old["installed"] != new["installed"]:
                                st.write(f"• Всего установлено: {old['installed']} → {new['installed']}")

                        c1, c2 = st.columns(2)
                        with c1:
                            confirm = st.button(
                                "Подтвердить",
                                key=f"management_confirm_{object_id}",
                                use_container_width=True,
                            )
                        with c2:
                            cancel = st.button(
                                "Отменить",
                                key=f"management_cancel_{object_id}",
                                use_container_width=True,
                            )

                        if cancel:
                            st.session_state.pop("object_management_pending", None)
                            st.session_state.pop(f"object_management_editor_{object_id}", None)
                            st.rerun()

                        if confirm:
                            statements = []

                            # Reconcile material postings against the FINAL production
                            # stage of every changed item. This is intentionally not based
                            # on "newly produced" quantity only: legacy items that were
                            # already in transport/installation before the warehouse
                            # workflow was added must also receive their missing postings.
                            production_items = []
                            for ch in pending["changes"]:
                                new_state = ch.get("new", {})
                                planned_produced_qty = (
                                    safe_float(new_state.get("production", 0))
                                    + safe_float(new_state.get("ready", 0))
                                    + safe_float(new_state.get("shipped", 0))
                                    + safe_float(new_state.get("arrived", 0))
                                    + safe_float(new_state.get("installing", 0))
                                    + safe_float(new_state.get("installed", 0))
                                )
                                if planned_produced_qty <= 0:
                                    continue

                                item_df = run_query(
                                    """
                                    SELECT id
                                    FROM reklet.object_items
                                    WHERE object_id=%s
                                      AND (product_template_id=%s OR template_id=%s)
                                    ORDER BY id
                                    LIMIT 1
                                    """,
                                    (object_id, safe_int(ch["tid"]), safe_int(ch["tid"])),
                                    fetch=True,
                                )
                                if item_df.empty:
                                    raise ValueError(
                                        f"Не найдена позиция изделия в объекте: {ch.get('name','')}"
                                    )
                                production_items.append(
                                    (safe_int(item_df.iloc[0]["id"]), planned_produced_qty)
                                )

                            # The management screen is intentionally a shortcut: when a
                            # command starts from a later stage, all missing warehouse
                            # postings are generated automatically. The reconciliation is
                            # idempotent, so the same item can be corrected again without
                            # duplicating material purchases, transfers, or consumption.
                            try:
                                statements.extend(
                                    build_auto_material_reconciliation_statements(
                                        object_id, production_items
                                    )
                                )
                            except Exception as e:
                                st.error(f"Не удалось подготовить автоматические проводки склада: {e}")
                                st.stop()

                            for change in pending["changes"]:
                                tid = change["tid"]
                                new = change["new"]

                                # Create the object-item row if necessary.
                                statements.append((
                                    """
                                    INSERT INTO reklet.object_items
                                        (object_id, product_template_id, template_id,
                                         quantity_needed, item_name, quantity, qty_new, status)
                                    SELECT %s,%s,%s,%s,%s,%s,%s,'New'
                                    WHERE NOT EXISTS (
                                        SELECT 1
                                        FROM reklet.object_items
                                        WHERE object_id=%s
                                          AND (product_template_id=%s OR template_id=%s)
                                    )
                                    """,
                                    (
                                        object_id, tid, tid,
                                        new["order"], change["name"], new["order"], new["new"],
                                        object_id, tid, tid
                                    )
                                ))
                                statements.append((
                                    """
                                    INSERT INTO reklet.object_item_material_costs
                                        (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
                                    SELECT oi.id,
                                           ptm.material_id,
                                           COALESCE(ptm.quantity_per_unit,0),
                                           COALESCE(ptm.waste_coefficient,m.default_waste_coefficient,1),
                                           COALESCE(m.cost_per_unit,0)
                                    FROM reklet.object_items oi
                                    JOIN reklet.product_template_materials ptm
                                      ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                                    JOIN reklet.materials m ON m.id=ptm.material_id
                                    WHERE oi.object_id=%s
                                      AND (oi.product_template_id=%s OR oi.template_id=%s)
                                    ON CONFLICT (object_item_id,material_id) DO NOTHING
                                    """,
                                    (object_id, tid, tid)
                                ))

                                production_completed = (
                                    new["ready"] + new["shipped"] + new["arrived"] +
                                    new["installing"] + new["installed"]
                                )
                                production_status = (
                                    "completed" if new["new"] == 0 and new["production"] == 0 and new["order"] > 0
                                    else "in_progress" if new["production"] > 0 or production_completed > 0
                                    else "not_started"
                                )
                                installation_status = (
                                    "completed" if new["installed"] >= new["order"] and new["order"] > 0
                                    else "in_progress" if new["installed"] > 0
                                    else "not_started"
                                )

                                statements.append((
                                    """
                                    UPDATE reklet.object_items
                                    SET quantity_needed=%s,
                                        quantity=%s,
                                        qty_new=%s,
                                        qty_production=%s,
                                        qty_ready=%s,
                                        qty_shipped=%s,
                                        qty_arrived=%s,
                                        qty_installing=%s,
                                        qty_installed=%s,
                                        production_status=%s,
                                        production_progress_pct=CASE WHEN %s>0 THEN LEAST(100,ROUND(%s::numeric/%s*100)) ELSE 0 END,
                                        installation_status=%s,
                                        installation_progress_pct=CASE WHEN %s>0 THEN LEAST(100,ROUND(%s::numeric/%s*100)) ELSE 0 END
                                    WHERE object_id=%s
                                      AND (product_template_id=%s OR template_id=%s)
                                    """,
                                    (
                                        new["order"], new["order"], new["new"], new["production"],
                                        new["ready"], new["shipped"], new["arrived"],
                                        new["installing"], new["installed"],
                                        production_status,
                                        new["order"], production_completed, new["order"],
                                        installation_status,
                                        new["order"], new["installed"], new["order"],
                                        object_id, tid, tid
                                    )
                                ))

                                # Write every transition generated by the command.
                                for command in change["commands"]:
                                    kind, qty = command

                                    if kind == "production":
                                        statements.extend([
                                            (
                                                """
                                                INSERT INTO reklet.production_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'completed',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods
                                                    (object_item_id,object_id,quantity,status)
                                                SELECT id,object_id,%s,'ready'
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'ready',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                                    elif kind == "ship":
                                        statements.extend([
                                            (
                                                """
                                                WITH ready_rows AS (
                                                    SELECT
                                                        id,
                                                        quantity,
                                                        COALESCE(
                                                            SUM(quantity) OVER (
                                                                ORDER BY created_at,id
                                                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                                            ), 0
                                                        ) AS prev_quantity
                                                    FROM reklet.finished_goods
                                                    WHERE object_item_id=(
                                                        SELECT id
                                                        FROM reklet.object_items
                                                        WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                        ORDER BY id LIMIT 1
                                                    )
                                                      AND status='ready'
                                                      AND quantity>0
                                                ),
                                                updates AS (
                                                    SELECT
                                                        id,
                                                        GREATEST(
                                                            quantity - GREATEST(LEAST(%s - prev_quantity, quantity),0),
                                                            0
                                                        ) AS new_quantity
                                                    FROM ready_rows
                                                    WHERE prev_quantity < %s
                                                )
                                                UPDATE reklet.finished_goods fg
                                                SET quantity=updates.new_quantity,
                                                    status=CASE WHEN updates.new_quantity=0 THEN 'shipped' ELSE 'ready' END
                                                FROM updates
                                                WHERE fg.id=updates.id
                                                """,
                                                (object_id, tid, tid, qty, qty)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'ship',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.transport_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'ship',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                                    elif kind == "arrive":
                                        statements.extend([
                                            (
                                                """
                                                WITH shipped_rows AS (
                                                    SELECT
                                                        id,
                                                        quantity,
                                                        COALESCE(
                                                            SUM(quantity) OVER (
                                                                ORDER BY created_at,id
                                                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                                            ), 0
                                                        ) AS prev_quantity
                                                    FROM reklet.finished_goods
                                                    WHERE object_item_id=(
                                                        SELECT id
                                                        FROM reklet.object_items
                                                        WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                        ORDER BY id LIMIT 1
                                                    )
                                                      AND status='shipped'
                                                      AND quantity>0
                                                ),
                                                updates AS (
                                                    SELECT
                                                        id,
                                                        GREATEST(
                                                            quantity - GREATEST(LEAST(%s - prev_quantity, quantity),0),
                                                            0
                                                        ) AS new_quantity
                                                    FROM shipped_rows
                                                    WHERE prev_quantity < %s
                                                )
                                                UPDATE reklet.finished_goods fg
                                                SET quantity=updates.new_quantity,
                                                    status=CASE WHEN updates.new_quantity=0 THEN 'arrived' ELSE 'shipped' END
                                                FROM updates
                                                WHERE fg.id=updates.id
                                                """,
                                                (object_id, tid, tid, qty, qty)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.finished_goods_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'arrive',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.transport_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'arrive',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                                    elif kind == "install":
                                        statements.extend([
                                            (
                                                """
                                                WITH arrived_rows AS (
                                                    SELECT
                                                        id,
                                                        quantity,
                                                        COALESCE(
                                                            SUM(quantity) OVER (
                                                                ORDER BY created_at,id
                                                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                                            ), 0
                                                        ) AS prev_quantity
                                                    FROM reklet.finished_goods
                                                    WHERE object_item_id=(
                                                        SELECT id
                                                        FROM reklet.object_items
                                                        WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                        ORDER BY id LIMIT 1
                                                    )
                                                      AND status='arrived'
                                                      AND quantity>0
                                                ),
                                                updates AS (
                                                    SELECT
                                                        id,
                                                        GREATEST(
                                                            quantity - GREATEST(LEAST(%s - prev_quantity, quantity),0),
                                                            0
                                                        ) AS new_quantity
                                                    FROM arrived_rows
                                                    WHERE prev_quantity < %s
                                                )
                                                UPDATE reklet.finished_goods fg
                                                SET quantity=updates.new_quantity
                                                FROM updates
                                                WHERE fg.id=updates.id
                                                """,
                                                (object_id, tid, tid, qty, qty)
                                            ),
                                            (
                                                """
                                                INSERT INTO reklet.installation_transactions
                                                    (object_item_id,object_id,operation_type,quantity)
                                                SELECT id,object_id,'complete',%s
                                                FROM reklet.object_items
                                                WHERE object_id=%s AND (product_template_id=%s OR template_id=%s)
                                                ORDER BY id LIMIT 1
                                                """,
                                                (qty, object_id, tid, tid)
                                            ),
                                        ])

                            try:
                                run_transaction(statements)
                                # Green fields are one-time commands. Reset the editor
                                # state after a successful transaction so the action
                                # values return to zero after rerun.
                                st.session_state.pop(f"object_management_editor_{object_id}", None)
                                st.session_state.pop("object_management_pending", None)
                                st.success("Изменения выполнены. Движения записаны по всем необходимым этапам.")
                                st.rerun()
                            except Exception as e:
                                st.error("Операция не выполнена. Транзакция отменена.")
                                st.code(str(e))

                # --------------------------------------------------------
                # СТАТУСЫ ОБЪЕКТОВ
                # --------------------------------------------------------
                st.markdown("---")
                st.subheader("Статус объектов")
                status_filter = st.selectbox(
                    "Отбор по статусу",
                    ["Все объекты", "Согласован", "Запущен", "Завершен"],
                    key="object_management_status_filter"
                )

                status_df = run_query(
                    """
                    WITH item_state AS (
                        SELECT
                            oi.object_id,
                            COUNT(*) AS item_count,
                            COALESCE(SUM(COALESCE(oi.quantity_needed, 0)), 0) AS ordered_qty,
                            COALESCE(SUM(COALESCE(oi.qty_production, 0)), 0) AS production_qty,
                            COALESCE(SUM(COALESCE(oi.qty_ready, 0)), 0) AS ready_qty,
                            COALESCE(SUM(COALESCE(oi.qty_shipped, 0)), 0) AS shipped_qty,
                            COALESCE(SUM(COALESCE(oi.qty_arrived, 0)), 0) AS arrived_qty,
                            COALESCE(SUM(COALESCE(oi.qty_installing, 0)), 0) AS installing_qty,
                            COALESCE(SUM(COALESCE(oi.qty_installed, 0)), 0) AS installed_qty
                        FROM reklet.object_items oi
                        GROUP BY oi.object_id
                    ),
                    production_history AS (
                        SELECT DISTINCT object_id
                        FROM reklet.production_transactions
                        WHERE object_id IS NOT NULL
                    )
                    SELECT
                        o.id,
                        COALESCE(c.name, '') AS client_name,
                        o.object_name,
                        CASE
                            WHEN s.item_count IS NULL OR s.item_count = 0 THEN NULL
                            WHEN s.ordered_qty > 0 AND s.installed_qty >= s.ordered_qty THEN 'Завершен'
                            WHEN p.object_id IS NOT NULL
                                 OR s.production_qty > 0
                                 OR s.ready_qty > 0
                                 OR s.shipped_qty > 0
                                 OR s.arrived_qty > 0
                                 OR s.installing_qty > 0
                                 OR s.installed_qty > 0
                                THEN 'Запущен'
                            ELSE 'Согласован'
                        END AS status
                    FROM reklet.objects o
                    LEFT JOIN reklet.clients c ON c.id = o.client_id
                    LEFT JOIN item_state s ON s.object_id = o.id
                    LEFT JOIN production_history p ON p.object_id = o.id
                    WHERE s.item_count IS NOT NULL AND s.item_count > 0
                    ORDER BY o.object_name
                    """,
                    fetch=True
                )

                if status_df.empty:
                    st.info("Нет объектов с добавленными изделиями.")
                else:
                    if status_filter != "Все объекты":
                        status_df = status_df[status_df["status"] == status_filter].copy()

                    status_view = status_df[["client_name", "object_name", "status"]].copy()
                    status_view.columns = ["Заказчик", "Объект", "Статус"]

                    if status_view.empty:
                        st.info("Объектов с выбранным статусом нет.")
                    else:
                        st.dataframe(
                            status_view,
                            width="stretch",
                            hide_index=True
                        )
                        render_print_html(
                            "Статус объектов",
                            status_view,
                            "print_object_statuses",
                            subtitle=f"Отбор: {status_filter}"
                        )

    # ------------------------------------------------------------
    # ПОТРЕБНОСТЬ В МАТЕРИАЛАХ
    # ------------------------------------------------------------
    elif sub == "Материалы объекта":
        object_id, object_row = select_object_by_customer("object_material_requirement")

        if object_id is not None:
            items = get_object_items(object_id)
            if items.empty:
                st.info("К этому объекту не привязаны изделия.")
            else:
                requirements = run_query(
                    """
                    SELECT
                        oi.id AS object_item_id,
                        oi.item_name,
                        oi.quantity AS product_quantity,
                        ptm.material_id,
                        m.name AS material_name,
                        u.name AS unit_name,
                        COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit) AS quantity_per_unit,
                        COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1) AS waste_coefficient,
                        COALESCE(oimc.unit_cost, m.cost_per_unit, 0) AS cost_per_unit,
                        m.stock_quantity
                    FROM reklet.object_items oi
                    JOIN reklet.product_templates pt
                      ON pt.id = COALESCE(oi.product_template_id, oi.template_id)
                    JOIN reklet.product_template_materials ptm
                      ON ptm.product_template_id = pt.id
                    JOIN reklet.materials m ON m.id = ptm.material_id
                    LEFT JOIN reklet.object_item_material_costs oimc
                      ON oimc.object_item_id=oi.id
                     AND oimc.material_id=ptm.material_id
                    LEFT JOIN reklet.units u ON u.id = m.unit_id
                    WHERE oi.object_id = %s
                    ORDER BY oi.item_name, m.name
                    """,
                    (object_id,), fetch=True
                )
                if requirements.empty:
                    st.warning("Для изделий этого объекта ещё не создана спецификация материалов.")
                else:
                    requirements["required_quantity"] = (
                        requirements["product_quantity"]
                        * requirements["quantity_per_unit"]
                        * requirements["waste_coefficient"]
                    )
                    requirements["material_cost"] = (
                        requirements["required_quantity"]
                        * requirements["cost_per_unit"]
                    )
                    requirement_view = requirements[[
                        "item_name", "product_quantity", "material_name", "unit_name",
                        "quantity_per_unit", "waste_coefficient", "required_quantity",
                        "cost_per_unit", "material_cost"
                    ]].copy()
                    requirement_view.columns = [
                        "Изделие", "Количество", "Материал", "Единица",
                        "Количество на изделие", "Коэффициент отходов", "Требуется",
                        "Цена", "Сумма"
                    ]
                    st.dataframe(requirement_view, width="stretch", hide_index=True)
                    render_print_html(
                        f"Потребность в материалах — {str(object_row.get('object_name', '') or '').strip()}",
                        requirement_view,
                        f"print_object_material_requirement_{object_id}"
                    )

    # ------------------------------------------------------------
    # ДОБАВИТЬ ОБЪЕКТ
    # ------------------------------------------------------------
    elif sub == "Создать новый объект":
        clients = get_clients()
        client_map = {str(row["name"]): int(row["id"]) for _, row in clients.iterrows()} if not clients.empty else {}
        st.subheader("Создать объект")
        with st.form("create_object"):
            client_name = st.selectbox("Заказчик", list(client_map.keys()) if client_map else [])
            object_name = st.text_input("Название объекта")
            address = st.text_input("Адрес")
            phone = st.text_input("Телефон")
            contact_person = st.text_input("Контактное лицо")
            notes = st.text_area("Примечания")
            c1, c2 = st.columns(2)
            with c1:
                distance = st.number_input("Расстояние до объекта (км)", min_value=0.0, value=0.0)
                contract_date = st.date_input("Дата договора", value=None)
                production_start = st.date_input("Начало производства", value=None)
                production_end = st.date_input("Окончание производства", value=None)
            with c2:
                installation_date = st.date_input("Дата монтажа", value=None)
                installation_end = st.date_input("Окончание монтажа", value=None)
            submit = st.form_submit_button("Создать объект")
            if submit:
                if not client_name or not object_name.strip():
                    st.warning("Необходимо указать заказчика и название объекта.")
                else:
                    run_query(
                        """
                        INSERT INTO reklet.objects
                        (client_id, object_name, address, phone, contact_person, notes,
                         transport_distance_km, delivery_cost, contract_date,
                         production_start_date, production_end_date, installation_date, installation_end_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s)
                        """,
                        (client_map[client_name], object_name.strip(), address or None, phone or None,
                         contact_person or None, notes or None, distance,
                         contract_date, production_start, production_end, installation_date, installation_end)
                    )
                    st.success("Объект создан.")



# ============================================================
# PRODUCT TEMPLATES
# ============================================================
elif menu == "Изделия":
    st.header("Изделия")
    product_sub = render_button_nav(
        ["Перечень изделий","Добавить изделие","Спецификация изделия",
         "Корректировка изделия","Категории изделий"],
        "products_navigation","products_nav",columns_per_row=5
    )

    templates_all = get_templates()
    client_options = ["Все заказчики"] + (
        sorted(templates_all["client_name"].dropna().astype(str).str.strip()
               .loc[lambda x: x != ""].unique().tolist())
        if not templates_all.empty else []
    )
    if product_sub not in ("Добавить изделие", "Категории изделий"):
        selected_client = st.selectbox(
            "Отбор по заказчику-изделию", client_options,
            key=f"product_filter_{product_sub}"
        )
        templates = templates_all.copy()
        if selected_client != "Все заказчики":
            templates = templates[
                templates["client_name"].fillna("").astype(str).str.strip().eq(selected_client)
            ].copy()
    else:
        templates = templates_all.copy()

    if product_sub == "Перечень изделий":
        st.subheader("Перечень изделий")
        if templates.empty:
            st.info("Изделий нет.")
        else:
            display = templates[["id","name","type","client_name","category"]].copy()
            display.columns = ["ID","Изделие","Тип","Заказчик","Категория"]
            st.dataframe(display,width="stretch",hide_index=True)
            render_print_html("Перечень изделий", display, "print_product_list")

    elif product_sub == "Добавить изделие":
        st.subheader("Добавить изделие")
        clients = get_clients()
        client_map = {f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in clients.iterrows()} if not clients.empty else {}
        try:
            categories = get_product_categories()
        except Exception as e:
            categories = pd.DataFrame(columns=["id","name"])
            st.error("Не удалось открыть категории изделий.")
            st.code(str(e))
        category_options = categories["name"].astype(str).tolist() if not categories.empty else []
        with st.form("create_product_form"):
            name = st.text_input("Название изделия")
            type_value = st.selectbox("Тип",["recurrent","custom"])
            customer_label = st.selectbox("Заказчик",list(client_map.keys())) if client_map else None
            category = st.selectbox("Категория",category_options) if category_options else None
            submit = st.form_submit_button("Создать изделие")
            if submit:
                if not name.strip():
                    st.warning("Необходимо указать название изделия.")
                elif not client_map:
                    st.warning("Сначала создайте заказчика в разделе «Клиенты».")
                elif not category:
                    st.warning("Сначала создайте категорию изделия.")
                else:
                    customer_name = clients[clients["id"]==client_map[customer_label]].iloc[0]["name"]
                    run_query(
                        """INSERT INTO reklet.product_templates (name,type,client_name,category)
                           VALUES (%s,%s,%s,%s)""",
                        (name.strip(),type_value,customer_name,category)
                    )
                    st.success("Изделие создано.")
                    st.rerun()

    elif product_sub == "Категории изделий":
        st.subheader("Категории изделий")
        try:
            categories = get_product_categories()
        except Exception as e:
            categories = pd.DataFrame(columns=["id","name"])
            st.error("Не удалось открыть категории изделий.")
            st.code(str(e))

        # ----------------------------------------------------
        # ПЕРЕЧЕНЬ КАТЕГОРИЙ
        # ----------------------------------------------------
        st.markdown("### Перечень категорий")
        if categories.empty:
            st.info("Категорий изделий нет.")
        else:
            category_list = categories[["id", "name"]].copy()
            category_list.insert(0, "Nп/п", range(1, len(category_list) + 1))
            category_list.columns = ["Nп/п", "ID", "Категория"]
            st.dataframe(category_list, width="stretch", hide_index=True)
            render_print_html("Перечень категорий изделий", category_list, "print_product_categories")

        # ----------------------------------------------------
        # КОРРЕКТИРОВКА КАТЕГОРИИ
        # ----------------------------------------------------
        st.markdown("### Корректировка категории")
        if categories.empty:
            st.info("Нет категорий для корректировки.")
        else:
            category_map = {
                f"{int(row['id'])} — {str(row['name']).strip()}": int(row['id'])
                for _, row in categories.iterrows()
            }
            selected_label = st.selectbox(
                "Категория",
                ["— Выберите категорию —"] + list(category_map.keys()),
                index=0,
                key="product_category_edit_filter"
            )

            if selected_label != "— Выберите категорию —":
                category_id = category_map[selected_label]
                old_name = str(
                    categories[categories["id"] == category_id].iloc[0]["name"]
                ).strip()
                pending_key = f"product_category_edit_pending_{category_id}"

                with st.form(f"product_category_edit_form_{category_id}", clear_on_submit=False):
                    new_name = st.text_input("Новое название", value=old_name)
                    execute_category_changes = st.form_submit_button(
                        "Выполнить", use_container_width=True
                    )

                if execute_category_changes:
                    new_name_clean = new_name.strip()
                    if not new_name_clean:
                        st.error("Название категории не может быть пустым.")
                    elif new_name_clean == old_name:
                        st.info("Изменений нет.")
                    else:
                        st.session_state[pending_key] = {
                            "category_id": category_id,
                            "old_name": old_name,
                            "new_name": new_name_clean,
                        }

                pending = st.session_state.get(pending_key)
                if pending:
                    st.markdown("#### Подтверждение изменений")
                    confirmation = pd.DataFrame([{
                        "Поле": "Категория",
                        "Было": pending["old_name"],
                        "Станет": pending["new_name"],
                    }])
                    st.dataframe(confirmation, width="stretch", hide_index=True)
                    c1, c2 = st.columns(2)
                    with c1:
                        confirm_category_changes = st.button(
                            "Подтвердить",
                            key=f"confirm_product_category_edit_{category_id}",
                            type="primary",
                            use_container_width=True,
                        )
                    with c2:
                        cancel_category_changes = st.button(
                            "Отмена",
                            key=f"cancel_product_category_edit_{category_id}",
                            use_container_width=True,
                        )

                    if cancel_category_changes:
                        st.session_state.pop(pending_key, None)
                        st.rerun()

                    if confirm_category_changes:
                        try:
                            run_transaction([
                                (
                                    "UPDATE reklet.product_categories SET name=%s WHERE id=%s",
                                    (pending["new_name"], pending["category_id"])
                                ),
                                (
                                    "UPDATE reklet.product_templates SET category=%s WHERE category=%s",
                                    (pending["new_name"], pending["old_name"])
                                )
                            ])
                            st.session_state.pop(pending_key, None)
                            st.success("Категория изменена.")
                            st.rerun()
                        except Exception as e:
                            st.error("Не удалось изменить категорию.")
                            st.code(str(e))

                # ------------------------------------------------
                # БЕЗОПАСНОЕ УДАЛЕНИЕ
                # ------------------------------------------------
                st.markdown("### Безопасное удаление категории")
                with st.expander("Безопасное удаление категории", expanded=False):
                    st.warning(
                        "Удаление категории необратимо. Категория, используемая изделиями, "
                        "не может быть удалена."
                    )
                    confirm_delete_category = st.checkbox(
                        "Я подтверждаю удаление выбранной категории.",
                        key=f"confirm_delete_product_category_{category_id}"
                    )
                    if st.button(
                        "Удалить категорию",
                        key=f"delete_product_category_{category_id}",
                        disabled=not confirm_delete_category,
                    ):
                        used = run_query(
                            "SELECT COUNT(*) AS cnt FROM reklet.product_templates WHERE category=%s",
                            (old_name,), fetch=True
                        )
                        if int(used.iloc[0]["cnt"]) > 0:
                            st.error("Удаление невозможно: категория используется изделиями.")
                        else:
                            run_query(
                                "DELETE FROM reklet.product_categories WHERE id=%s",
                                (category_id,)
                            )
                            st.success("Категория удалена.")
                            st.rerun()

    elif product_sub == "Корректировка изделия":
        st.subheader("Корректировка изделия")
        if templates.empty:
            st.info("Нет изделий для корректировки.")
        else:
            pmap={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in templates.iterrows()}
            label=st.selectbox("Изделие",list(pmap.keys()),key="edit_product_select")
            pid=pmap[label]
            row=templates[templates["id"]==pid].iloc[0]
            clients=get_clients()
            cmap={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in clients.iterrows()} if not clients.empty else {}
            customer_labels=list(cmap.keys())
            current_customer=str(row["client_name"] or "")
            current_label=next((x for x in customer_labels if x.split(" — ",1)[1]==current_customer),customer_labels[0] if customer_labels else None)
            try:
                categories=get_product_categories()
                category_options=categories["name"].astype(str).tolist()
            except Exception:
                category_options=[]
            current_category=str(row["category"] or "")
            if current_category and current_category not in category_options:
                category_options=[current_category]+category_options
            with st.form("edit_product_form"):
                name=st.text_input("Название изделия",value=str(row["name"] or ""))
                type_value=st.selectbox("Тип",["recurrent","custom"],index=0 if row["type"]=="recurrent" else 1)
                customer_label=st.selectbox("Заказчик",customer_labels,index=customer_labels.index(current_label) if current_label in customer_labels else 0) if customer_labels else None
                category=st.selectbox("Категория",category_options,index=category_options.index(current_category) if current_category in category_options else 0) if category_options else None
                if st.form_submit_button("Сохранить изменения"):
                    customer_name=clients[clients["id"]==cmap[customer_label]].iloc[0]["name"] if customer_label else None
                    run_query(
                        """UPDATE reklet.product_templates SET name=%s,type=%s,client_name=%s,category=%s WHERE id=%s""",
                        (name.strip(),type_value,customer_name,category or None,pid)
                    )
                    st.success("Изделие изменено.")
                    st.rerun()
            with st.expander("Удаление изделия",expanded=False):
                st.warning("Безопасное удаление: изделие, используемое в объекте, не будет удалено.")
                confirm=st.checkbox("Я подтверждаю удаление выбранного изделия.",key="confirm_delete_product")
                if st.button("Удалить изделие",key="delete_product",disabled=not confirm):
                    used=run_query(
                        "SELECT COUNT(*) AS cnt FROM reklet.object_items WHERE product_template_id=%s OR template_id=%s",
                        (pid,pid),fetch=True
                    )
                    if int(used.iloc[0]["cnt"])>0:
                        st.error("Удаление невозможно: изделие используется в объекте.")
                    else:
                        run_transaction([
                            ("DELETE FROM reklet.product_template_materials WHERE product_template_id=%s",(pid,)),
                            ("DELETE FROM reklet.product_templates WHERE id=%s",(pid,))
                        ])
                        st.success("Изделие удалено.")
                        st.rerun()

    elif product_sub == "Спецификация изделия":
        st.subheader("Спецификация изделия")
        if templates.empty:
            st.info("Нет изделий.")
        else:
            pmap={f"{int(r['id'])} — {r['name']} — {r['client_name'] or 'Без заказчика'}":int(r['id']) for _,r in templates.iterrows()}
            selected=st.selectbox("Изделие",list(pmap.keys()),key="product_spec_select")
            pid=pmap[selected]
            specification=run_query(
                """SELECT ptm.id,ptm.material_id,m.name AS material_name,u.name AS unit_name,
                          mc.name AS category_name,ptm.quantity_per_unit,ptm.waste_coefficient
                   FROM reklet.product_template_materials ptm
                   JOIN reklet.materials m ON m.id=ptm.material_id
                   LEFT JOIN reklet.material_categories mc ON mc.id=m.category_id
                   LEFT JOIN reklet.units u ON u.id=m.unit_id
                   WHERE ptm.product_template_id=%s ORDER BY m.name""",
                (pid,),fetch=True
            )
            if specification.empty:
                st.info("В спецификации этого изделия нет материалов.")
            else:
                view=specification[["id","material_name","category_name","unit_name","quantity_per_unit","waste_coefficient"]].copy()
                view.columns=["ID","Материал","Категория","Единица","Количество на изделие","Коэффициент отходов"]
                st.dataframe(view,width="stretch",hide_index=True)
                render_print_html(
                    f"Спецификация изделия — {str(templates[templates['id']==pid].iloc[0]['name'])}",
                    view,
                    f"print_product_spec_{pid}"
                )

            st.markdown("---")
            st.subheader("Добавить материал в изделие")
            materials=get_materials_with_categories()
            material_categories=get_material_categories()
            category_options=["Все категории","Без категории"] + (
                material_categories["name"].astype(str).tolist() if not material_categories.empty else []
            )
            selected_category=st.selectbox("Отбор по категории материала",category_options,key=f"spec_material_category_{pid}")
            filtered=materials.copy()
            if selected_category=="Без категории":
                filtered=filtered[filtered["category_id"].isna()].copy()
            elif selected_category!="Все категории":
                filtered=filtered[filtered["category_name"].fillna("").astype(str).eq(selected_category)].copy()
            if filtered.empty:
                st.info("Материалов по выбранной категории нет.")
            else:
                spec_add=filtered[["id","name","category_name","unit_name"]].copy()
                spec_add.insert(0,"Выбрать",False)
                spec_add["Количество на изделие"]=0.0
                spec_add["Коэффициент отходов"]=1.20
                spec_add.columns=["Выбрать","ID","Материал","Категория","Единица","Количество на изделие","Коэффициент отходов"]
                with st.form(f"product_spec_material_form_{pid}",clear_on_submit=False):
                    edited=st.data_editor(
                        spec_add,key=f"product_spec_add_editor_{pid}_{selected_category}",
                        width="stretch",hide_index=True,
                        column_config={
                            "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                            "ID":st.column_config.NumberColumn("ID",disabled=True),
                            "Материал":st.column_config.TextColumn("Материал",disabled=True),
                            "Категория":st.column_config.TextColumn("Категория",disabled=True),
                            "Единица":st.column_config.TextColumn("Единица",disabled=True),
                            "Количество на изделие":st.column_config.NumberColumn("Количество на изделие",min_value=0.0,step=0.001,format="%.4f"),
                            "Коэффициент отходов":st.column_config.NumberColumn("Коэффициент отходов",min_value=0.0,step=0.01,format="%.2f")
                        },
                        disabled=["ID","Материал","Категория","Единица"]
                    )
                    execute=st.form_submit_button("Добавить выбранные материалы",use_container_width=True)
                if execute:
                    selected_rows=edited[
                        edited["Выбрать"].fillna(False) &
                        (edited["Количество на изделие"].fillna(0).astype(float)>0)
                    ]
                    if selected_rows.empty:
                        st.warning("Выберите материалы и укажите количество.")
                    else:
                        statements=[]
                        for _,r in selected_rows.iterrows():
                            mid=safe_int(r["ID"]); qty=safe_float(r["Количество на изделие"]); waste=safe_float(r["Коэффициент отходов"],1.20)
                            statements.extend([
                                ("UPDATE reklet.product_template_materials SET quantity_per_unit=%s,waste_coefficient=%s WHERE product_template_id=%s AND material_id=%s",(qty,waste,pid,mid)),
                                ("""INSERT INTO reklet.product_template_materials(product_template_id,material_id,quantity_per_unit,waste_coefficient)
                                   SELECT %s,%s,%s,%s WHERE NOT EXISTS
                                   (SELECT 1 FROM reklet.product_template_materials WHERE product_template_id=%s AND material_id=%s)""",
                                 (pid,mid,qty,waste,pid,mid))
                            ])
                        run_transaction(statements)
                        st.success(f"Сохранено материалов: {len(selected_rows)}.")
                        st.rerun()

# MATERIALS WAREHOUSE
# ============================================================

elif menu == "Склад материалов":

    ensure_material_planning_tables()
    ensure_task_three_tables()
    st.header("Склад материалов")

    material_sections = [
        ("Перечень материалов", "list"),
        ("Необходимые материалы для объекта", "planning"),
        ("Закупка материалов", "purchase"),
        ("Приход материалов", "receipt"),
        ("Выдача материалов в производство", "issue"),
        ("Движение материалов", "movement"),
    ]
    if "material_section" not in st.session_state:
        st.session_state.material_section = "list"

    for start_idx in range(0, len(material_sections), 3):
        row = material_sections[start_idx:start_idx + 3]
        cols = st.columns(len(row), gap="small")
        for col, (label, value) in zip(cols, row):
            with col:
                if st.button(label, key=f"material_nav_{start_idx}_{value}", use_container_width=True):
                    st.session_state.material_section = value
                    st.rerun()

    active_material_section = st.session_state.material_section
    materials = get_materials_with_categories()
    categories = get_material_categories()

    def warehouse_select_object(prefix):
        clients = get_clients()
        objects = get_objects().sort_values("id", ascending=False).copy()
        if clients.empty:
            st.info("Заказчики отсутствуют.")
            return None, None
        if objects.empty:
            st.info("Объектов нет.")
            return None, None
        client_rows = clients[["id", "name"]].copy()
        client_rows["name"] = client_rows["name"].fillna("").astype(str).str.strip()
        client_rows = client_rows[client_rows["name"] != ""]
        client_options = [f"{int(r['id'])} — {r['name']}" for _, r in client_rows.iterrows()]
        selected_client = st.selectbox(
            "Заказчик", ["— Выберите заказчика —"] + client_options,
            key=f"{prefix}_customer"
        )
        if selected_client == "— Выберите заказчика —":
            st.info("Сначала выберите заказчика.")
            return None, None
        client_id = int(selected_client.split(" — ")[0])
        client_objects = objects[pd.to_numeric(objects["client_id"], errors="coerce").eq(client_id)].copy()
        if client_objects.empty:
            st.info("У выбранного заказчика нет объектов.")
            return None, None
        object_options = [f"{int(r['id'])} — {str(r['object_name'] or '').strip()}" for _, r in client_objects.iterrows()]
        selected_object = st.selectbox(
            "Объект", ["— Выберите объект —"] + object_options,
            key=f"{prefix}_object_{client_id}"
        )
        if selected_object == "— Выберите объект —":
            st.info("Теперь выберите объект.")
            return None, None
        object_id = int(selected_object.split(" — ")[0])
        row = client_objects[client_objects["id"] == object_id].iloc[0]
        return object_id, row

    def issue_rows_for_scope(client_id=None, object_id=None):
        objs=get_objects().sort_values("id",ascending=False).copy()
        if client_id is not None: objs=objs[objs["client_id"].eq(client_id)].copy()
        if object_id is not None: objs=objs[objs["id"].eq(object_id)].copy()
        rows=[]
        for _,orow in objs.iterrows():
            oid=safe_int(orow["id"]); planning=get_object_material_planning(oid)
            if planning.empty: continue
            for _,mrow in planning.iterrows():
                rows.append({"object_id":oid,"object_name":str(orow.get("object_name","") or "").strip(),"client_name":str(orow.get("client_name","") or "").strip(),"material_id":safe_int(mrow["material_id"]),"material_name":str(mrow["material_name"] or ""),"unit_name":str(mrow["unit_name"] or ""),"stock_quantity":safe_float(mrow["stock_quantity"]),"required_quantity":safe_float(mrow["required_quantity"]),"issued_quantity":safe_float(mrow["issued_quantity"]),"available_quantity":safe_float(mrow["available_quantity"]),"work_in_process_quantity":safe_float(mrow["work_in_process_quantity"] )})
        return pd.DataFrame(rows)


    if active_material_section == "list":
        open_requests = get_open_production_requests()
        if not open_requests.empty:
            st.warning("У вас есть заказ материала с производства.")
            if st.button("Открыть заказы производства", key="open_production_requests_from_material_list", use_container_width=True):
                st.session_state.material_section = "production_requests"
                st.rerun()

        st.subheader("Перечень материалов")
        cat_options = ["Все материалы", "Без категории"] + (categories["name"].astype(str).tolist() if not categories.empty else [])
        selected_cat = st.selectbox("Отбор по категории", cat_options, key="material_category_filter_v3")
        filtered = materials.copy()
        if selected_cat == "Без категории":
            filtered = filtered[filtered["category_id"].isna()].copy()
        elif selected_cat != "Все материалы":
            filtered = filtered[filtered["category_name"].fillna("").astype(str).eq(selected_cat)].copy()

        if filtered.empty:
            st.info("Материалы по выбранному отбору отсутствуют.")
        else:
            stock_wip = get_material_stock_and_wip()
            wip_map = {safe_int(r["id"]): safe_float(r["production_wip"]) for _, r in stock_wip.iterrows()} if not stock_wip.empty else {}
            editor = filtered[["id","name","category_name","unit_name","cost_per_unit","stock_quantity","default_waste_coefficient"]].copy()
            editor["production_wip"] = editor["id"].map(wip_map).fillna(0.0)
            editor = editor[["id","name","category_name","unit_name","cost_per_unit","stock_quantity","production_wip","default_waste_coefficient"]].copy()
            editor.columns = ["ID","Материал","Категория","Единица","Цена за единицу","На складе","Остатки на производстве","Коэффициент отходов"]

            edited = st.data_editor(
                editor, key="materials_editor_v3", width="stretch", hide_index=True,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", disabled=True),
                    "Материал": st.column_config.TextColumn("Материал"),
                    "Категория": st.column_config.SelectboxColumn("Категория", options=[""] + categories["name"].astype(str).tolist(), required=False),
                    "Единица": st.column_config.TextColumn("Единица", disabled=True),
                    "Цена за единицу": st.column_config.NumberColumn("Цена за единицу", min_value=0.0, format="%.2f"),
                    "На складе": st.column_config.NumberColumn("На складе", disabled=True, format="%.4f"),
                    "Остатки на производстве": st.column_config.NumberColumn("Остатки на производстве", disabled=True, format="%.4f"),
                    "Коэффициент отходов": st.column_config.NumberColumn("Коэффициент отходов", min_value=0.0, format="%.2f"),
                },
                disabled=["ID","Единица","На складе","Остатки на производстве"],
            )
            render_print_html("Перечень материалов", edited, "print_material_list_v3", subtitle=f"Категория: {selected_cat}")

            if st.button("Сохранить изменения материалов", key="save_materials_v3", use_container_width=True):
                original_by_id = {safe_int(r["id"]): r for _, r in filtered.iterrows()}
                changes = []
                for _, row in edited.iterrows():
                    mid = safe_int(row["ID"]); old = original_by_id.get(mid)
                    if old is None: continue
                    fields=[]
                    old_name=str(old["name"] or "").strip(); new_name=str(row["Материал"] or "").strip()
                    old_cat=str(old["category_name"] or "").strip() if pd.notna(old["category_name"]) else ""
                    new_cat=str(row["Категория"] or "").strip() if pd.notna(row["Категория"]) else ""
                    old_price=safe_float(old["cost_per_unit"]); new_price=safe_float(row["Цена за единицу"])
                    old_waste=safe_float(old["default_waste_coefficient"],1.20); new_waste=safe_float(row["Коэффициент отходов"],1.20)
                    if old_name!=new_name: fields.append(("Материал",old_name,new_name))
                    if old_cat!=new_cat: fields.append(("Категория",old_cat or "—",new_cat or "—"))
                    if abs(old_price-new_price)>1e-9: fields.append(("Цена за единицу",f"{old_price:.2f}",f"{new_price:.2f}"))
                    if abs(old_waste-new_waste)>1e-9: fields.append(("Коэффициент отходов",f"{old_waste:.2f}",f"{new_waste:.2f}"))
                    if fields: changes.append({"id":mid,"fields":fields,"name":new_name,"category":new_cat,"price":new_price,"waste":new_waste})
                if changes: st.session_state["pending_material_changes_v3"] = changes
                else: st.info("Изменений нет.")

            pending = st.session_state.get("pending_material_changes_v3")
            if pending:
                st.warning("Подтверждение изменений материалов")
                rows=[]
                for ch in pending:
                    for field,b,a in ch["fields"]:
                        rows.append({"Материал":ch["name"],"Поле":field,"Было":b,"Станет":a})
                st.dataframe(pd.DataFrame(rows),width="stretch",hide_index=True)
                c1,c2=st.columns(2)
                with c1:
                    ok=st.button("Подтвердить",key="confirm_material_changes_v3",type="primary",use_container_width=True)
                with c2:
                    no=st.button("Отменить",key="cancel_material_changes_v3",use_container_width=True)
                if no:
                    st.session_state.pop("pending_material_changes_v3",None); st.session_state.pop("materials_editor_v3",None); st.rerun()
                if ok:
                    cmap={str(r["name"]):int(r["id"]) for _,r in categories.iterrows()}
                    statements=[("UPDATE reklet.materials SET name=%s,category_id=%s,cost_per_unit=%s,default_waste_coefficient=%s WHERE id=%s",(ch["name"],cmap.get(ch["category"]) if ch["category"] else None,ch["price"],ch["waste"],ch["id"])) for ch in pending]
                    run_transaction(statements); st.session_state.pop("pending_material_changes_v3",None); st.session_state.pop("materials_editor_v3",None); st.success("Изменения материалов сохранены."); st.rerun()

        with st.expander("Добавить материал", expanded=False):
            units=run_query("SELECT id,name FROM reklet.units ORDER BY name",fetch=True)
            unit_map={str(r["name"]):int(r["id"]) for _,r in units.iterrows()} if not units.empty else {}
            cat_options=["— Без категории —"]+(categories["name"].astype(str).tolist() if not categories.empty else [])
            suppliers_for_add=get_suppliers(); supplier_map={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in suppliers_for_add.iterrows()} if not suppliers_for_add.empty else {}
            with st.form("add_material_form_v3"):
                name=st.text_input("Название материала")
                unit=st.selectbox("Единица измерения",list(unit_map.keys())) if unit_map else None
                cat=st.selectbox("Категория",cat_options)
                price=st.number_input("Цена за единицу",min_value=0.0,value=0.0,format="%.2f")
                stock=st.number_input("Начальный остаток",min_value=0.0,value=0.0,format="%.4f")
                waste=st.number_input("Коэффициент отходов",min_value=0.0,value=1.20,format="%.2f")
                chosen=st.multiselect("Поставщики",list(supplier_map.keys()),key="add_material_suppliers_v3")
                chosen_primary_label=st.selectbox("Основной поставщик",["— Не назначать —"]+chosen,key="add_material_primary_supplier_v3")
                submit=st.form_submit_button("Добавить материал",use_container_width=True)
            if submit:
                if not name.strip() or not unit_map:
                    st.warning("Укажите название материала и единицу измерения.")
                else:
                    primary_id = supplier_map.get(chosen_primary_label) if chosen_primary_label != "— Не назначать —" else None
                    st.session_state["pending_material_create_v3"]={"name":name.strip(),"unit_id":unit_map[unit],"unit_name":unit,"category":cat,"price":price,"stock":stock,"waste":waste,"supplier_ids":[supplier_map[x] for x in chosen],"supplier_labels":chosen,"primary_supplier_id":primary_id}
            pending=st.session_state.get("pending_material_create_v3")
            if pending:
                st.warning("Подтвердите добавление материала")
                st.write(f"**Материал:** {pending['name']}")
                st.write(f"**Категория:** {pending['category']}")
                st.write(f"**Единица:** {pending['unit_name']}  |  **Цена:** {pending['price']:.2f}  |  **Обрез:** {pending['waste']:.2f}")
                st.write(f"**Поставщики:** {', '.join(pending['supplier_labels']) if pending['supplier_labels'] else 'не назначены'}")
                primary_label = next((x for x in pending['supplier_labels'] if supplier_map.get(x)==pending.get('primary_supplier_id')), '— Не назначен —')
                st.write(f"**Основной поставщик:** {primary_label}")
                c1,c2=st.columns(2)
                with c1: ok=st.button("Подтвердить добавление",key="confirm_material_create_v3",type="primary",use_container_width=True)
                with c2: no=st.button("Отменить",key="cancel_material_create_v3",use_container_width=True)
                if no: st.session_state.pop("pending_material_create_v3",None); st.rerun()
                if ok:
                    cat_id=None if pending["category"]=="— Без категории —" else next((int(r["id"]) for _,r in categories.iterrows() if str(r["name"])==pending["category"]),None)
                    statements=[("INSERT INTO reklet.materials(name,unit_id,category_id,cost_per_unit,stock_quantity,default_waste_coefficient) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",(pending["name"],pending["unit_id"],cat_id,pending["price"],pending["stock"],pending["waste"]))]
                    conn=get_connection(); cur=conn.cursor()
                    try:
                        cur.execute(statements[0][0],statements[0][1]); material_id=safe_int(cur.fetchone()[0])
                        for sid in pending["supplier_ids"]:
                            is_primary = bool(pending.get("primary_supplier_id")) and sid == int(pending["primary_supplier_id"])
                            cur.execute(
                                "INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price,is_preferred) VALUES (%s,%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price,is_preferred=EXCLUDED.is_preferred",
                                (material_id,sid,pending["price"],is_primary)
                            )
                        if pending.get("primary_supplier_id"):
                            cur.execute("UPDATE reklet.materials SET supplier_id=%s WHERE id=%s",(pending["primary_supplier_id"],material_id))
                        elif pending["supplier_ids"]:
                            cur.execute("UPDATE reklet.materials SET supplier_id=%s WHERE id=%s",(pending["supplier_ids"][0],material_id))
                        conn.commit()
                    except Exception:
                        conn.rollback(); raise
                    finally:
                        cur.close()
                    st.session_state.pop("pending_material_create_v3",None)
                    st.success(f"Материал «{pending['name']}» добавлен в перечень материалов в категорию «{pending['category']}" + ("." if not pending['category'].endswith(".") else ""))
                    st.rerun()

        with st.expander("Категории материалов", expanded=False):
            category_action=st.selectbox("Операция",["Перечень","Добавить","Корректировка","Удаление"],key="material_category_action_v3")
            categories_now=get_material_categories()
            if category_action=="Перечень":
                cv=categories_now.rename(columns={"id":"ID","name":"Категория"})
                st.dataframe(cv,width="stretch",hide_index=True)
                render_print_html("Категории материалов",cv,"print_material_categories_v3")
            elif category_action=="Добавить":
                with st.form("add_material_category_v3"):
                    newc=st.text_input("Название категории")
                    if st.form_submit_button("Добавить категорию"):
                        if not newc.strip(): st.warning("Укажите название категории.")
                        else:
                            run_query("INSERT INTO reklet.material_categories(name) VALUES (%s)",(newc.strip(),)); st.success("Категория добавлена."); st.rerun()
            elif category_action=="Корректировка":
                if categories_now.empty: st.info("Категорий нет.")
                else:
                    cmap={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in categories_now.iterrows()}
                    label=st.selectbox("Категория",list(cmap.keys()),key="edit_material_category_v3")
                    cid=cmap[label]; current=str(categories_now[categories_now["id"]==cid].iloc[0]["name"])
                    newc=st.text_input("Новое название",value=current,key="edit_material_category_name_v3")
                    if st.button("Выполнить",key="execute_material_category_edit_v3",use_container_width=True):
                        if not newc.strip(): st.warning("Название не может быть пустым.")
                        elif newc.strip()==current: st.info("Изменений нет.")
                        else: st.session_state["pending_material_category_edit_v3"]={"id":cid,"old":current,"new":newc.strip()}
                    pcat=st.session_state.get("pending_material_category_edit_v3")
                    if pcat and pcat["id"]==cid:
                        st.dataframe(pd.DataFrame([{"Категория":"Категория","Было":pcat["old"],"Станет":pcat["new"]}]),width="stretch",hide_index=True)
                        c1,c2=st.columns(2)
                        with c1: ok=st.button("Подтвердить",key="confirm_material_category_edit_v3",type="primary",use_container_width=True)
                        with c2: no=st.button("Отменить",key="cancel_material_category_edit_v3",use_container_width=True)
                        if no: st.session_state.pop("pending_material_category_edit_v3",None); st.rerun()
                        if ok: run_query("UPDATE reklet.material_categories SET name=%s WHERE id=%s",(pcat["new"],pcat["id"])); st.session_state.pop("pending_material_category_edit_v3",None); st.success("Категория изменена."); st.rerun()
            else:
                if categories_now.empty: st.info("Категорий нет.")
                else:
                    cmap={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in categories_now.iterrows()}
                    label=st.selectbox("Категория",list(cmap.keys()),key="delete_material_category_v3")
                    cid=cmap[label]
                    st.warning("Удаление категории необратимо. Категория, используемая материалами, не может быть удалена.")
                    confirm=st.checkbox("Я подтверждаю удаление",key="confirm_delete_material_category_v3")
                    if st.button("Удалить",key="delete_material_category_v3_button",disabled=not confirm):
                        refs=run_query("SELECT COUNT(*) AS n FROM reklet.materials WHERE category_id=%s",(cid,),fetch=True)
                        if int(refs.iloc[0]["n"])>0: st.error("Удаление невозможно: категория используется материалами.")
                        else: run_query("DELETE FROM reklet.material_categories WHERE id=%s",(cid,)); st.success("Категория удалена."); st.rerun()

        with st.expander("Удалить брак", expanded=False):
            st.subheader("Удалить брак")
            cat_options=["Все категории","Без категории"]+(categories["name"].astype(str).tolist() if not categories.empty else [])
            cat=st.selectbox("Категория материала",cat_options,key="waste_material_category_v3")
            wf=materials.copy()
            if cat=="Без категории": wf=wf[wf["category_id"].isna()].copy()
            elif cat!="Все категории": wf=wf[wf["category_name"].fillna("").astype(str).eq(cat)].copy()
            wip_all=get_material_stock_and_wip()
            wip_map={safe_int(r["id"]):safe_float(r["production_wip"]) for _,r in wip_all.iterrows()} if not wip_all.empty else {}
            wrows=wf[["id","name","stock_quantity"]].copy(); wrows["production_wip"]=wrows["id"].map(wip_map).fillna(0.0)
            wrows["Удалить со склада"]=0.0; wrows["Удалить из излишков производства"]=0.0; wrows.insert(0,"Выбрать",False)
            wrows.columns=["Выбрать","ID","Материал","Остаток на складе","Остатки на производстве","Удалить со склада","Удалить из излишков производства"]
            edited_w=st.data_editor(wrows,key="waste_editor_v3",width="stretch",hide_index=True,column_config={
                "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                "ID":st.column_config.NumberColumn("ID",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),
                "Остаток на складе":st.column_config.NumberColumn("🔵 Остаток на складе",disabled=True,format="%.4f"),
                "Остатки на производстве":st.column_config.NumberColumn("🔵 Остатки на производстве",disabled=True,format="%.4f"),
                "Удалить со склада":st.column_config.NumberColumn("🟢 Удалить со склада",min_value=0.0,step=0.001,format="%.4f"),
                "Удалить из излишков производства":st.column_config.NumberColumn("🟢 Удалить из излишков производства",min_value=0.0,step=0.001,format="%.4f")},disabled=["ID","Материал","Остаток на складе","Остатки на производстве"])
            if st.button("Выполнить",key="execute_waste_v3",use_container_width=True):
                selected=edited_w[edited_w["Выбрать"].fillna(False)&((edited_w["Удалить со склада"].fillna(0)>0)|(edited_w["Удалить из излишков производства"].fillna(0)>0))].copy(); errors=[]; preview=[]
                for _,r in selected.iterrows():
                    sid=safe_int(r["ID"]); ws=safe_float(r["Удалить со склада"]); wp=safe_float(r["Удалить из излишков производства"]); stock=safe_float(r["Остаток на складе"]); wip=safe_float(r["Остатки на производстве"])
                    if ws>stock+1e-9: errors.append(f"{r['Материал']}: на складе только {stock:.4f}.")
                    if wp>wip+1e-9: errors.append(f"{r['Материал']}: на производстве только {wip:.4f}.")
                    if ws>0: preview.append({"Материал":r["Материал"],"Источник":"Склад","Количество":ws})
                    if wp>0: preview.append({"Материал":r["Материал"],"Источник":"Производство","Количество":wp})
                if selected.empty: st.info("Выберите материал и количество для списания.")
                elif errors: st.error("Операция не подготовлена:\n"+"\n".join(errors))
                else: st.session_state["pending_waste_v3"]={"rows":preview}
            pending_w=st.session_state.get("pending_waste_v3")
            if pending_w:
                st.warning("Вы действительно хотите выбросить эти материалы?")
                st.dataframe(pd.DataFrame(pending_w["rows"]),width="stretch",hide_index=True)
                c1,c2=st.columns(2)
                with c1: ok=st.button("Выполнить",key="confirm_waste_v3",type="primary",use_container_width=True)
                with c2: no=st.button("Отменить",key="cancel_waste_v3",use_container_width=True)
                if no: st.session_state.pop("pending_waste_v3",None); st.rerun()
                if ok:
                    statements=[]
                    for row in pending_w["rows"]:
                        mid=next((safe_int(x["ID"]) for _,x in edited_w.iterrows() if str(x["Материал"])==str(row["Материал"])),None)
                        if mid is None: continue
                        qty=safe_float(row["Количество"]); source="stock" if row["Источник"]=="Склад" else "production"
                        price_df=run_query("SELECT COALESCE(cost_per_unit,0) AS cost FROM reklet.materials WHERE id=%s",(mid,),fetch=True); unit_cost=safe_float(price_df.iloc[0]["cost"]) if not price_df.empty else 0.0
                        if source=="stock":
                            statements.append(("UPDATE reklet.materials SET stock_quantity=GREATEST(COALESCE(stock_quantity,0)-%s,0) WHERE id=%s",(qty,mid)))
                            statements.append(("INSERT INTO reklet.material_waste_transactions(material_id,object_id,source_type,quantity,unit_cost_snapshot,reason) VALUES (%s,NULL,'stock',%s,%s,'Брак / выброшено со склада')",(mid,qty,unit_cost)))
                        else:
                            alloc=get_production_wip_for_material(mid); remaining=qty
                            for _,a in alloc.iterrows():
                                if remaining<=1e-9: break
                                take=min(remaining,safe_float(a["wip_quantity"]));
                                if take>1e-9:
                                    statements.append(("INSERT INTO reklet.material_waste_transactions(material_id,object_id,source_type,quantity,unit_cost_snapshot,reason) VALUES (%s,%s,'production',%s,%s,'Брак / излишек выброшен с производства')",(mid,safe_int(a["object_id"]),take,unit_cost)))
                                    remaining-=take
                    run_transaction(statements); st.session_state.pop("pending_waste_v3",None); st.session_state.pop("waste_editor_v3",None); st.success("Брак списан. Операции сохранены в истории."); st.rerun()

    elif active_material_section == "planning":
        st.subheader("Необходимые материалы для объекта")
        object_id, object_row = warehouse_select_object("material_planning_v4")
        if object_id is not None:
            planning=get_object_material_planning(object_id)
            if planning.empty:
                st.info("Для выбранного объекта нет потребности в материалах по спецификациям.")
            else:
                view=planning[["material_name","unit_name","base_required_quantity","waste_quantity","required_quantity","issued_quantity","work_in_process_quantity","remaining_need","stock_quantity","ordered_outstanding","need_to_buy"]].copy()
                view.columns=["Материал","Единица","По спецификации","Обрез","Требуется","Выдано в производство","На производстве","Осталось потребно","На складе","Ожидается","Нужно купить"]
                st.dataframe(view,width="stretch",hide_index=True)
                render_print_html(f"Необходимые материалы — {object_row['object_name']}",view,f"print_material_planning_v4_{object_id}",subtitle=f"Заказчик: {object_row['client_name']}")
                st.markdown("---")
                st.subheader("Передать материал в производство")
                action_df=planning[["material_id","material_name","unit_name","remaining_need","stock_quantity","work_in_process_quantity"]].copy()
                action_df.insert(0,"Выбрать",False); action_df["Выдать"]=0.0
                action_df.columns=["Выбрать","ID","Материал","Единица","Осталось потребно","На складе","На производстве","Выдать"]
                with st.form(f"material_direct_issue_form_v4_{object_id}",clear_on_submit=False):
                    edited=st.data_editor(action_df,key=f"material_direct_issue_editor_v4_{object_id}",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID":st.column_config.NumberColumn("ID",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Единица":st.column_config.TextColumn("Единица",disabled=True),"Осталось потребно":st.column_config.NumberColumn("Осталось потребно",disabled=True,format="%.4f"),"На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.4f"),"На производстве":st.column_config.NumberColumn("На производстве",disabled=True,format="%.4f"),"Выдать":st.column_config.NumberColumn("Выдать",min_value=0.0,step=0.001,format="%.4f")},disabled=["ID","Материал","Единица","Осталось потребно","На складе","На производстве"])
                    execute=st.form_submit_button("Выполнить выдачу в производство",use_container_width=True)
                if execute:
                    selected=edited[edited["Выбрать"].fillna(False)&(edited["Выдать"].fillna(0)>0)].copy(); errors=[]; statements=[]; totals={}
                    for _,row in selected.iterrows():
                        mid=safe_int(row["ID"]); qty=safe_float(row["Выдать"]); stock=safe_float(row["На складе"]); totals[mid]=totals.get(mid,0.0)+qty
                        if qty>stock+1e-9: errors.append(f"{row['Материал']}: на складе только {stock:.4f}.")
                    stock_check={safe_int(r["material_id"]):safe_float(r["stock_quantity"]) for _,r in planning.iterrows()}
                    for mid,total in totals.items():
                        if total>stock_check.get(mid,0.0)+1e-9: errors.append(f"Материал ID {mid}: суммарная выдача {total:.4f} больше остатка {stock_check.get(mid,0.0):.4f}.")
                    if selected.empty: st.info("Выберите материал и количество.")
                    elif errors: st.error("Выдача не выполнена:\n"+"\n".join(errors))
                    else:
                        for _,row in selected.iterrows():
                            mid=safe_int(row["ID"]); qty=safe_float(row["Выдать"])
                            statements += [("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",(mid,object_id,qty)),("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(qty,mid))]
                        run_transaction(statements); st.success("Материалы выданы в производство."); st.session_state.pop(f"material_direct_issue_editor_v4_{object_id}",None); st.rerun()

    elif active_material_section == "purchase":
        st.subheader("Закупка материалов")
        clients=get_clients()
        objects=get_objects().sort_values("id",ascending=False).copy()

        client_options=["Все заказчики"]+([f"{int(r['id'])} — {r['name']}" for _,r in clients.iterrows()] if not clients.empty else [])
        selected_client_label=st.selectbox("Заказчик",client_options,key="purchase_scope_client_v4")
        scope_client_id=None if selected_client_label=="Все заказчики" else int(selected_client_label.split(" — ")[0])

        if scope_client_id is None:
            object_options=["Все объекты"]
        else:
            co=objects[objects["client_id"].eq(scope_client_id)].copy()
            object_options=["Все объекты"]+[f"{int(r['id'])} — {r['object_name']}" for _,r in co.iterrows()]
        selected_object_label=st.selectbox("Объект",object_options,key="purchase_scope_object_v4")
        scope_object_id=None if selected_object_label=="Все объекты" else int(selected_object_label.split(" — ")[0])

        need=get_purchase_scope_needs(scope_client_id,scope_object_id)
        if need.empty:
            st.success("Для выбранного отбора закупать нечего.")
        else:
            suppliers=get_suppliers()
            default_supplier_id=get_default_supplier_id()
            supplier_labels={int(r["id"]):f"{int(r['id'])} — {r['name']}" for _,r in suppliers.iterrows()}
            if default_supplier_id not in supplier_labels:
                suppliers=get_suppliers()
                supplier_labels={int(r["id"]):f"{int(r['id'])} — {r['name']}" for _,r in suppliers.iterrows()}
            supplier_options=list(supplier_labels.values())

            default_by_material={}
            for _,n in need.iterrows():
                mid=safe_int(n["material_id"])
                link=run_query(
                    """
                    SELECT COALESCE(
                        (SELECT ms.supplier_id
                         FROM reklet.material_suppliers ms
                         WHERE ms.material_id=%s
                         ORDER BY ms.is_preferred DESC,ms.id
                         LIMIT 1),
                        m.supplier_id
                    ) AS supplier_id
                    FROM reklet.materials m
                    WHERE m.id=%s
                    """,
                    (mid,mid),fetch=True
                )
                sid=safe_int(link.iloc[0]["supplier_id"]) if not link.empty and pd.notna(link.iloc[0]["supplier_id"]) else default_supplier_id
                default_by_material[mid]=sid

            pdf=need.copy()
            pdf.insert(0,"Выбрать",False)
            pdf["Поставщик"]=[supplier_labels.get(default_by_material.get(safe_int(mid)),"") for mid in pdf["material_id"]]
            pdf["Купить"]=pdf["need_to_buy"]
            pdf=pdf[["Выбрать","material_id","material_name","remaining_need","stock_quantity","selected_ordered","need_to_buy","Поставщик","Купить"]]
            pdf.columns=["Выбрать","ID","Материал","Потребность","Наличие на складе","Ожидается","Нужно купить","Поставщик","Купить"]

            with st.form("purchase_form_v4",clear_on_submit=False):
                edited=st.data_editor(
                    pdf,key="purchase_editor_v4",width="stretch",hide_index=True,
                    column_config={
                        "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                        "ID":st.column_config.NumberColumn("ID",disabled=True),
                        "Материал":st.column_config.TextColumn("Материал",disabled=True),
                        "Потребность":st.column_config.NumberColumn("Потребность",disabled=True,format="%.4f"),
                        "Наличие на складе":st.column_config.NumberColumn("Наличие на складе",disabled=True,format="%.4f"),
                        "Ожидается":st.column_config.NumberColumn("Ожидается",disabled=True,format="%.4f"),
                        "Нужно купить":st.column_config.NumberColumn("Нужно купить",disabled=True,format="%.4f"),
                        "Поставщик":st.column_config.SelectboxColumn("Поставщик",options=supplier_options),
                        "Купить":st.column_config.NumberColumn("Купить",min_value=0.0,step=0.001,format="%.4f")
                    },
                    disabled=["ID","Материал","Потребность","Наличие на складе","Ожидается","Нужно купить"]
                )
                create=st.form_submit_button("Сформировать закупку",use_container_width=True)

            pending_key="purchase_pending_v4"
            if create:
                selected=edited[edited["Выбрать"].fillna(False)&(pd.to_numeric(edited["Купить"],errors="coerce").fillna(0)>0)].copy()
                lines=[]; warnings=[]
                for _,r in selected.iterrows():
                    supplier_label=str(r["Поставщик"] or "")
                    sid=next((x for x,lbl in supplier_labels.items() if lbl==supplier_label),default_supplier_id)
                    qty=safe_float(r["Купить"])
                    needqty=safe_float(r["Нужно купить"])
                    if qty<needqty-1e-9:
                        warnings.append(f"{r['Материал']}: покупка {qty:.4f}, рассчитано {needqty:.4f}; потребность останется незакрытой.")
                    lines.append({
                        "material_id":safe_int(r["ID"]),
                        "material_name":str(r["Материал"]),
                        "supplier_id":sid,
                        "supplier_name":supplier_label or supplier_labels.get(sid,""),
                        "quantity":qty,
                        "need_to_buy":needqty
                    })
                if selected.empty:
                    st.warning("Выберите материал и укажите количество.")
                else:
                    st.session_state[pending_key]={
                        "lines":lines,
                        "client_id":scope_client_id,
                        "object_id":scope_object_id,
                        "warnings":warnings,
                        "scope":"Все объекты" if scope_object_id is None else selected_object_label
                    }

            pending=st.session_state.get(pending_key)
            if pending:
                st.subheader("Подтверждение закупки")
                if pending["warnings"]:
                    st.warning("\n".join(pending["warnings"]))
                st.dataframe(
                    pd.DataFrame([
                        {"Материал":x["material_name"],"Поставщик":x["supplier_name"],"Количество":x["quantity"]}
                        for x in pending["lines"]
                    ]),width="stretch",hide_index=True
                )
                c1,c2=st.columns(2)
                with c1:
                    ok=st.button("Подтвердить закупку",key="confirm_purchase_v4",type="primary",use_container_width=True)
                with c2:
                    no=st.button("Отменить",key="cancel_purchase_v4",use_container_width=True)
                if no:
                    st.session_state.pop(pending_key,None)
                    st.rerun()
                if ok:
                    statements=[]
                    grouped={}
                    for line in pending["lines"]:
                        grouped.setdefault(line["supplier_id"],[]).append(line)
                    for sid,lines in grouped.items():
                        value_sql=[]
                        params=[sid,f"Закупка материалов ({pending['scope']})"]
                        for line in lines:
                            price_df=run_query(
                                "SELECT COALESCE(ms.purchase_price,m.cost_per_unit,0) AS price FROM reklet.materials m LEFT JOIN reklet.material_suppliers ms ON ms.material_id=m.id AND ms.supplier_id=%s WHERE m.id=%s ORDER BY ms.id DESC LIMIT 1",
                                (sid,line["material_id"]),fetch=True
                            )
                            price=safe_float(price_df.iloc[0]["price"]) if not price_df.empty else 0.0
                            value_sql.append("(%s,%s,%s,%s)")
                            params.extend([pending["object_id"],line["material_id"],line["quantity"],price])
                        statements.append((
                            "WITH new_po AS (INSERT INTO reklet.purchase_orders(supplier_id,status,notes) VALUES (%s,'ordered',%s) RETURNING id) "
                            "INSERT INTO reklet.purchase_order_items(purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price) "
                            "SELECT new_po.id,v.object_id,v.material_id,v.quantity_ordered,0,v.unit_price FROM new_po CROSS JOIN (VALUES "
                            + ",".join(value_sql) + ") AS v(object_id,material_id,quantity_ordered,unit_price)",
                            tuple(params)
                        ))
                        for line in lines:
                            price_df=run_query(
                                "SELECT COALESCE(ms.purchase_price,m.cost_per_unit,0) AS price FROM reklet.materials m LEFT JOIN reklet.material_suppliers ms ON ms.material_id=m.id AND ms.supplier_id=%s WHERE m.id=%s ORDER BY ms.id DESC LIMIT 1",
                                (sid,line["material_id"]),fetch=True
                            )
                            price=safe_float(price_df.iloc[0]["price"]) if not price_df.empty else 0.0
                            statements.append((
                                "INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price",
                                (line["material_id"],sid,price)
                            ))
                    run_transaction(statements)
                    st.session_state.pop(pending_key,None)
                    st.session_state.pop("purchase_editor_v4",None)
                    st.success("Закупка сформирована. Материалы появятся на складе после прихода.")
                    st.rerun()

            history=run_query(
                """
                SELECT po.id AS "№ закупки",po.order_date AS "Дата",
                       CASE po.status WHEN 'ordered' THEN 'Заказан' WHEN 'partial' THEN 'Частично получен'
                            WHEN 'received' THEN 'Получен' WHEN 'cancelled' THEN 'Отменён' ELSE po.status END AS "Статус",
                       s.name AS "Поставщик",COALESCE(c.name,'') AS "Заказчик",
                       COALESCE(o.object_name,'Все объекты') AS "Объект",m.name AS "Материал",
                       poi.quantity_ordered AS "Заказано",poi.quantity_received AS "Получено",
                       GREATEST(poi.quantity_ordered-poi.quantity_received,0) AS "Осталось",poi.unit_price AS "Цена"
                FROM reklet.purchase_order_items poi
                JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
                JOIN reklet.suppliers s ON s.id=po.supplier_id
                LEFT JOIN reklet.objects o ON o.id=poi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                JOIN reklet.materials m ON m.id=poi.material_id
                ORDER BY po.id DESC,m.name LIMIT 500
                """,fetch=True)
            if not history.empty:
                st.markdown("---")
                st.subheader("История закупок")
                st.dataframe(history,width="stretch",hide_index=True)
                render_print_html("История закупок",history,"print_purchase_history_v4")

    elif active_material_section == "receipt":
        st.subheader("Приход материалов")
        openp=run_query(
            """
            SELECT poi.id AS purchase_item_id,po.id AS purchase_order_id,
                   s.id AS supplier_id,s.name AS supplier_name,
                   poi.object_id,o.object_name,c.name AS client_name,
                   m.id AS material_id,m.name AS material_name,u.name AS unit_name,
                   poi.quantity_ordered,poi.quantity_received,
                   GREATEST(poi.quantity_ordered-poi.quantity_received,0) AS remaining_quantity,
                   poi.unit_price,COALESCE(m.stock_quantity,0) AS stock_quantity
            FROM reklet.purchase_order_items poi
            JOIN reklet.purchase_orders po ON po.id=poi.purchase_order_id
            JOIN reklet.suppliers s ON s.id=po.supplier_id
            LEFT JOIN reklet.objects o ON o.id=poi.object_id
            LEFT JOIN reklet.clients c ON c.id=o.client_id
            JOIN reklet.materials m ON m.id=poi.material_id
            LEFT JOIN reklet.units u ON u.id=m.unit_id
            WHERE po.status<>'cancelled' AND poi.quantity_received<poi.quantity_ordered
            ORDER BY po.id DESC,COALESCE(o.object_name,'Все объекты'),m.name LIMIT 1000
            """,fetch=True)
        if openp.empty:
            st.info("Ожидающих приходов нет.")
        else:
            edf=openp[["purchase_item_id","purchase_order_id","supplier_name","client_name","object_name","material_name","unit_name","stock_quantity","quantity_ordered","quantity_received","remaining_quantity","unit_price"]].copy()
            edf.insert(0,"Выбрать",False)
            edf["Принять"]=0.0
            edf.columns=["Выбрать","ID позиции","№ закупки","Поставщик","Заказчик","Объект","Материал","Единица","Наличие на складе","Заказано","Получено","Осталось","Цена","Принять"]
            with st.form("purchase_receipt_form_v5",clear_on_submit=False):
                edited=st.data_editor(
                    edf,key="purchase_receipt_editor_v5",width="stretch",hide_index=True,
                    column_config={
                        "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                        "ID позиции":st.column_config.NumberColumn("ID позиции",disabled=True),
                        "№ закупки":st.column_config.NumberColumn("№ закупки",disabled=True),
                        "Поставщик":st.column_config.TextColumn("Поставщик",disabled=True),
                        "Заказчик":st.column_config.TextColumn("Заказчик",disabled=True),
                        "Объект":st.column_config.TextColumn("Объект",disabled=True),
                        "Материал":st.column_config.TextColumn("Материал",disabled=True),
                        "Единица":st.column_config.TextColumn("Единица",disabled=True),
                        "Наличие на складе":st.column_config.NumberColumn("Наличие на складе",disabled=True,format="%.4f"),
                        "Заказано":st.column_config.NumberColumn("Заказано",disabled=True,format="%.4f"),
                        "Получено":st.column_config.NumberColumn("Получено",disabled=True,format="%.4f"),
                        "Осталось":st.column_config.NumberColumn("Осталось",disabled=True,format="%.4f"),
                        "Цена":st.column_config.NumberColumn("Цена",disabled=True,format="%.2f"),
                        "Принять":st.column_config.NumberColumn("Принять",min_value=0.0,step=0.001,format="%.4f")
                    },
                    disabled=["ID позиции","№ закупки","Поставщик","Заказчик","Объект","Материал","Единица","Наличие на складе","Заказано","Получено","Осталось","Цена"]
                )
                execute=st.form_submit_button("Выполнить приход",use_container_width=True)
            if execute:
                selected=edited[edited["Выбрать"].fillna(False)&(pd.to_numeric(edited["Принять"],errors="coerce").fillna(0)>0)].copy()
                errors=[]; preview=[]
                for idx,row in selected.iterrows():
                    raw=openp.loc[int(idx)]
                    qty=safe_float(row["Принять"]); rem=safe_float(row["Осталось"])
                    if qty>rem+1e-9:
                        errors.append(f"{row['Материал']}: можно принять максимум {rem:.4f}.")
                    if qty>0:
                        preview.append({
                            "ID позиции":safe_int(raw["purchase_item_id"]),
                            "Материал":str(raw["material_name"]),
                            "Поставщик":str(raw["supplier_name"]),
                            "Объект":str(raw["object_name"] or "Все объекты"),
                            "Количество":qty,
                            "Цена":safe_float(raw["unit_price"]),
                            "Наличие до":safe_float(raw["stock_quantity"]),
                            "Наличие после":safe_float(raw["stock_quantity"])+qty
                        })
                if selected.empty:
                    st.warning("Выберите позиции и количество принятого материала.")
                elif errors:
                    st.error("Приход не подготовлен:\n"+"\n".join(errors))
                else:
                    st.session_state["pending_receipt_v5"]={"rows":preview}
            pending=st.session_state.get("pending_receipt_v5")
            if pending:
                st.subheader("Подтверждение прихода")
                st.dataframe(pd.DataFrame(pending["rows"]),width="stretch",hide_index=True)
                c1,c2=st.columns(2)
                with c1:
                    ok=st.button("Подтвердить приход",key="confirm_receipt_v5",type="primary",use_container_width=True)
                with c2:
                    no=st.button("Отменить",key="cancel_receipt_v5",use_container_width=True)
                if no:
                    st.session_state.pop("pending_receipt_v5",None)
                    st.rerun()
                if ok:
                    statements=[]
                    poids=set()
                    for row in pending["rows"]:
                        pid=safe_int(row["ID позиции"])
                        raw=openp[openp["purchase_item_id"].eq(pid)].iloc[0]
                        mid=safe_int(raw["material_id"]); qty=safe_float(row["Количество"])
                        oid=None if pd.isna(raw["object_id"]) else safe_int(raw["object_id"])
                        sid=safe_int(raw["supplier_id"]); price=safe_float(raw["unit_price"])
                        poids.add(safe_int(raw["purchase_order_id"]))
                        statements.extend([
                            ("INSERT INTO reklet.material_transactions(material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')",(mid,sid,oid,qty,price)),
                            ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(qty,mid)),
                            ("UPDATE reklet.purchase_order_items SET quantity_received=quantity_received+%s WHERE id=%s",(qty,pid)),
                            ("INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price",(mid,sid,price))
                        ])
                    for poid in sorted(poids):
                        statements.append((
                            "UPDATE reklet.purchase_orders po SET status=CASE WHEN NOT EXISTS(SELECT 1 FROM reklet.purchase_order_items poi WHERE poi.purchase_order_id=po.id AND poi.quantity_received<poi.quantity_ordered) THEN 'received' WHEN EXISTS(SELECT 1 FROM reklet.purchase_order_items poi WHERE poi.purchase_order_id=po.id AND poi.quantity_received>0) THEN 'partial' ELSE 'ordered' END WHERE po.id=%s",
                            (poid,)
                        ))
                    run_transaction(statements)
                    st.session_state.pop("pending_receipt_v5",None)
                    st.session_state.pop("purchase_receipt_editor_v5",None)
                    st.success("Приход выполнен и подтверждён. Материал отражён на складе и в истории.")
                    st.rerun()

        st.markdown("---")
        st.subheader("История прихода материалов")
        history=run_query(
            """
            SELECT mt.created_at AS "Дата",s.name AS "Поставщик",COALESCE(c.name,'') AS "Заказчик",
                   COALESCE(o.object_name,'Без объекта') AS "Объект",m.name AS "Материал",u.name AS "Единица",
                   mt.quantity AS "Количество",mt.unit_price AS "Цена",mt.quantity*COALESCE(mt.unit_price,0) AS "Сумма"
            FROM reklet.material_transactions mt
            LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id
            LEFT JOIN reklet.objects o ON o.id=mt.object_id
            LEFT JOIN reklet.clients c ON c.id=o.client_id
            JOIN reklet.materials m ON m.id=mt.material_id
            LEFT JOIN reklet.units u ON u.id=m.unit_id
            WHERE mt.operation_type='purchase' AND mt.transaction_type='IN'
            ORDER BY mt.created_at DESC LIMIT 1000
            """,fetch=True)
        if history.empty:
            st.info("История прихода пока пуста.")
        else:
            st.dataframe(history,width="stretch",hide_index=True)
            render_print_html("История прихода материалов",history,"print_material_receipt_history_v5")

    elif active_material_section == "issue":
        st.subheader("Выдача материалов в производство")
        clients=get_clients(); objects=get_objects().sort_values("id",ascending=False).copy()
        client_options=["Все заказчики"]+([f"{int(r['id'])} — {r['name']}" for _,r in clients.iterrows()] if not clients.empty else [])
        selected_client=st.selectbox("Заказчик",client_options,key="issue_scope_client_v4")
        cid=None if selected_client=="Все заказчики" else int(selected_client.split(" — ")[0])
        if cid is None:
            object_options=["Все объекты"]
        else:
            co=objects[objects["client_id"].eq(cid)].copy()
            object_options=["Все объекты"]+[f"{int(r['id'])} — {r['object_name']}" for _,r in co.iterrows()]
        selected_object=st.selectbox("Объект",object_options,key="issue_scope_object_v4")
        oid=None if selected_object=="Все объекты" else int(selected_object.split(" — ")[0])

        issue=issue_rows_for_scope(cid,oid)
        if issue.empty:
            st.info("Для выбранного отбора нет материалов.")
        else:
            issue_df=issue[[
                "object_id","client_name","object_name","material_id","material_name","unit_name",
                "stock_quantity","required_quantity","issued_quantity","work_in_process_quantity"
            ]].copy()
            issue_df.insert(0,"Выбрать",False)
            issue_df["Осталось потребно"]=(issue_df["required_quantity"]-issue_df["issued_quantity"]).clip(lower=0)
            issue_df["Можно выдать"]=issue_df["stock_quantity"].clip(lower=0)
            issue_df["Выдать"]=0.0
            issue_df=issue_df[[
                "Выбрать","object_id","client_name","object_name","material_id","material_name","unit_name",
                "stock_quantity","required_quantity","issued_quantity","work_in_process_quantity","Осталось потребно","Можно выдать","Выдать"
            ]]
            issue_df.columns=[
                "Выбрать","Объект ID","Заказчик","Объект","Материал ID","Материал","Единица",
                "На складе","Потребность","Выдано","На производстве","Осталось потребно","Можно выдать","Выдать"
            ]
            with st.form("issue_materials_form_v4",clear_on_submit=False):
                edited=st.data_editor(
                    issue_df,key="issue_materials_editor_v4",width="stretch",hide_index=True,
                    column_config={
                        "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                        "Объект ID":st.column_config.NumberColumn("Объект ID",disabled=True),
                        "Заказчик":st.column_config.TextColumn("Заказчик",disabled=True),
                        "Объект":st.column_config.TextColumn("Объект",disabled=True),
                        "Материал ID":st.column_config.NumberColumn("Материал ID",disabled=True),
                        "Материал":st.column_config.TextColumn("Материал",disabled=True),
                        "Единица":st.column_config.TextColumn("Единица",disabled=True),
                        "На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.4f"),
                        "Потребность":st.column_config.NumberColumn("Потребность",disabled=True,format="%.4f"),
                        "Выдано":st.column_config.NumberColumn("Выдано",disabled=True,format="%.4f"),
                        "На производстве":st.column_config.NumberColumn("На производстве",disabled=True,format="%.4f"),
                        "Осталось потребно":st.column_config.NumberColumn("Осталось потребно",disabled=True,format="%.4f"),
                        "Можно выдать":st.column_config.NumberColumn("Можно выдать",disabled=True,format="%.4f"),
                        "Выдать":st.column_config.NumberColumn("Выдать",min_value=0.0,step=0.001,format="%.4f")
                    },
                    disabled=["Объект ID","Заказчик","Объект","Материал ID","Материал","Единица","На складе","Потребность","Выдано","На производстве","Осталось потребно","Можно выдать"]
                )
                execute=st.form_submit_button("Выполнить выдачу в производство",use_container_width=True)
            if execute:
                selected=edited[edited["Выбрать"].fillna(False)&(pd.to_numeric(edited["Выдать"],errors="coerce").fillna(0)>0)].copy()
                errors=[]; statements=[]; totals={}
                stock_by_material={safe_int(r["material_id"]):safe_float(r["stock_quantity"]) for _,r in issue.iterrows()}
                for _,r in selected.iterrows():
                    mid=safe_int(r["Материал ID"]); qty=safe_float(r["Выдать"]); stock=safe_float(r["На складе"])
                    totals[mid]=totals.get(mid,0.0)+qty
                    if qty>stock+1e-9:
                        errors.append(f"{r['Материал']}: на складе только {stock:.4f}.")
                for mid,total in totals.items():
                    if total>stock_by_material.get(mid,0.0)+1e-9:
                        errors.append(f"Материал ID {mid}: суммарная выдача {total:.4f} больше остатка {stock_by_material.get(mid,0.0):.4f}.")
                if selected.empty:
                    st.info("Выберите материал и количество.")
                elif errors:
                    st.error("Выдача не выполнена:\n"+"\n".join(errors))
                else:
                    for _,r in selected.iterrows():
                        mid=safe_int(r["Материал ID"]); qty=safe_float(r["Выдать"]); oid2=safe_int(r["Объект ID"])
                        statements.extend([
                            ("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",(mid,oid2,qty)),
                            ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(qty,mid))
                        ])
                    run_transaction(statements)
                    st.session_state.pop("issue_materials_editor_v4",None)
                    st.success("Материалы выданы в производство.")
                    st.rerun()

    elif active_material_section == "production_requests":
        st.subheader("Заказы материала с производства")
        requests=get_open_production_requests()
        if requests.empty:
            st.info("Открытых заказов материала с производства нет.")
        else:
            rv=requests.rename(columns={"id":"ID заявки","client_name":"Заказчик","object_name":"Объект","item_name":"Изделие","material_name":"Материал","unit_name":"Единица","quantity_requested":"Необходимо производству","quantity_supplied":"Уже передано","remaining_quantity":"Осталось","status":"Статус","created_at":"Дата"})[["ID заявки","Заказчик","Объект","Изделие","Материал","Единица","Необходимо производству","Уже передано","Осталось","Статус","Дата"]]
            st.dataframe(rv,width="stretch",hide_index=True)
            req_map={f"{int(r['id'])} — {r['object_name']} — {r['item_name']} — {r['material_name']}":int(r['id']) for _,r in requests.iterrows()}
            sel_label=st.selectbox("Заявка",list(req_map.keys()),key="production_request_select_v3")
            request_id=req_map[sel_label]
            selected_req=requests[requests["id"]==request_id].iloc[0]
            group=requests[(requests["object_item_id"]==selected_req["object_item_id"]) & (requests["status"]!="completed")].copy()
            suppliers=get_suppliers(); slabels={int(r["id"]):f"{int(r['id'])} — {r['name']}" for _,r in suppliers.iterrows()}; soptions=list(slabels.values())
            rows=[]
            for _,rr in group.iterrows():
                siddf=run_query("SELECT supplier_id FROM reklet.material_suppliers WHERE material_id=%s ORDER BY is_preferred DESC,id LIMIT 1",(safe_int(rr["material_id"]),),fetch=True); sid=safe_int(siddf.iloc[0]["supplier_id"]) if not siddf.empty else get_default_supplier_id();
                rows.append({"Выбрать":False,"ID заявки":safe_int(rr["id"]),"Материал":rr["material_name"],"Единица":rr["unit_name"],"Необходимо производству":safe_float(rr["remaining_quantity"]),"Свободно на складе":0.0,"Поставщик":slabels.get(sid,""),"Заказать количество":0.0,"material_id":safe_int(rr["material_id"]),"object_id":safe_int(rr["object_id"])})
            order_df=pd.DataFrame(rows)
            for _,rr in order_df.iterrows():
                pass
            # Refresh free stock for display.
            for idx,rr in order_df.iterrows():
                mid=safe_int(rr["material_id"]); stf=run_query("SELECT COALESCE(stock_quantity,0) AS stock_quantity FROM reklet.materials WHERE id=%s",(mid,),fetch=True); order_df.at[idx,"Свободно на складе"]=max(safe_float(stf.iloc[0]["stock_quantity"]) if not stf.empty else 0.0,0.0); order_df.at[idx,"Заказать количество"]=max(safe_float(rr["Необходимо производству"])-order_df.at[idx,"Свободно на складе"],0.0)
            editor=order_df[["Выбрать","ID заявки","Материал","Единица","Необходимо производству","Свободно на складе","Поставщик","Заказать количество"]].copy()
            with st.form("production_request_purchase_form_v3",clear_on_submit=False):
                edited=st.data_editor(editor,key="production_request_purchase_editor_v3",width="stretch",hide_index=True,column_config={"Выбрать":st.column_config.CheckboxColumn("Выбрать"),"ID заявки":st.column_config.NumberColumn("ID заявки",disabled=True),"Материал":st.column_config.TextColumn("Материал",disabled=True),"Единица":st.column_config.TextColumn("Единица",disabled=True),"Необходимо производству":st.column_config.NumberColumn("Необходимо производству",disabled=True,format="%.4f"),"Свободно на складе":st.column_config.NumberColumn("Свободно на складе",disabled=True,format="%.4f"),"Поставщик":st.column_config.SelectboxColumn("Поставщик",options=soptions),"Заказать количество":st.column_config.NumberColumn("Заказать количество",min_value=0.0,step=0.001,format="%.4f")},disabled=["ID заявки","Материал","Единица","Необходимо производству","Свободно на складе"])
                do_purchase=st.form_submit_button("Выполнить",use_container_width=True)
            if do_purchase:
                sel=edited[edited["Выбрать"].fillna(False)&(edited["Заказать количество"].fillna(0)>0)].copy(); statements=[]; data=[]
                for _,rr in sel.iterrows():
                    full=order_df[order_df["ID заявки"].eq(safe_int(rr["ID заявки"]))].iloc[0]; sid=next((i for i,l in slabels.items() if l==str(rr["Поставщик"])),get_default_supplier_id()); mid=safe_int(full["material_id"]); qty=safe_float(rr["Заказать количество"]); oid2=safe_int(full["object_id"]); price_df=run_query("SELECT COALESCE(ms.purchase_price,m.cost_per_unit,0) AS price FROM reklet.materials m LEFT JOIN reklet.material_suppliers ms ON ms.material_id=m.id AND ms.supplier_id=%s WHERE m.id=%s ORDER BY ms.id DESC LIMIT 1",(sid,mid),fetch=True); price=safe_float(price_df.iloc[0]["price"]) if not price_df.empty else 0.0
                    statements.append(("WITH new_po AS (INSERT INTO reklet.purchase_orders(supplier_id,status,notes) VALUES (%s,'received',%s) RETURNING id) INSERT INTO reklet.purchase_order_items(purchase_order_id,object_id,material_id,quantity_ordered,quantity_received,unit_price) SELECT id,%s,%s,%s,%s,%s FROM new_po",(sid,"Пополнение по заявке производства",oid2,mid,qty,qty,price)))
                    statements.extend([("INSERT INTO reklet.material_transactions(material_id,supplier_id,object_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,%s,'purchase',%s,%s,'IN')",(mid,sid,oid2,qty,price)),("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",(qty,mid)),("INSERT INTO reklet.material_suppliers(material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT(material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price",(mid,sid,price))])
                    statements.append(("UPDATE reklet.material_production_requests SET status='ready',updated_at=timezone('utc'::text,now()) WHERE id=%s",(safe_int(full["ID заявки"]),)))
                if sel.empty: st.info("Выберите материал и укажите количество закупки.")
                else: run_transaction(statements); st.success("Материал закуплен/оприходован, заявка обновлена. При необходимости она останется открытой до передачи в производство."); st.rerun()

            ready=requests[requests["status"].isin(["sent","purchasing","ready"])].copy()
            if not ready.empty:
                st.markdown("---"); st.subheader("Отправить необходимый материал на производство")
                ready_map={f"{int(r['id'])} — {r['object_name']} — {r['material_name']} — осталось {safe_float(r['remaining_quantity']):.4f}":int(r['id']) for _,r in ready.iterrows()}
                send_label=st.selectbox("Заявка для передачи",list(ready_map.keys()),key="production_request_send_select_v4")
                send_id=ready_map[send_label]; send_req=ready[ready["id"]==send_id].iloc[0]
                mid=safe_int(send_req["material_id"]); oid2=safe_int(send_req["object_id"])
                stock_df=run_query("SELECT COALESCE(stock_quantity,0) AS stock_quantity FROM reklet.materials WHERE id=%s",(mid,),fetch=True)
                stock=safe_float(stock_df.iloc[0]["stock_quantity"]) if not stock_df.empty else 0.0
                remaining_req=safe_float(send_req["remaining_quantity"]); qty_possible=min(remaining_req,stock)
                st.write(f"Необходимо передать: **{remaining_req:.4f}**; на складе: **{stock:.4f}**.")
                if qty_possible<=1e-9:
                    st.info("Пока на складе нет достаточного материала. Оформите закупку выше.")
                else:
                    send_qty=st.number_input("Отправить на производство",min_value=0.0,max_value=float(qty_possible),value=float(qty_possible),step=0.001,format="%.4f",key="production_request_send_qty_v4")
                    if st.button("Выполнить передачу",key="production_request_send_button_v4",use_container_width=True):
                        statements=[("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",(mid,oid2,send_qty)),("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(send_qty,mid)),("UPDATE reklet.material_production_requests SET quantity_supplied=quantity_supplied+%s,status=CASE WHEN quantity_supplied+%s>=quantity_requested THEN 'completed' ELSE 'ready' END,updated_at=timezone('utc'text',now()) WHERE id=%s",(send_qty,send_qty,send_id))]
                        # Correct the SQL cast/token above to plain PostgreSQL expression.
                        statements[-1]=( "UPDATE reklet.material_production_requests SET quantity_supplied=quantity_supplied+%s,status=CASE WHEN quantity_supplied+%s>=quantity_requested THEN 'completed' ELSE 'ready' END,updated_at=timezone('utc'::text,now()) WHERE id=%s", (send_qty,send_qty,send_id) )
                        run_transaction(statements); st.success("Необходимый материал отправлен в производство."); st.rerun()


    elif active_material_section == "movement":
        ensure_task_three_tables()
        st.subheader("Движение материалов")
        movements=run_query("""SELECT * FROM (
            SELECT mt.created_at AS tx_date,CASE mt.operation_type WHEN 'purchase' THEN 'Приход материала' WHEN 'production_transfer' THEN 'Выдано в производство' ELSE mt.operation_type END AS operation_name,c.name AS client_name,o.object_name,NULL::text AS product_name,m.name AS material_name,s.name AS supplier_name,mt.quantity::numeric AS quantity,mt.unit_price::numeric AS unit_price FROM reklet.material_transactions mt LEFT JOIN reklet.materials m ON m.id=mt.material_id LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id LEFT JOIN reklet.objects o ON o.id=mt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id
            UNION ALL
            SELECT mc.created_at,'Списано при производстве',c.name,o.object_name,oi.item_name,m.name,NULL::text,mc.quantity::numeric,COALESCE(mc.unit_cost_snapshot,0)::numeric FROM reklet.material_consumption mc LEFT JOIN reklet.objects o ON o.id=mc.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=mc.object_item_id LEFT JOIN reklet.materials m ON m.id=mc.material_id
            UNION ALL
            SELECT mw.created_at,CASE mw.source_type WHEN 'stock' THEN 'Удалено со склада' WHEN 'production' THEN 'Удалено из производства' ELSE 'Удалённый материал' END,c.name,o.object_name,NULL::text,m.name,NULL::text,mw.quantity::numeric,mw.unit_cost_snapshot::numeric FROM reklet.material_waste_transactions mw LEFT JOIN reklet.objects o ON o.id=mw.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.materials m ON m.id=mw.material_id
        ) x ORDER BY tx_date DESC LIMIT 2000""",fetch=True)
        if movements.empty: st.info("Движений материалов пока нет.")
        else:
            f1,f2,f3=st.columns(3); f4,f5,f6=st.columns(3)
            def opts(col):
                vals=movements[col].fillna("").astype(str).replace("","—").drop_duplicates().sort_values().tolist(); return ["Все"]+vals
            with f1: mc=st.selectbox("Заказчик",opts("client_name"),key="movement_client_v3")
            with f2: ms=st.selectbox("Поставщик",opts("supplier_name"),key="movement_supplier_v3")
            with f3: mo=st.selectbox("Объект",opts("object_name"),key="movement_object_v3")
            with f4: mm=st.selectbox("Материал",opts("material_name"),key="movement_material_v3")
            with f5: mpi=st.selectbox("Изделие",opts("product_name"),key="movement_product_v3")
            with f6: date_range=st.date_input("Период",value=(pd.Timestamp.today().date()-pd.Timedelta(days=30),pd.Timestamp.today().date()),key="movement_period_v3")
            filt=movements.copy()
            if mc!="Все": filt=filt[filt["client_name"].fillna("").astype(str)==("" if mc=="—" else mc)]
            if ms!="Все": filt=filt[filt["supplier_name"].fillna("").astype(str)==("" if ms=="—" else ms)]
            if mo!="Все": filt=filt[filt["object_name"].fillna("").astype(str)==("" if mo=="—" else mo)]
            if mm!="Все": filt=filt[filt["material_name"].fillna("").astype(str)==("" if mm=="—" else mm)]
            if mpi!="Все": filt=filt[filt["product_name"].fillna("").astype(str)==("" if mpi=="—" else mpi)]
            if isinstance(date_range,tuple) and len(date_range)==2:
                d1=pd.Timestamp(date_range[0]); d2=pd.Timestamp(date_range[1])+pd.Timedelta(days=1); dt=pd.to_datetime(filt["tx_date"],errors="coerce"); filt=filt[(dt>=d1)&(dt<d2)]
            view=filt.rename(columns={"tx_date":"Дата","operation_name":"Операция","client_name":"Заказчик","object_name":"Объект","product_name":"Изделие","material_name":"Материал","supplier_name":"Поставщик","quantity":"Количество","unit_price":"Цена"})[["Дата","Операция","Заказчик","Объект","Изделие","Материал","Поставщик","Количество","Цена"]]
            st.dataframe(view,width="stretch",hide_index=True); render_print_html("Движение материалов",view,"print_material_movements_v3")
# ============================================================
# SUPPLIERS
# ============================================================
elif menu == "Поставщики":
    st.header("Поставщики")

    supplier_sub = render_button_nav(
        [
            "Перечень поставщиков",
            "Создать поставщика",
            "Материалы поставщика",
            "Поиск поставщика",
            "Коррекция и удаление поставщиков"
        ],
        "suppliers_navigation",
        "suppliers_nav",
        columns_per_row=5
    )
    suppliers=get_suppliers()

    if supplier_sub=="Перечень поставщиков":
        st.subheader("Перечень поставщиков")
        if suppliers.empty:
            st.info("Поставщиков нет.")
        else:
            display_cols=[c for c in ["id","name","type","contact_person","phone","email","conditions"] if c in suppliers.columns]
            supplier_view = suppliers[display_cols].copy()
            st.dataframe(supplier_view,width="stretch",hide_index=True)
            render_print_html("Перечень поставщиков", supplier_view, "print_supplier_list")

    elif supplier_sub=="Создать поставщика":
        st.subheader("Создать поставщика")
        with st.form("create_supplier_new"):
            name=st.text_input("Название")
            supplier_type=st.selectbox("Тип поставщика",["material_supplier","subcontractor","both"])
            contact_person=st.text_input("Контактное лицо")
            phone=st.text_input("Телефон")
            email=st.text_input("Email")
            conditions=st.text_area("Условия")
            contact_info=st.text_area("Контактная информация")
            submit=st.form_submit_button("Создать поставщика")
            if submit:
                if not name.strip():
                    st.warning("Необходимо указать название.")
                else:
                    st.session_state["pending_supplier_create"]={
                        "name":name.strip(),"type":supplier_type,"contact_person":contact_person.strip(),
                        "phone":phone.strip(),"email":email.strip(),
                        "conditions":conditions.strip(),"contact_info":contact_info.strip()
                    }
        pending_supplier=st.session_state.get("pending_supplier_create")
        if pending_supplier:
            st.warning("Подтвердите создание поставщика.")
            supplier_preview=pd.DataFrame([pending_supplier])
            supplier_preview.columns=["Название","Тип","Контактное лицо","Телефон","Email","Условия","Контактная информация"]
            st.dataframe(supplier_preview,width="stretch",hide_index=True)
            c1,c2=st.columns(2)
            with c1:
                ok=st.button("Подтвердить создание",key="confirm_supplier_create",use_container_width=True)
            with c2:
                no=st.button("Отменить",key="cancel_supplier_create",use_container_width=True)
            if no:
                st.session_state.pop("pending_supplier_create",None)
                st.rerun()
            if ok:
                run_query(
                    """INSERT INTO reklet.suppliers
                       (name,type,contact_info,contact_person,phone,email,conditions)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (pending_supplier["name"],pending_supplier["type"],pending_supplier["contact_info"] or None,
                     pending_supplier["contact_person"] or None,pending_supplier["phone"] or None,
                     pending_supplier["email"] or None,pending_supplier["conditions"] or None)
                )
                st.session_state.pop("pending_supplier_create",None)
                st.success(f"Поставщик «{pending_supplier['name']}» создан.")
                st.rerun()

    elif supplier_sub=="Материалы поставщика":
        st.subheader("Материалы поставщика")

        st.markdown("---")

        if suppliers.empty:
            st.info("Сначала создайте поставщика.")
        else:
            supplier_map={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in suppliers.iterrows()}
            selected_supplier_label=st.selectbox("Отбор по поставщику",list(supplier_map.keys()),key="supplier_material_filter")
            supplier_id=supplier_map[selected_supplier_label]

            linked=run_query(
                """SELECT ms.id,m.id AS material_id,m.name AS material,
                          mc.name AS category,ms.purchase_price,ms.supplier_code,
                          ms.conditions,ms.is_preferred
                   FROM reklet.material_suppliers ms
                   JOIN reklet.materials m ON m.id=ms.material_id
                   LEFT JOIN reklet.material_categories mc ON mc.id=m.category_id
                   WHERE ms.supplier_id=%s ORDER BY m.name""",
                (supplier_id,),fetch=True
            )
            if linked.empty:
                st.info("Для этого поставщика материалы пока не привязаны.")
            else:
                view=linked.copy()
                view.columns=["ID связи","ID материала","Материал","Категория","Цена","Код поставщика","Условия","Предпочтительный"]
                st.dataframe(view,width="stretch",hide_index=True)
                render_print_html(
                    f"Материалы поставщика — {selected_supplier_label}",
                    view,
                    f"print_supplier_materials_{supplier_id}"
                )

            all_materials=get_materials_with_categories()
            material_categories=get_material_categories()
            category_options=["Все категории","Без категории"] + (material_categories["name"].astype(str).tolist() if not material_categories.empty else [])
            add_category=st.selectbox("Категория материала для добавления",category_options,key="supplier_material_add_category")
            filtered_add_materials=all_materials.copy()
            if add_category=="Без категории":
                filtered_add_materials=filtered_add_materials[filtered_add_materials["category_id"].isna()].copy()
            elif add_category!="Все категории":
                filtered_add_materials=filtered_add_materials[filtered_add_materials["category_name"].fillna("").astype(str).eq(add_category)].copy()

            material_options={
                f"{int(r['id'])} — {r['name']}":int(r['id'])
                for _,r in filtered_add_materials.sort_values("name").iterrows()
            }
            if not material_options:
                st.info("В выбранной категории материалов нет.")
            else:
                with st.form("supplier_material_link_form_new"):
                    material_label=st.selectbox("Материал для добавления",list(material_options.keys()))
                    price=st.number_input("Закупочная цена",min_value=0.0,value=0.0,format="%.2f")
                    code=st.text_input("Код поставщика")
                    conditions=st.text_area("Условия")
                    preferred=st.checkbox("Предпочтительный поставщик")
                    if st.form_submit_button("Добавить материал поставщику"):
                        run_query(
                            """INSERT INTO reklet.material_suppliers
                               (material_id,supplier_id,purchase_price,supplier_code,conditions,is_preferred)
                               VALUES (%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(material_id,supplier_id)
                               DO UPDATE SET purchase_price=EXCLUDED.purchase_price,
                                             supplier_code=EXCLUDED.supplier_code,
                                             conditions=EXCLUDED.conditions,
                                             is_preferred=EXCLUDED.is_preferred""",
                            (material_options[material_label],supplier_id,price,code.strip() or None,
                             conditions.strip() or None,preferred)
                        )
                        st.success("Материал поставщику добавлен.")
                        st.rerun()

            if not linked.empty:
                with st.expander("Убрать материал у поставщика",expanded=False):
                    link_map={
                        f"{int(r['material_id'])} — {r['material']}":int(r['material_id'])
                        for _,r in linked.iterrows()
                    }
                    unlink_label=st.selectbox("Материал",list(link_map.keys()),key="unlink_supplier_material")
                    unlink_confirm=st.checkbox(
                        "Я подтверждаю удаление связи поставщик → материал.",
                        key="confirm_unlink_supplier_material"
                    )
                    if st.button("Убрать материал у поставщика",key="unlink_supplier_material_button",disabled=not unlink_confirm):
                        run_query(
                            "DELETE FROM reklet.material_suppliers WHERE supplier_id=%s AND material_id=%s",
                            (supplier_id,link_map[unlink_label])
                        )
                        st.success("Материал убран из списка поставщика.")
                        st.rerun()


    elif supplier_sub=="Поиск поставщика":
        st.subheader("Поиск поставщика")

        all_materials = get_materials_with_categories()
        material_categories = get_material_categories()

        if all_materials.empty:
            st.info("Материалов пока нет.")
        else:
            category_options = ["Все категории", "Без категории"] + (
                material_categories["name"].astype(str).tolist()
                if not material_categories.empty else []
            )

            search_category = st.selectbox(
                "Категория материала",
                category_options,
                key="supplier_search_category"
            )

            filtered_materials = all_materials.copy()
            if search_category == "Без категории":
                filtered_materials = filtered_materials[
                    filtered_materials["category_id"].isna()
                ].copy()
            elif search_category != "Все категории":
                filtered_materials = filtered_materials[
                    filtered_materials["category_name"].fillna("").astype(str).eq(search_category)
                ].copy()

            if filtered_materials.empty:
                st.info("В выбранной категории материалов нет.")
            else:
                material_map = {
                    f"{int(row['id'])} — {row['name']}": int(row['id'])
                    for _, row in filtered_materials.sort_values("name").iterrows()
                }

                selected_material = st.selectbox(
                    "Материал",
                    list(material_map.keys()),
                    key="supplier_search_material_new"
                )
                material_id = material_map[selected_material]

                suppliers_for_material = run_query(
                    """
                    SELECT
                        s.id,
                        s.name AS supplier,
                        ms.purchase_price,
                        ms.supplier_code,
                        ms.conditions,
                        ms.is_preferred
                    FROM reklet.material_suppliers ms
                    JOIN reklet.suppliers s
                        ON s.id = ms.supplier_id
                    WHERE ms.material_id = %s
                    ORDER BY s.name
                    """,
                    (material_id,),
                    fetch=True
                )

                if suppliers_for_material.empty:
                    st.info("Для этого материала поставщики не назначены.")
                else:
                    supplier_view = suppliers_for_material.copy()
                    supplier_view.columns = [
                        "ID",
                        "Поставщик",
                        "Цена",
                        "Код поставщика",
                        "Условия",
                        "Предпочтительный"
                    ]
                    st.dataframe(
                        supplier_view,
                        width="stretch",
                        hide_index=True
                    )
                    render_print_html(
                        f"Поставщики материала — {str(selected_material).split(' — ', 1)[-1]}",
                        supplier_view,
                        f"print_supplier_search_{material_id}",
                        subtitle=f"Категория: {search_category}"
                    )

    elif supplier_sub=="Коррекция и удаление поставщиков":
        st.subheader("Коррекция поставщиков")
        if suppliers.empty:
            st.info("Поставщиков нет.")
        else:
            supplier_map={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in suppliers.iterrows()}
            selected_label=st.selectbox("Поставщик",list(supplier_map.keys()),key="supplier_edit_select")
            selected_id=supplier_map[selected_label]
            row=suppliers[suppliers["id"]==selected_id].iloc[0]
            with st.form("edit_supplier_form"):
                name=st.text_input("Название",value=str(row.get("name") or ""))
                types=["material_supplier","subcontractor","both"]
                current_type=str(row.get("type") or "material_supplier")
                supplier_type=st.selectbox("Тип поставщика",types,index=types.index(current_type) if current_type in types else 0)
                contact_person=st.text_input("Контактное лицо",value=str(row.get("contact_person") or ""))
                phone=st.text_input("Телефон",value=str(row.get("phone") or ""))
                email=st.text_input("Email",value=str(row.get("email") or ""))
                conditions=st.text_area("Условия",value=str(row.get("conditions") or ""))
                contact_info=st.text_area("Контактная информация",value=str(row.get("contact_info") or ""))
                if st.form_submit_button("Сохранить изменения"):
                    if not name.strip():
                        st.warning("Название поставщика не может быть пустым.")
                    else:
                        run_query(
                            """UPDATE reklet.suppliers SET name=%s,type=%s,contact_info=%s,
                                      contact_person=%s,phone=%s,email=%s,conditions=%s
                               WHERE id=%s""",
                            (name.strip(),supplier_type,contact_info.strip() or None,
                             contact_person.strip() or None,phone.strip() or None,email.strip() or None,
                             conditions.strip() or None,selected_id)
                        )
                        st.success("Данные поставщика изменены.")
                        st.rerun()

            with st.expander("Удаление поставщика",expanded=False):
                st.warning(
                    "Безопасное удаление: поставщик не будет удалён, "
                    "если он используется материалами или движениями."
                )
                confirm=st.checkbox("Я подтверждаю удаление выбранного поставщика.",key="confirm_supplier_delete")
                if st.button("Удалить поставщика",key="delete_supplier_safe",disabled=not confirm):
                    used=run_query(
                        """SELECT
                             (SELECT COUNT(*) FROM reklet.material_suppliers WHERE supplier_id=%s) AS material_links,
                             (SELECT COUNT(*) FROM reklet.material_transactions WHERE supplier_id=%s) AS transactions,
                             (SELECT COUNT(*) FROM reklet.purchase_orders WHERE supplier_id=%s) AS purchase_orders""",
                        (selected_id,selected_id,selected_id),fetch=True
                    )
                    if int(used.iloc[0]["material_links"])>0 or int(used.iloc[0]["transactions"])>0 or int(used.iloc[0]["purchase_orders"])>0:
                        st.error("Удаление невозможно: поставщик используется в связанных данных.")
                    else:
                        run_query("DELETE FROM reklet.suppliers WHERE id=%s",(selected_id,))
                        st.success("Поставщик удалён.")
                        st.rerun()

# ============================================================
# PRODUCTION
# ============================================================

elif menu == "Производство":

    ensure_material_planning_tables()
    ensure_task_three_tables()
    st.header("Производство")
    ensure_stage_movement_tables()

    objects_all = get_objects().sort_values("id", ascending=False).copy()
    clients_all = get_clients()
    if objects_all.empty:
        st.success("Объектов нет.")
    else:
        client_options = ["Все заказчики"] + [f"{int(r['id'])} — {r['name']}" for _,r in clients_all.iterrows()]
        selected_client = st.selectbox("Заказчик",client_options,key="production_scope_client_v4")
        client_id = None if selected_client == "Все заказчики" else int(selected_client.split(" — ")[0])
        object_options = ["Все объекты"]
        filtered_objs = objects_all if client_id is None else objects_all[objects_all["client_id"].eq(client_id)].copy()
        object_options += [f"{int(r['id'])} — {r['object_name']}" for _,r in filtered_objs.iterrows()]
        selected_object = st.selectbox("Объект",object_options,key="production_scope_object_v4")
        object_id = None if selected_object == "Все объекты" else int(selected_object.split(" — ")[0])

        # Overview for all objects.
        if object_id is None:
            summary = run_query(
                """SELECT o.id AS "ID",COALESCE(c.name,'') AS "Заказчик",o.object_name AS "Объект",
                          COALESCE(SUM(oi.quantity_needed),0) AS "Заказано",
                          COALESCE(SUM(oi.qty_new),0) AS "Осталось запустить",
                          COALESCE(SUM(oi.qty_production),0) AS "В производстве",
                          COALESCE(SUM(oi.qty_ready),0) AS "Готовая продукция"
                   FROM reklet.objects o LEFT JOIN reklet.clients c ON c.id=o.client_id
                   JOIN reklet.object_items oi ON oi.object_id=o.id
                   WHERE (%s OR o.client_id=%s) GROUP BY o.id,c.name,o.object_name ORDER BY o.object_name""",
                (client_id is None, client_id if client_id is not None else -1),fetch=True
            )
            if summary.empty: st.info("Нет изделий для выбранного отбора.")
            else: st.dataframe(summary,width="stretch",hide_index=True)
            st.info("Для выполнения производства выберите конкретный объект.")
        else:
            production_df = run_query(
                """SELECT oi.id,oi.item_name,oi.quantity_needed,
                          COALESCE(oi.qty_new,0) AS qty_new,
                          COALESCE(oi.qty_production,0) AS qty_production,
                          COALESCE(oi.qty_ready,0) AS qty_ready,
                          (COALESCE(oi.quantity_needed,0)-COALESCE(oi.qty_new,0)) AS manufactured_total
                   FROM reklet.object_items oi WHERE oi.object_id=%s
                   ORDER BY oi.id""",(object_id,),fetch=True
            )
            if production_df.empty:
                st.info("Для выбранного объекта изделий нет.")
            else:
                ensure_object_item_material_costs(object_id)
                # Table is informational; the action is performed for one selected item below.
                production_view = production_df[["id","item_name","quantity_needed","qty_new","qty_production","manufactured_total"]].copy()
                production_view.columns=["ID","Изделие","Заказано","Осталось запустить","В производстве","Изготовлено всего"]
                st.dataframe(production_view,width="stretch",hide_index=True)
                render_print_html(f"Производственное задание — {selected_object}",production_view,f"print_production_v4_{object_id}")

                item_options={f"{int(r['id'])} — {r['item_name']}":int(r['id']) for _,r in production_df.iterrows() if safe_int(r['quantity_needed'])>0}
                if item_options:
                    selected_item_label=st.selectbox("Изделие",list(item_options.keys()),key="production_item_v4")
                    item_id=item_options[selected_item_label]
                    item_row=production_df[production_df["id"].eq(item_id)].iloc[0]
                    ordered=safe_int(item_row["quantity_needed"])
                    manufactured_total=safe_int(item_row["manufactured_total"])
                    remaining_to_make=max(ordered-manufactured_total,0)
                    in_production=safe_int(item_row["qty_production"])
                    st.write(f"Осталось изготовить: **{remaining_to_make} шт.**; уже в производстве: **{in_production} шт.**")

                    # Material capacity based on actual WIP for this object.
                    req=run_query(
                        """SELECT ptm.material_id,m.name AS material_name,
                                  COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0) AS quantity_per_unit,
                                  COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1) AS waste_coefficient
                           FROM reklet.product_template_materials ptm JOIN reklet.materials m ON m.id=ptm.material_id
                           LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=%s AND oimc.material_id=ptm.material_id
                           WHERE ptm.product_template_id=COALESCE((SELECT product_template_id FROM reklet.object_items WHERE id=%s),(SELECT template_id FROM reklet.object_items WHERE id=%s))""",
                        (item_id,item_id,item_id),fetch=True
                    )
                    wip_map={}
                    for _,rr in req.iterrows():
                        mid=safe_int(rr["material_id"])
                        x=run_query(
                            """SELECT GREATEST(
                                  COALESCE((SELECT SUM(mt.quantity) FROM reklet.material_transactions mt WHERE mt.object_id=%s AND mt.material_id=%s AND mt.operation_type='production_transfer' AND mt.transaction_type='OUT'),0)
                                  - COALESCE((SELECT SUM(mc.quantity) FROM reklet.material_consumption mc WHERE mc.object_id=%s AND mc.material_id=%s),0)
                                  - COALESCE((SELECT SUM(mw.quantity) FROM reklet.material_waste_transactions mw WHERE mw.object_id=%s AND mw.material_id=%s AND mw.source_type='production'),0),0) AS wip""",
                            (object_id,mid,object_id,mid,object_id,mid),fetch=True)
                        wip_map[mid]=safe_float(x.iloc[0]["wip"]) if not x.empty else 0.0
                    per_material={safe_int(rr["material_id"]):safe_float(rr["quantity_per_unit"])*safe_float(rr["waste_coefficient"],1.0) for _,rr in req.iterrows()}
                    max_by_material={mid:(wip_map.get(mid,0.0)/per_material[mid] if per_material[mid]>1e-12 else 10**9) for mid in per_material}
                    producible=remaining_to_make if not max_by_material else min(remaining_to_make,int(min(max_by_material.values())))

                    desired_qty=st.number_input("Изготовить",min_value=0,max_value=remaining_to_make,value=remaining_to_make if remaining_to_make>0 else 0,step=1,key=f"production_qty_v4_{item_id}")
                    if req.empty:
                        st.warning("У изделия нет материалов в спецификации. Производство возможно без проверки материала.")
                    elif desired_qty>producible:
                        shortage_qty=desired_qty-producible
                        st.warning(
                            f"У вас есть материала только на {producible} изделий из {desired_qty}. "
                            f"Необходимо дополнительно обеспечить материалом {shortage_qty} изделий."
                        )

                        shortage_rows=[]
                        for mid,pper in per_material.items():
                            missing=max(shortage_qty*pper,0.0)
                            if missing>1e-9:
                                shortage_rows.append({
                                    "Материал": next((str(x["material_name"]) for _,x in req.iterrows() if safe_int(x["material_id"])==mid),str(mid)),
                                    "Единица": next((str(x.get("unit_name","") or "") for _,x in req.iterrows() if safe_int(x["material_id"])==mid),""),
                                    "Необходимо дополнительно": missing,
                                })
                        shortage_df=pd.DataFrame(shortage_rows)
                        if not shortage_df.empty:
                            st.subheader("Заказать материал со склада")
                            st.dataframe(shortage_df,width="stretch",hide_index=True)
                            st.caption(
                                "Нажатие «Заказать на складе» одновременно выпускает доступное количество изделий "
                                "и создаёт заявку на недостающий материал."
                            )
                            if st.button(
                                "Заказать на складе",
                                key=f"produce_partial_request_{item_id}",
                                use_container_width=True
                            ):
                                statements=[]
                                if producible>0:
                                    for mid,pper in per_material.items():
                                        consume_qty=producible*pper
                                        if consume_qty>1e-9:
                                            statements.append(("INSERT INTO reklet.material_consumption(object_item_id,object_id,material_id,quantity,unit_cost_snapshot) SELECT %s,%s,%s,%s,COALESCE(oimc.unit_cost,m.cost_per_unit,0) FROM reklet.materials m LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=%s AND oimc.material_id=%s WHERE m.id=%s",(item_id,object_id,mid,consume_qty,item_id,mid,mid)))
                                    statements += [("UPDATE reklet.object_items SET qty_new=GREATEST(quantity_needed-qty_production-qty_ready-qty_shipped-qty_arrived-qty_installing-qty_installed-%s,0),qty_production=COALESCE(qty_production,0)+%s,production_status='in_progress' WHERE id=%s",(producible,producible,item_id)),("INSERT INTO reklet.production_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'completed',%s)",(item_id,object_id,producible))]
                                for mid,pper in per_material.items():
                                    missing=max(shortage_qty*pper,0.0)
                                    if missing<=1e-9: continue
                                    exists=run_query("SELECT id,quantity_requested,quantity_supplied FROM reklet.material_production_requests WHERE object_item_id=%s AND material_id=%s AND status IN ('sent','purchasing','ready') ORDER BY id LIMIT 1",(item_id,mid),fetch=True)
                                    if exists.empty:
                                        statements.append(("INSERT INTO reklet.material_production_requests(object_id,object_item_id,material_id,quantity_requested,status,notes) VALUES (%s,%s,%s,%s,'sent','Заявка производства на недостающий материал')",(object_id,item_id,mid,missing)))
                                    else:
                                        rid=safe_int(exists.iloc[0]["id"]); req_now=safe_float(exists.iloc[0]["quantity_requested"]); supplied=safe_float(exists.iloc[0]["quantity_supplied"]); new_req=max(req_now,supplied+missing)
                                        statements.append(("UPDATE reklet.material_production_requests SET quantity_requested=%s,status='sent',updated_at=timezone('utc'::text,now()) WHERE id=%s",(new_req,rid)))
                                if statements:
                                    run_transaction(statements)
                                st.success(
                                    f"Доступно изготовить: {producible}. "
                                    "Заявка на недостающий материал отправлена на склад."
                                )
                                st.rerun()
                    elif desired_qty>0:
                        if st.button("Изготовить",key=f"produce_full_{item_id}",type="primary",use_container_width=True):
                            statements=[]
                            for mid,pper in per_material.items():
                                consume_qty=desired_qty*pper
                                if consume_qty>1e-9:
                                    statements.append(("INSERT INTO reklet.material_consumption(object_item_id,object_id,material_id,quantity,unit_cost_snapshot) SELECT %s,%s,%s,%s,COALESCE(oimc.unit_cost,m.cost_per_unit,0) FROM reklet.materials m LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=%s AND oimc.material_id=%s WHERE m.id=%s",(item_id,object_id,mid,consume_qty,item_id,mid,mid)))
                            statements += [("UPDATE reklet.object_items SET qty_new=GREATEST(quantity_needed-qty_production-qty_ready-qty_shipped-qty_arrived-qty_installing-qty_installed-%s,0),qty_production=COALESCE(qty_production,0)+%s,production_status='in_progress' WHERE id=%s",(desired_qty,desired_qty,item_id)),("INSERT INTO reklet.production_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'completed',%s)",(item_id,object_id,desired_qty))]
                            run_transaction(statements); st.success(f"Изготовлено {desired_qty}."); st.rerun()

                    if in_production>0:
                        transfer_qty=st.number_input("Передать на склад готовой продукции",min_value=0,max_value=in_production,value=0,step=1,key=f"production_transfer_v4_{item_id}")
                        if st.button("Передать на склад",key=f"production_transfer_button_v4_{item_id}",use_container_width=True) and transfer_qty>0:
                            statements=[
                                ("UPDATE reklet.object_items SET qty_production=GREATEST(COALESCE(qty_production,0)-%s,0),qty_ready=COALESCE(qty_ready,0)+%s WHERE id=%s",(transfer_qty,transfer_qty,item_id)),
                                ("INSERT INTO reklet.finished_goods(object_item_id,object_id,quantity,status) VALUES (%s,%s,%s,'ready')",(item_id,object_id,transfer_qty)),
                                ("INSERT INTO reklet.finished_goods_transactions(object_item_id,object_id,operation_type,quantity) VALUES (%s,%s,'ready',%s)",(item_id,object_id,transfer_qty)),
                            ]
                            run_transaction(statements); st.success("Изделие передано на склад готовой продукции."); st.rerun()

        open_req=get_open_production_requests()
        if not open_req.empty:
            st.markdown("---")
            st.subheader("Заказы материала с производства")
            rv=open_req.rename(columns={"id":"ID заявки","client_name":"Заказчик","object_name":"Объект","item_name":"Изделие","material_name":"Материал","unit_name":"Единица","quantity_requested":"Необходимо","quantity_supplied":"Передано","remaining_quantity":"Осталось","status":"Статус","created_at":"Дата"})
            st.dataframe(rv[["ID заявки","Заказчик","Объект","Изделие","Материал","Единица","Необходимо","Передано","Осталось","Статус","Дата"]],width="stretch",hide_index=True)

elif menu == "Готовая продукция":

    st.header("Готовая продукция")
    ensure_stage_movement_tables()

    objects = get_stage_objects("finished_goods")
    if objects.empty:
        st.success("На складе готовой продукции нет незавершённых заданий.")
    else:
        object_options = [f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _, r in objects.iterrows()]
        object_map = {x: int(x.split(" — ")[0]) for x in object_options}
        selected_object = st.selectbox("Объект", object_options, key="finished_goods_object_filter")
        object_id = object_map[selected_object]

        df = run_query(
            """SELECT oi.id, oi.item_name, oi.quantity_needed AS ordered,
                      COALESCE(oi.qty_ready,0) AS ready,
                      COALESCE(oi.qty_shipped,0) AS shipped,
                      COALESCE(oi.qty_arrived,0) AS arrived
               FROM reklet.object_items oi
               WHERE oi.object_id=%s AND COALESCE(oi.qty_ready,0)>0
               ORDER BY oi.id""",
            (object_id,), fetch=True
        )

        if df.empty:
            st.success("Для выбранного объекта на складе готовой продукции нет изделий для передачи в транспорт.")
        else:
            editor=df[["id","item_name","ordered","ready","shipped","arrived"]].copy()
            editor.columns=["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]
            editor["Передать в транспорт"]=0
            finished_goods_print = editor[["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]].copy()
            render_print_html(
                f"Готовая продукция — {selected_object}",
                finished_goods_print,
                f"print_finished_goods_{object_id}"
            )
            with st.form(f"finished_goods_form_{object_id}", clear_on_submit=False):
                edited=st.data_editor(
                    editor, key=f"finished_goods_editor_{object_id}", width="stretch", hide_index=True,
                    column_config={
                        "ID":st.column_config.NumberColumn("ID",disabled=True),
                        "Изделие":st.column_config.TextColumn("Изделие",disabled=True),
                        "Заказано":st.column_config.NumberColumn("Заказано",disabled=True),
                        "На складе":st.column_config.NumberColumn("На складе",disabled=True),
                        "Уже отправлено":st.column_config.NumberColumn("Уже отправлено",disabled=True),
                        "Доставлено":st.column_config.NumberColumn("Доставлено",disabled=True),
                        "Передать в транспорт":st.column_config.NumberColumn("Передать в транспорт",min_value=0,step=1,format="%d"),
                    },
                    disabled=["ID","Изделие","Заказано","На складе","Уже отправлено","Доставлено"]
                )
                execute=st.form_submit_button("Выполнить",use_container_width=True)
            if execute:
                errors=[]; statements=[]
                for _,r in edited.iterrows():
                    qty=safe_int(r["Передать в транспорт"]); available=safe_int(r["На складе"]); item_id=safe_int(r["ID"])
                    if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, на складе только {available}.")
                    if qty>0:
                        statements.extend([
                            ("UPDATE reklet.object_items SET qty_ready=GREATEST(COALESCE(qty_ready,0)-%s,0), qty_shipped=COALESCE(qty_shipped,0)+%s WHERE id=%s",(qty,qty,item_id)),
                            ("UPDATE reklet.finished_goods SET quantity=GREATEST(quantity-%s,0), status=CASE WHEN quantity-%s<=0 THEN 'shipped' ELSE 'ready' END WHERE id=(SELECT id FROM reklet.finished_goods WHERE object_item_id=%s AND status='ready' AND quantity>0 ORDER BY created_at, id LIMIT 1)",(qty,qty,item_id)),
                            ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                            ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                        ])
                if errors: st.error("Операция не выполнена:\n"+"\n".join(errors))
                elif not statements: st.info("Введите количество хотя бы для одной строки.")
                else:
                    run_transaction(statements); st.success("Изделия переданы в транспорт."); st.rerun()

    st.markdown("---")
    st.subheader("Движения по складу готовой продукции")
    movements=run_query("""SELECT fgt.id,o.object_name,c.name AS client_name,oi.item_name,fgt.operation_type,fgt.quantity,fgt.created_at FROM reklet.finished_goods_transactions fgt LEFT JOIN reklet.objects o ON o.id=fgt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=fgt.object_item_id ORDER BY fgt.created_at DESC LIMIT 500""",fetch=True)
    if movements.empty: st.info("Движений пока нет.")
    else:
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"})
        finished_movement_view = movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]].copy()
        st.dataframe(finished_movement_view,width="stretch",hide_index=True)
        render_print_html("Движения по складу готовой продукции", finished_movement_view, "print_finished_goods_movements")

# ============================================================
# TRANSPORT & LOGISTICS
# ============================================================

elif menu == "Транспорт и логистика":

    st.header("Транспорт и логистика")
    ensure_stage_movement_tables()
    objects_all=get_objects().sort_values("id",ascending=False).copy(); clients_all=get_clients()
    if objects_all.empty:
        st.info("Объектов нет.")
    else:
        client_options=["Все заказчики"]+[f"{int(r['id'])} — {r['name']}" for _,r in clients_all.iterrows()]
        sel_client=st.selectbox("Заказчик",client_options,key="transport_scope_client_v4")
        cid=None if sel_client=="Все заказчики" else int(sel_client.split(" — ")[0])
        obj_scope=objects_all if cid is None else objects_all[objects_all["client_id"].eq(cid)].copy()
        object_options=["Все объекты"]+[f"{int(r['id'])} — {r['object_name']}" for _,r in obj_scope.iterrows()]
        sel_obj=st.selectbox("Объект",object_options,key="transport_scope_object_v4")
        oid=None if sel_obj=="Все объекты" else int(sel_obj.split(" — ")[0])
        if oid is None:
            q="""SELECT oi.id,o.object_name,c.name AS client_name,oi.item_name,oi.quantity_needed AS ordered,
                         COALESCE(oi.qty_shipped,0) AS shipped,COALESCE(oi.qty_arrived,0) AS arrived,
                         GREATEST(COALESCE(oi.qty_shipped,0)-COALESCE(oi.qty_arrived,0),0) AS in_transit
                  FROM reklet.object_items oi JOIN reklet.objects o ON o.id=oi.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id
                  WHERE COALESCE(oi.qty_shipped,0)>COALESCE(oi.qty_arrived,0) AND (%s OR o.client_id=%s)
                  ORDER BY o.object_name,oi.id"""
            df=run_query(q,(cid is None,cid if cid is not None else -1),fetch=True)
        else:
            df=run_query("""SELECT oi.id,o.object_name,c.name AS client_name,oi.item_name,oi.quantity_needed AS ordered,
                               COALESCE(oi.qty_shipped,0) AS shipped,COALESCE(oi.qty_arrived,0) AS arrived,
                               GREATEST(COALESCE(oi.qty_shipped,0)-COALESCE(oi.qty_arrived,0),0) AS in_transit
                         FROM reklet.object_items oi JOIN reklet.objects o ON o.id=oi.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id
                         WHERE oi.object_id=%s AND COALESCE(oi.qty_shipped,0)>COALESCE(oi.qty_arrived,0) ORDER BY oi.id""",(oid,),fetch=True)
        if df.empty: st.info("Изделий в пути нет.")
        else:
            editor=df[["id","object_name","client_name","item_name","ordered","shipped","arrived","in_transit"]].copy(); editor["Доставить"]=0; editor.columns=["ID","Объект","Заказчик","Изделие","Заказано","Отправлено","Доставлено","В пути","Доставить на объект"]
            st.dataframe(editor.drop(columns=["Доставить на объект"]),width="stretch",hide_index=True)
            render_print_html("План транспортировки",editor.drop(columns=["Доставить на объект"]),"print_transport_v4")
            with st.form("transport_form_v4",clear_on_submit=False):
                edited=st.data_editor(editor,key="transport_editor_v4",width="stretch",hide_index=True,column_config={"ID":st.column_config.NumberColumn("ID",disabled=True),"Объект":st.column_config.TextColumn("Объект",disabled=True),"Заказчик":st.column_config.TextColumn("Заказчик",disabled=True),"Изделие":st.column_config.TextColumn("Изделие",disabled=True),"Заказано":st.column_config.NumberColumn("Заказано",disabled=True),"Отправлено":st.column_config.NumberColumn("Отправлено",disabled=True),"Доставлено":st.column_config.NumberColumn("Доставлено",disabled=True),"В пути":st.column_config.NumberColumn("В пути",disabled=True),"Доставить на объект":st.column_config.NumberColumn("Доставить на объект",min_value=0,step=1,format="%d")},disabled=["ID","Объект","Заказчик","Изделие","Заказано","Отправлено","Доставлено","В пути"])
                execute=st.form_submit_button("Выполнить",use_container_width=True)
            if execute:
                errors=[]; statements=[]
                for _,r in edited.iterrows():
                    qty=safe_int(r["Доставить на объект"]); available=safe_int(r["В пути"]); item_id=safe_int(r["ID"])
                    if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, в пути только {available}.")
                    if qty>0: statements.extend([("UPDATE reklet.object_items SET qty_shipped=GREATEST(COALESCE(qty_shipped,0)-%s,0),qty_arrived=COALESCE(qty_arrived,0)+%s WHERE id=%s",(qty,qty,item_id)),("INSERT INTO reklet.finished_goods_transactions(object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),("INSERT INTO reklet.transport_transactions(object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s",(qty,item_id))])
                if errors: st.error("Доставка не выполнена:\n"+"\n".join(errors))
                elif not statements: st.info("Укажите количество доставки.")
                else: run_transaction(statements); st.success("Доставка выполнена."); st.rerun()

    st.markdown("---"); st.subheader("Движения транспорта")
    movements=run_query("""SELECT tt.id,o.object_name,c.name AS client_name,oi.item_name,tt.operation_type,tt.quantity,tt.created_at FROM reklet.transport_transactions tt LEFT JOIN reklet.objects o ON o.id=tt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=tt.object_item_id ORDER BY tt.created_at DESC LIMIT 1000""",fetch=True)
    if not movements.empty:
        mv=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"}); st.dataframe(mv[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]],width="stretch",hide_index=True); render_print_html("Движения транспорта",mv[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]],"print_transport_movements_v4")
    else: st.info("Движений транспорта пока нет.")

elif menu == "Монтаж":

    st.header("Монтаж")
    ensure_stage_movement_tables()
    objects=get_stage_objects("installation")
    if objects.empty:
        st.success("На монтаже нет незавершённых заданий.")
    else:
        object_options=[f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _,r in objects.iterrows()]
        object_map={x:int(x.split(" — ")[0]) for x in object_options}
        selected_object=st.selectbox("Объект",object_options,key="installation_object_filter")
        object_id=object_map[selected_object]
        df=run_query("""SELECT oi.id,oi.item_name,oi.quantity_needed AS ordered,COALESCE(oi.qty_arrived,0) AS arrived,COALESCE(oi.qty_installing,0) AS installing,COALESCE(oi.qty_installed,0) AS installed FROM reklet.object_items oi WHERE oi.object_id=%s AND COALESCE(oi.qty_arrived,0)>0 ORDER BY oi.id""",(object_id,),fetch=True)
        if df.empty:
            st.success("Для выбранного объекта нет изделий, доступных для монтажа.")
        else:
            editor=df[["id","item_name","ordered","arrived","installing","installed"]].copy(); editor.columns=["ID","Изделие","Заказано","Прибыло","В монтаже","Смонтировано"]; editor["Смонтировать"]=0
            installation_print = editor[[
                "ID", "Изделие", "Заказано", "Прибыло", "В монтаже", "Смонтировано"
            ]].copy()
            render_print_html(
                f"Задание на монтаж — {selected_object}",
                installation_print,
                f"print_installation_{object_id}"
            )
            with st.form(f"installation_form_{object_id}",clear_on_submit=False):
                edited=st.data_editor(editor,key=f"installation_editor_{object_id}",width="stretch",hide_index=True,column_config={
                    "ID":st.column_config.NumberColumn("ID",disabled=True),"Изделие":st.column_config.TextColumn("Изделие",disabled=True),"Заказано":st.column_config.NumberColumn("Заказано",disabled=True),"Прибыло":st.column_config.NumberColumn("Прибыло",disabled=True),"В монтаже":st.column_config.NumberColumn("В монтаже",disabled=True),"Смонтировано":st.column_config.NumberColumn("Смонтировано",disabled=True),"Смонтировать":st.column_config.NumberColumn("Смонтировать",min_value=0,step=1,format="%d")},disabled=["ID","Изделие","Заказано","Прибыло","В монтаже","Смонтировано"])
                execute=st.form_submit_button("Выполнить",use_container_width=True)
            if execute:
                errors=[]; statements=[]
                for _,r in edited.iterrows():
                    qty=safe_int(r["Смонтировать"]); available=safe_int(r["Прибыло"]); item_id=safe_int(r["ID"])
                    if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, доступно для монтажа {available}.")
                    if qty>0:
                        statements.extend([
                            ("UPDATE reklet.object_items SET qty_arrived=GREATEST(COALESCE(qty_arrived,0)-%s,0), qty_installed=COALESCE(qty_installed,0)+%s, installation_status=CASE WHEN COALESCE(qty_installed,0)+%s>=quantity_needed THEN 'completed' ELSE 'in_progress' END, installation_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND((COALESCE(qty_installed,0)+%s)::numeric/quantity_needed*100)) ELSE 0 END WHERE id=%s",(qty,qty,qty,qty,item_id)),
                            ("INSERT INTO reklet.installation_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'complete',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                        ])
                if errors: st.error("Операция не выполнена:\n"+"\n".join(errors))
                elif not statements: st.info("Введите количество хотя бы для одной строки.")
                else: run_transaction(statements); st.success("Монтаж выполнен."); st.rerun()

    st.markdown("---"); st.subheader("Движения по монтажу")
    movements=run_query("""SELECT it.id,o.object_name,c.name AS client_name,oi.item_name,it.operation_type,it.quantity,it.created_at FROM reklet.installation_transactions it LEFT JOIN reklet.objects o ON o.id=it.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=it.object_item_id ORDER BY it.created_at DESC LIMIT 500""",fetch=True)
    if not movements.empty:
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"}); installation_movement_view = movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]].copy(); st.dataframe(installation_movement_view,width="stretch",hide_index=True); render_print_html("Движения по монтажу", installation_movement_view, "print_installation_movements")
    else: st.info("Движений монтажа пока нет.")

# ============================================================
# PAYROLL
# ============================================================

elif menu == "Зарплата":

    ensure_material_planning_tables()
    st.header("Зарплата")

    if "payroll_section" not in st.session_state:
        st.session_state.payroll_section = "Производство"

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("Зарплата производства", key="payroll_production_btn", width="stretch"):
            st.session_state.payroll_section = "Производство"
            st.rerun()
    with b2:
        if st.button("Зарплата транспортировки", key="payroll_transport_btn", width="stretch"):
            st.session_state.payroll_section = "Транспортировка"
            st.rerun()
    with b3:
        if st.button("Зарплата монтажа", key="payroll_install_btn", width="stretch"):
            st.session_state.payroll_section = "Монтаж"
            st.rerun()
    with b4:
        if st.button("Сводка по зарплате", key="payroll_summary_btn", width="stretch"):
            st.session_state.payroll_section = "Сводка"
            st.rerun()

    st.markdown("---")

    # --------------------------------------------------------
    # Двойной отбор: сначала заказчик, затем его объект.
    # Никакой общей таблицы по всем объектам здесь нет.
    # --------------------------------------------------------
    customers = run_query(
        """
        SELECT DISTINCT c.id, c.name
        FROM reklet.clients c
        JOIN reklet.objects o ON o.client_id = c.id
        JOIN reklet.object_items oi ON oi.object_id = o.id
        ORDER BY c.name
        """,
        fetch=True
    )

    section_key = st.session_state.payroll_section

    if customers.empty:
        st.info("Нет объектов с изделиями для расчёта зарплаты.")
        st.stop()

    customer_options = [f"{int(row['id'])} — {row['name']}" for _, row in customers.iterrows()]
    selected_customer = st.selectbox(
        "Заказчик",
        customer_options,
        key=f"payroll_customer_filter_{section_key}"
    )
    selected_customer_id = int(selected_customer.split(" — ")[0])

    objects_for_customer = run_query(
        """
        SELECT DISTINCT o.id, o.object_name
        FROM reklet.objects o
        JOIN reklet.object_items oi ON oi.object_id = o.id
        WHERE o.client_id = %s
        ORDER BY o.object_name
        """,
        (selected_customer_id,),
        fetch=True
    )

    if objects_for_customer.empty:
        st.info("У выбранного заказчика нет объектов с изделиями.")
        st.stop()

    object_options = [
        f"{int(row['id'])} — {row['object_name']}"
        for _, row in objects_for_customer.iterrows()
    ]
    selected_object = st.selectbox(
        "Объект",
        object_options,
        key=f"payroll_object_filter_{section_key}_{selected_customer_id}"
    )
    selected_object_id = int(selected_object.split(" — ")[0])

    st.markdown("---")

    # Данные только выбранного объекта.
    ensure_object_item_material_costs(selected_object_id)
    payroll_items = run_query(
        """
        SELECT
            oi.id AS object_item_id,
            oi.object_id,
            o.object_name,
            COALESCE(c.name, '') AS client_name,
            oi.item_name,
            COALESCE(oi.quantity_needed, 0) AS quantity_needed,
            COALESCE(o.transport_distance_km, 0) AS distance_km,
            COALESCE(SUM(
                COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit) *
                COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1) *
                COALESCE(oimc.unit_cost, m.cost_per_unit, 0)
            ), 0) AS material_cost_per_unit
        FROM reklet.object_items oi
        JOIN reklet.objects o ON o.id = oi.object_id
        LEFT JOIN reklet.clients c ON c.id = o.client_id
        LEFT JOIN reklet.product_templates pt
            ON pt.id = COALESCE(oi.product_template_id, oi.template_id)
        LEFT JOIN reklet.product_template_materials ptm
            ON ptm.product_template_id = pt.id
        LEFT JOIN reklet.materials m
            ON m.id = ptm.material_id
        LEFT JOIN reklet.object_item_material_costs oimc
            ON oimc.object_item_id = oi.id
           AND oimc.material_id = ptm.material_id
        WHERE oi.object_id = %s
        GROUP BY
            oi.id, oi.object_id, o.object_name, c.name, oi.item_name,
            oi.quantity_needed, o.transport_distance_km
        ORDER BY oi.id
        """,
        (selected_object_id,),
        fetch=True
    )

    if payroll_items.empty:
        st.info("В выбранном объекте нет изделий для расчёта зарплаты.")
        st.stop()

    numeric_cols = ["material_cost_per_unit", "distance_km", "quantity_needed"]
    for col in numeric_cols:
        payroll_items[col] = pd.to_numeric(
            payroll_items[col], errors="coerce"
        ).fillna(0.0)

    if st.session_state.payroll_section == "Производство":
        view = payroll_items.copy()
        view["Себестоимость материалов"] = view["material_cost_per_unit"]
        view["Количество"] = view["quantity_needed"]
        view["Зарплата производства"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
        )
        view = view.rename(columns={
            "object_name": "Объект",
            "client_name": "Заказчик",
            "item_name": "Изделие"
        })
        st.caption(
            "Зарплата производства рассчитывается сразу на всё количество изделий, "
            "указанное в объекте: себестоимость материалов × количество изделий × 1,50 (+50%)."
        )
        payroll_production_view = view[[
            "Изделие", "Себестоимость материалов", "Количество",
            "Зарплата производства"
        ]].copy()
        st.dataframe(payroll_production_view, width="stretch", hide_index=True)
        render_print_html(
            f"Зарплата производства — {selected_object}",
            payroll_production_view,
            f"print_payroll_production_{selected_object_id}",
            subtitle=f"Заказчик: {selected_customer.split(' — ', 1)[-1]}"
        )

    elif st.session_state.payroll_section == "Монтаж":
        view = payroll_items.copy()
        view["Себестоимость материалов"] = view["material_cost_per_unit"]
        view["Количество"] = view["quantity_needed"]
        view["Зарплата монтажа"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
        )
        view = view.rename(columns={
            "object_name": "Объект",
            "client_name": "Заказчик",
            "item_name": "Изделие"
        })
        st.caption(
            "Зарплата монтажа рассчитывается сразу на всё количество изделий, "
            "указанное в объекте: себестоимость материалов × количество изделий × 1,40 (+40%)."
        )
        payroll_installation_view = view[[
            "Изделие", "Себестоимость материалов", "Количество",
            "Зарплата монтажа"
        ]].copy()
        st.dataframe(payroll_installation_view, width="stretch", hide_index=True)
        render_print_html(
            f"Зарплата монтажа — {selected_object}",
            payroll_installation_view,
            f"print_payroll_installation_{selected_object_id}",
            subtitle=f"Заказчик: {selected_customer.split(' — ', 1)[-1]}"
        )

    elif st.session_state.payroll_section == "Транспортировка":
        view = payroll_items.copy()
        view["Себестоимость материалов"] = (
            view["material_cost_per_unit"] * view["quantity_needed"]
        )
        view["Количество"] = view["quantity_needed"]
        view["Зарплата 10%"] = view["Себестоимость материалов"] * 0.10

        st.caption(
            "Транспортировка = 10% от себестоимости материалов всех изделий объекта "
            "+ расстояние до объекта × 2. Расстояние оплачивается только один раз на объект."
        )
        payroll_transport_view = view[[
            "item_name", "Себестоимость материалов", "Количество", "Зарплата 10%"
        ]].rename(columns={"item_name": "Изделие"})
        st.dataframe(payroll_transport_view, width="stretch", hide_index=True)

        total_material_cost = float(view["Себестоимость материалов"].sum())
        salary_10 = total_material_cost * 0.10
        distance_km = float(payroll_items["distance_km"].iloc[0]) if not payroll_items.empty else 0.0
        distance_salary = distance_km * 2
        transport_total = salary_10 + distance_salary

        render_print_html(
            f"Зарплата транспортировки — {selected_object}",
            payroll_transport_view,
            f"print_payroll_transport_{selected_object_id}",
            subtitle=f"Заказчик: {selected_customer.split(' — ', 1)[-1]} | Расстояние × 2 считается один раз на объект"
        )

        summary = pd.DataFrame([{
            "Себестоимость материалов всего": total_material_cost,
            "Зарплата 10%": salary_10,
            "Расстояние, км": distance_km,
            "Расстояние × 2": distance_salary,
            "Итого зарплата транспортировки": transport_total
        }])
        st.subheader("Итого по выбранному объекту")
        st.dataframe(summary, width="stretch", hide_index=True)
        render_print_html(
            f"Итого зарплата транспортировки — {selected_object}",
            summary,
            f"print_payroll_transport_total_{selected_object_id}"
        )

    else:
        view = payroll_items.copy()
        view["Производство"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
        )
        view["Монтаж"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
        )
        view["Доставка 10%"] = (
            view["material_cost_per_unit"] * view["quantity_needed"] * 0.10
        )

        payroll_summary_items = view[["item_name", "Производство", "Монтаж", "Доставка 10%"]].rename(
            columns={"item_name": "Изделие"}
        )
        st.dataframe(payroll_summary_items, width="stretch", hide_index=True)

        total_production = float(view["Производство"].sum())
        total_installation = float(view["Монтаж"].sum())
        total_delivery_10 = float(view["Доставка 10%"].sum())
        distance_km = float(payroll_items["distance_km"].iloc[0]) if not payroll_items.empty else 0.0
        distance_salary = distance_km * 2
        total_delivery = total_delivery_10 + distance_salary
        total_salary = total_production + total_installation + total_delivery

        summary = pd.DataFrame([{
            "Производство": total_production,
            "Монтаж": total_installation,
            "Доставка 10%": total_delivery_10,
            "Расстояние, км": distance_km,
            "Расстояние × 2": distance_salary,
            "Доставка": total_delivery,
            "Итого": total_salary
        }])
        st.subheader("Итого по выбранному объекту")
        st.dataframe(summary, width="stretch", hide_index=True)
        render_print_html(
            f"Итого зарплата — {selected_object}",
            summary,
            f"print_payroll_summary_total_{selected_object_id}"
        )

    st.caption(
        "Количество берётся из object_items.quantity_needed — это плановая зарплата "
        "за всё количество изделий объекта, независимо от фактически выполненных работ."
    )


# ============================================================
# REPORTS
# ============================================================

elif menu == "Отчёты":

    ensure_material_planning_tables()
    st.header("Отчёты")

    # ========================================================
    # REPORT BUTTONS
    # ========================================================
    if "reports_section" not in st.session_state:
        st.session_state["reports_section"] = "Сводные таблицы"

    rb1, rb2, rb3, rb4, rb5, rb6 = st.columns(6)

    with rb1:
        if st.button("Сводные таблицы", key="reports_summary_btn", use_container_width=True):
            st.session_state["reports_section"] = "Сводные таблицы"; st.rerun()
    with rb2:
        if st.button("Печать документов", key="reports_print_btn", use_container_width=True):
            st.session_state["reports_section"] = "Печать документов"; st.rerun()
    with rb3:
        if st.button("Операционные отчёты", key="reports_operational_btn", use_container_width=True):
            st.session_state["reports_section"] = "Операционные отчёты"; st.rerun()
    with rb4:
        if st.button("Складские отчёты", key="reports_stock_btn", use_container_width=True):
            st.session_state["reports_section"] = "Складские отчёты"; st.rerun()
    with rb5:
        if st.button("Все движения", key="reports_movements_btn", use_container_width=True):
            st.session_state["reports_section"] = "Все движения"; st.rerun()
    with rb6:
        if st.button("Расчёт рабочего времени", key="reports_work_time_btn", use_container_width=True):
            st.session_state["reports_section"] = "Расчёт рабочего времени"; st.rerun()

    st.markdown("---")

    # ========================================================
    # COMMON COST DATA
    # ========================================================
    report_q = """
    SELECT
        o.id AS object_id,
        o.object_name,
        c.name AS client_name,
        o.address,
        COALESCE(o.transport_distance_km, 0) AS distance_km,
        oi.id AS object_item_id,
        oi.item_name,
        COALESCE(oi.quantity_needed, 0) AS quantity_needed,
        COALESCE(oi.qty_installed, 0) AS qty_installed,
        (
            COALESCE(oi.qty_arrived, 0)
            + COALESCE(oi.qty_installing, 0)
            + COALESCE(oi.qty_installed, 0)
        ) AS qty_arrived,
        (
            COALESCE(oi.qty_shipped, 0)
            + COALESCE(oi.qty_arrived, 0)
            + COALESCE(oi.qty_installing, 0)
            + COALESCE(oi.qty_installed, 0)
        ) AS qty_shipped,
        COALESCE(oi.qty_ready, 0) AS qty_ready,
        COALESCE(SUM(
            COALESCE(oimc.quantity_per_unit, ptm.quantity_per_unit, 0)
            * COALESCE(oimc.unit_cost, m.cost_per_unit, 0)
            * COALESCE(oimc.waste_coefficient, ptm.waste_coefficient, m.default_waste_coefficient, 1)
        ), 0) AS material_unit_cost
    FROM reklet.object_items oi
    JOIN reklet.objects o ON o.id = oi.object_id
    LEFT JOIN reklet.clients c ON c.id = o.client_id
    LEFT JOIN reklet.product_template_materials ptm
        ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
    LEFT JOIN reklet.materials m ON m.id = ptm.material_id
    LEFT JOIN reklet.object_item_material_costs oimc
        ON oimc.object_item_id = oi.id
       AND oimc.material_id = ptm.material_id
    GROUP BY
        o.id, o.object_name, c.name, o.address,
        o.transport_distance_km,
        oi.id, oi.item_name, oi.quantity_needed,
        oi.qty_installed, oi.qty_arrived, oi.qty_installing, oi.qty_shipped, oi.qty_ready
    ORDER BY o.object_name, oi.item_name
    """

    report_df = run_query(report_q, fetch=True)

    if not report_df.empty:
        numeric_cols = [
            "quantity_needed", "qty_installed", "qty_arrived",
            "qty_shipped", "qty_ready", "material_unit_cost", "distance_km"
        ]
        for col in numeric_cols:
            report_df[col] = pd.to_numeric(report_df[col], errors="coerce").fillna(0.0)

        report_df["Материалы"] = report_df["material_unit_cost"] * report_df["quantity_needed"]
        report_df["Производство"] = report_df["Материалы"] * 0.50
        report_df["Монтаж"] = report_df["Материалы"] * 0.40
        report_df["Доставка"] = report_df["Материалы"] * 0.10 + report_df["distance_km"] * 2
        report_df["Себестоимость"] = report_df["Материалы"] + report_df["Производство"] + report_df["Монтаж"] + report_df["Доставка"]
        report_df["Цена объекта"] = report_df["Себестоимость"] * 2
        report_df["Остаток"] = (report_df["quantity_needed"] - report_df["qty_installed"]).clip(lower=0)

    # ========================================================
    # 1. SUMMARY TABLES
    # ========================================================
    if st.session_state["reports_section"] == "Сводные таблицы":

        st.subheader("По заказчикам")

        if report_df.empty:
            st.info("Нет данных для сводной таблицы.")
        else:
            client_summary = report_df.groupby(
                ["client_name"], dropna=False
            ).agg(
                Объектов=("object_id", "nunique"),
                Изделий=("quantity_needed", "sum"),
                Материалы=("Материалы", "sum"),
                Производство=("Производство", "sum"),
                Монтаж=("Монтаж", "sum"),
                Доставка=("Доставка", "sum"),
                Себестоимость=("Себестоимость", "sum"),
                Стоимость=("Цена объекта", "sum"),
                Выполнено=("qty_installed", "sum"),
            ).reset_index()
            client_summary = client_summary.rename(columns={"client_name": "Заказчик"})
            st.dataframe(client_summary, width="stretch", hide_index=True)
            render_print_html("Сводка по заказчикам", client_summary, "print_report_clients")

        st.subheader("По объектам")

        if not report_df.empty:
            object_summary = report_df.groupby(
                ["object_id", "object_name", "client_name", "address"], dropna=False
            ).agg(
                Изделий=("quantity_needed", "sum"),
                Выполнено=("qty_installed", "sum"),
                Остаток=("Остаток", "sum"),
                Материалы=("Материалы", "sum"),
                Производство=("Производство", "sum"),
                Монтаж=("Монтаж", "sum"),
                Доставка=("Доставка", "sum"),
                Себестоимость=("Себестоимость", "sum"),
                Стоимость=("Цена объекта", "sum"),
            ).reset_index()
            object_summary.columns = [
                "№", "Объект", "Заказчик", "Адрес", "Изделий", "Выполнено",
                "Остаток", "Материалы", "Производство", "Монтаж", "Доставка",
                "Себестоимость", "Стоимость объекта"
            ]
            st.dataframe(object_summary, width="stretch", hide_index=True)
            render_print_html("Сводка по объектам", object_summary, "print_report_objects")

        st.subheader("Общие показатели")
        if not report_df.empty:
            totals = pd.DataFrame([{
                "Показатель": "Все объекты",
                "Объектов": report_df["object_id"].nunique(),
                "Изделий заказано": report_df["quantity_needed"].sum(),
                "Изделий установлено": report_df["qty_installed"].sum(),
                "Материалы": report_df["Материалы"].sum(),
                "Зарплата производства": report_df["Производство"].sum(),
                "Зарплата монтажа": report_df["Монтаж"].sum(),
                "Доставка": report_df["Доставка"].sum(),
                "Себестоимость": report_df["Себестоимость"].sum(),
                "Цена с наценкой 100%": report_df["Цена объекта"].sum(),
            }])
            st.dataframe(totals, width="stretch", hide_index=True)
            render_print_html("Общие показатели", totals, "print_report_totals")

    # ========================================================
    # 2. ALL MOVEMENTS
    # ========================================================
    elif st.session_state["reports_section"] == "Все движения":

        st.subheader("Все движения")
        st.caption("Одна строка = одна транзакция в базе данных. Фильтры можно комбинировать.")

        movements_q = """
            SELECT * FROM (
                SELECT
                    pt.created_at AS tx_date,
                    'Производство'::text AS section_name,
                    CASE pt.operation_type
                        WHEN 'completed' THEN 'Изготовлено'
                        ELSE pt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    pt.quantity::numeric AS quantity
                FROM reklet.production_transactions pt
                LEFT JOIN reklet.objects o ON o.id = pt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = pt.object_item_id

                UNION ALL

                SELECT
                    fgt.created_at AS tx_date,
                    'Склад'::text AS section_name,
                    CASE fgt.operation_type
                        WHEN 'ready' THEN 'Поступило на склад'
                        WHEN 'ship' THEN 'Отгружено'
                        WHEN 'arrive' THEN 'Доставлено на объект'
                        ELSE fgt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    fgt.quantity::numeric AS quantity
                FROM reklet.finished_goods_transactions fgt
                LEFT JOIN reklet.objects o ON o.id = fgt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = fgt.object_item_id

                UNION ALL

                SELECT
                    mt.created_at AS tx_date,
                    'Склад'::text AS section_name,
                    CASE mt.operation_type
                        WHEN 'purchase' THEN 'Приход материала'
                        WHEN 'production_transfer' THEN 'Выдано в производство'
                        ELSE mt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    NULL::text AS product_name,
                    m.name AS material_name,
                    s.name AS supplier_name,
                    mt.quantity::numeric AS quantity
                FROM reklet.material_transactions mt
                LEFT JOIN reklet.materials m ON m.id = mt.material_id
                LEFT JOIN reklet.suppliers s ON s.id = mt.supplier_id
                LEFT JOIN reklet.objects o ON o.id = mt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id

                UNION ALL

                SELECT
                    mc.created_at AS tx_date,
                    'Склад'::text AS section_name,
                    'Списано при производстве'::text AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    m.name AS material_name,
                    NULL::text AS supplier_name,
                    mc.quantity::numeric AS quantity
                FROM reklet.material_consumption mc
                LEFT JOIN reklet.objects o ON o.id=mc.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id=mc.object_item_id
                LEFT JOIN reklet.materials m ON m.id=mc.material_id

                UNION ALL

                SELECT
                    tt.created_at AS tx_date,
                    'Транспортировка'::text AS section_name,
                    CASE tt.operation_type
                        WHEN 'ship' THEN 'Отправлено'
                        WHEN 'arrive' THEN 'Доставлено'
                        ELSE tt.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    tt.quantity::numeric AS quantity
                FROM reklet.transport_transactions tt
                LEFT JOIN reklet.objects o ON o.id = tt.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = tt.object_item_id

                UNION ALL

                SELECT
                    it.created_at AS tx_date,
                    'Монтаж'::text AS section_name,
                    CASE it.operation_type
                        WHEN 'complete' THEN 'Установлено'
                        ELSE it.operation_type
                    END AS operation_name,
                    c.name AS client_name,
                    o.object_name,
                    oi.item_name AS product_name,
                    NULL::text AS material_name,
                    NULL::text AS supplier_name,
                    it.quantity::numeric AS quantity
                FROM reklet.installation_transactions it
                LEFT JOIN reklet.objects o ON o.id = it.object_id
                LEFT JOIN reklet.clients c ON c.id = o.client_id
                LEFT JOIN reklet.object_items oi ON oi.id = it.object_item_id
            ) movements
            ORDER BY tx_date DESC
        """

        movements = run_query(movements_q, fetch=True)

        if movements.empty:
            st.info("Транзакций в базе данных пока нет.")
        else:
            def movement_options(column, first_label="Все"):
                vals = (
                    movements[column]
                    .fillna("")
                    .astype(str)
                    .replace("", pd.NA)
                    .dropna()
                    .drop_duplicates()
                    .sort_values()
                    .tolist()
                )
                return [first_label] + vals

            f1, f2, f3 = st.columns(3)
            f4, f5, f6 = st.columns(3)

            with f1:
                movement_client = st.selectbox(
                    "Заказчик", movement_options("client_name"), key="movement_filter_client"
                )
            with f2:
                movement_object = st.selectbox(
                    "Объект", movement_options("object_name"), key="movement_filter_object"
                )
            with f3:
                movement_section = st.selectbox(
                    "Раздел",
                    ["Все", "Производство", "Склад", "Транспортировка", "Монтаж"],
                    key="movement_filter_section"
                )
            with f4:
                movement_supplier = st.selectbox(
                    "Поставщик", movement_options("supplier_name"), key="movement_filter_supplier"
                )
            with f5:
                movement_material = st.selectbox(
                    "Материал", movement_options("material_name"), key="movement_filter_material"
                )
            with f6:
                movement_product = st.selectbox(
                    "Изделие", movement_options("product_name"), key="movement_filter_product"
                )

            filtered = movements.copy()

            if movement_client != "Все":
                filtered = filtered[filtered["client_name"].fillna("").astype(str) == movement_client]
            if movement_object != "Все":
                filtered = filtered[filtered["object_name"].fillna("").astype(str) == movement_object]
            if movement_section != "Все":
                filtered = filtered[filtered["section_name"] == movement_section]
            if movement_supplier != "Все":
                filtered = filtered[filtered["supplier_name"].fillna("").astype(str) == movement_supplier]
            if movement_material != "Все":
                filtered = filtered[filtered["material_name"].fillna("").astype(str) == movement_material]
            if movement_product != "Все":
                filtered = filtered[filtered["product_name"].fillna("").astype(str) == movement_product]

            view = filtered.rename(columns={
                "tx_date": "Дата",
                "section_name": "Раздел",
                "operation_name": "Действие",
                "client_name": "Заказчик",
                "object_name": "Объект",
                "product_name": "Изделие",
                "material_name": "Материал",
                "supplier_name": "Поставщик",
                "quantity": "Количество",
            })[[
                "Дата", "Раздел", "Действие", "Заказчик", "Объект",
                "Изделие", "Материал", "Поставщик", "Количество"
            ]]

            st.dataframe(view, width="stretch", hide_index=True)
            st.caption(f"Показано транзакций: {len(view)} из {len(movements)}")
            render_print_html("Все движения", view, "print_all_movements")

    # ========================================================
    # 3. PRINT DOCUMENTS
    # ========================================================
    elif st.session_state["reports_section"] == "Печать документов":

        st.subheader("Готовые документы")

        document_type = st.selectbox(
            "Документ",
            [
                "Выверка по объекту",
                "Выверка по заказчику",
                "Смета объекта",
                "Акт сдачи-приёмки работ",
                "Приходная накладная",
                "Расходная накладная",
            ],
            key="print_document_type"
        )

        # ---------- Reusable printable HTML ----------
        def printable_html(title, body_html):
            return f"""
            <!doctype html>
            <html><head><meta charset='utf-8'>
            <title>{escape(title)}</title>
            <style>
            body {{ font-family: Arial, sans-serif; margin: 35px; color: #111; }}
            h1 {{ font-size: 22px; margin-bottom: 8px; }}
            h2 {{ font-size: 17px; margin-top: 22px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
            th, td {{ border: 1px solid #777; padding: 6px 8px; text-align: left; }}
            th {{ background: #eee; }}
            .right {{ text-align: right; }}
            .sign {{ margin-top: 45px; display: flex; justify-content: space-between; }}
            </style></head><body>
            <h1>{escape(title)}</h1>
            {body_html}
            </body></html>
            """

        if document_type in ["Выверка по объекту", "Смета объекта", "Акт сдачи-приёмки работ"]:
            if report_df.empty:
                st.info("Нет объектов для формирования документа.")
            else:
                object_options = [
                    f"{int(r['object_id'])} — {r['object_name']}"
                    for _, r in report_df[["object_id", "object_name"]].drop_duplicates().iterrows()
                ]
                selected_object = st.selectbox("Объект", object_options, key="print_object")
                selected_object_id = int(selected_object.split(" — ")[0])
                doc = report_df[report_df["object_id"] == selected_object_id].copy()

                object_name = str(doc.iloc[0]["object_name"])
                client_name = str(doc.iloc[0]["client_name"] or "")
                address = str(doc.iloc[0]["address"] or "")

                if document_type == "Выверка по объекту":
                    view = doc[["item_name", "quantity_needed", "qty_ready", "qty_shipped", "qty_arrived", "qty_installed"]].copy()
                    view.columns = ["Изделие", "Запланировано", "Готово", "Отправлено", "Доставлено", "Выполнено"]
                    view["Остаток"] = (view["Запланировано"] - view["Выполнено"]).clip(lower=0)
                    st.dataframe(view, width="stretch", hide_index=True)
                    body = f"<p><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += view.to_html(index=False)
                    body += "<div class='sign'><span>Представитель заказчика: __________________</span><span>Представитель исполнителя: __________________</span></div>"
                    title = f"Выверка по объекту — {object_name}"

                elif document_type == "Смета объекта":
                    estimate = doc.groupby("item_name", as_index=False).agg(
                        Количество=("quantity_needed", "sum"),
                        Материалы=("Материалы", "sum"),
                        Производство=("Производство", "sum"),
                        Монтаж=("Монтаж", "sum"),
                        Доставка=("Доставка", "sum"),
                        Себестоимость=("Себестоимость", "sum"),
                        Стоимость=("Цена объекта", "sum"),
                    )
                    st.dataframe(estimate, width="stretch", hide_index=True)
                    totals = estimate[["Материалы", "Производство", "Монтаж", "Доставка", "Себестоимость", "Стоимость"]].sum()
                    st.write(f"**Итого материалов:** {money(totals['Материалы'])}")
                    st.write(f"**Итого себестоимость:** {money(totals['Себестоимость'])}")
                    st.write(f"**Итоговая стоимость с наценкой 100%:** {money(totals['Стоимость'])}")
                    body = f"<p><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += estimate.to_html(index=False)
                    body += f"<h2>Итого</h2><p>Материалы: {money(totals['Материалы'])}<br>Производство: {money(totals['Производство'])}<br>Монтаж: {money(totals['Монтаж'])}<br>Доставка: {money(totals['Доставка'])}<br>Себестоимость: {money(totals['Себестоимость'])}<br><b>Итоговая стоимость: {money(totals['Стоимость'])}</b></p>"
                    body += "<div class='sign'><span>Согласовано: __________________</span><span>Дата: __________________</span></div>"
                    title = f"Смета объекта — {object_name}"

                else:
                    planned = float(doc["quantity_needed"].sum())
                    completed = float(doc["qty_installed"].sum())
                    remaining = max(planned - completed, 0)
                    intermediate = remaining > 0
                    act_title = "Промежуточный акт сдачи-приёмки работ" if intermediate else "Акт сдачи-приёмки работ"
                    st.subheader(act_title)
                    st.write(f"Запланировано: **{planned:g} шт.**")
                    st.write(f"Выполнено: **{completed:g} шт.**")
                    st.write(f"Остаток: **{remaining:g} шт.**")
                    view = doc[["item_name", "quantity_needed", "qty_installed"]].copy()
                    view.columns = ["Изделие", "Запланировано", "Выполнено"]
                    view["Остаток"] = (view["Запланировано"] - view["Выполнено"]).clip(lower=0)
                    st.dataframe(view, width="stretch", hide_index=True)
                    body = f"<h2>{escape(act_title)}</h2><p><b>Объект:</b> {escape(object_name)}<br><b>Заказчик:</b> {escape(client_name)}<br><b>Адрес:</b> {escape(address)}</p>"
                    body += view.to_html(index=False)
                    body += f"<p><b>Запланировано:</b> {planned:g} шт.<br><b>Выполнено:</b> {completed:g} шт.<br><b>Остаток:</b> {remaining:g} шт.</p>"
                    body += "<div class='sign'><span>Заказчик: __________________</span><span>Исполнитель: __________________</span></div>"
                    title = f"{act_title} — {object_name}"

                st.download_button(
                    "Печать HTML",
                    data=printable_html(title, body),
                    file_name=title.replace(" ", "_") + ".html",
                    mime="text/html",
                    key="download_object_document"
                )
                st.caption("HTML-документ можно открыть в браузере и распечатать или сохранить в PDF через печать браузера.")

        elif document_type == "Выверка по заказчику":
            clients = report_df["client_name"].fillna("").astype(str).drop_duplicates().sort_values().tolist()
            if not clients:
                st.info("Нет заказчиков.")
            else:
                selected_client = st.selectbox("Заказчик", clients, key="print_client")
                doc = report_df[report_df["client_name"].fillna("").astype(str) == selected_client].copy()
                summary = doc.groupby(["object_id", "object_name"], as_index=False).agg(
                    Изделий=("quantity_needed", "sum"),
                    Выполнено=("qty_installed", "sum"),
                    Материалы=("Материалы", "sum"),
                    Производство=("Производство", "sum"),
                    Монтаж=("Монтаж", "sum"),
                    Доставка=("Доставка", "sum"),
                    Себестоимость=("Себестоимость", "sum"),
                    Стоимость=("Цена объекта", "sum"),
                )
                st.dataframe(summary, width="stretch", hide_index=True)
                body = f"<p><b>Заказчик:</b> {escape(selected_client)}</p>" + summary.to_html(index=False)
                body += "<div class='sign'><span>Представитель заказчика: __________________</span><span>Представитель исполнителя: __________________</span></div>"
                title = f"Выверка по заказчику — {selected_client}"
                st.download_button("Печать HTML", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_client_document")

        elif document_type in ["Приходная накладная", "Расходная накладная"]:
            if document_type == "Приходная накладная":
                suppliers_for_print = run_query(
                    "SELECT id, name FROM reklet.suppliers ORDER BY name",
                    fetch=True
                )
                supplier_options = ["Все поставщики"] + (
                    suppliers_for_print["name"].fillna("").astype(str).tolist()
                    if not suppliers_for_print.empty else []
                )
                selected_supplier = st.selectbox("Поставщик", supplier_options, key="print_receipt_supplier")
                invoice_q = """
                    SELECT mt.created_at AS "Дата", s.name AS "Поставщик", m.name AS "Материал",
                           u.name AS "Единица", mt.quantity AS "Количество",
                           mt.unit_price AS "Цена",
                           (mt.quantity * COALESCE(mt.unit_price,0)) AS "Сумма"
                    FROM reklet.material_transactions mt
                    LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id
                    JOIN reklet.materials m ON m.id=mt.material_id
                    LEFT JOIN reklet.units u ON u.id=m.unit_id
                    WHERE mt.operation_type='purchase' AND mt.transaction_type='IN'
                """
                params=[]
                if selected_supplier != "Все поставщики":
                    invoice_q += " AND s.name=%s"
                    params.append(selected_supplier)
                invoice_q += " ORDER BY mt.created_at DESC LIMIT 500"
                invoice_df = run_query(invoice_q, tuple(params), fetch=True)
                if invoice_df.empty:
                    st.info("Приходных движений нет.")
                else:
                    st.dataframe(invoice_df, width="stretch", hide_index=True)
                    body = invoice_df.to_html(index=False)
                    title = "Приходная накладная" if selected_supplier == "Все поставщики" else f"Приходная накладная — {selected_supplier}"
                    st.download_button("Печать HTML", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_purchase_invoice")

            else:
                objects_for_print = run_query(
                    "SELECT id, object_name FROM reklet.objects ORDER BY object_name",
                    fetch=True
                )
                object_options = ["Все объекты"] + (
                    [f"{int(r['id'])} — {r['object_name']}" for _, r in objects_for_print.iterrows()]
                    if not objects_for_print.empty else []
                )
                selected_issue_object = st.selectbox("Объект", object_options, key="print_issue_object")
                issue_q = """
                    SELECT mt.created_at AS "Дата", o.object_name AS "Объект", c.name AS "Заказчик",
                           m.name AS "Материал", u.name AS "Единица", mt.quantity AS "Количество",
                           mt.unit_price AS "Цена",
                           (mt.quantity * COALESCE(mt.unit_price,0)) AS "Сумма"
                    FROM reklet.material_transactions mt
                    JOIN reklet.materials m ON m.id=mt.material_id
                    LEFT JOIN reklet.units u ON u.id=m.unit_id
                    LEFT JOIN reklet.objects o ON o.id=mt.object_id
                    LEFT JOIN reklet.clients c ON c.id=o.client_id
                    WHERE mt.operation_type='production_transfer' AND mt.transaction_type='OUT'
                """
                params=[]
                if selected_issue_object != "Все объекты":
                    issue_q += " AND o.id=%s"
                    params.append(int(selected_issue_object.split(" — ")[0]))
                issue_q += " ORDER BY mt.created_at DESC LIMIT 500"
                invoice_df = run_query(issue_q, tuple(params), fetch=True)
                if invoice_df.empty:
                    st.info("Расходных движений нет.")
                else:
                    st.dataframe(invoice_df, width="stretch", hide_index=True)
                    body = invoice_df.to_html(index=False)
                    title = "Расходная накладная" if selected_issue_object == "Все объекты" else f"Расходная накладная — {selected_issue_object}"
                    st.download_button("Печать HTML", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_issue_invoice")

    # ========================================================
    # WORK TIME CALCULATIONS
    # ========================================================
    elif st.session_state["reports_section"] == "Расчёт рабочего времени":
        ensure_task_three_tables()
        st.subheader("Расчёт рабочего времени")
        clients_w=get_clients(); objects_w=get_objects().sort_values("id",ascending=False).copy()
        if clients_w.empty or objects_w.empty:
            st.info("Недостаточно данных для расчёта.")
        else:
            st.markdown("### Новый расчёт")
            client_labels=["Все заказчики"]+[f"{int(r['id'])} — {r['name']}" for _,r in clients_w.iterrows()]
            wc=st.selectbox("Заказчик",client_labels,key="work_time_new_client_v5")
            wcid=None if wc=="Все заказчики" else int(wc.split(" — ")[0])
            wobjs=objects_w if wcid is None else objects_w[objects_w["client_id"].eq(wcid)].copy()
            if wobjs.empty:
                st.info("У выбранного заказчика объектов нет.")
            else:
                wol=[f"{int(r['id'])} — {r['object_name']}" for _,r in wobjs.iterrows()]
                wo=st.selectbox("Объект",wol,key="work_time_new_object_v5")
                wo_id=int(wo.split(" — ")[0])
                if st.button("Рассчитать рабочее время",key=f"calculate_work_time_v5_{wo_id}",type="primary",use_container_width=True):
                    items=get_object_cost_per_unit_map(wo_id)
                    obj=objects_w[objects_w["id"].eq(wo_id)].iloc[0]
                    item_payload=[]; production_total=0.0; installation_total=0.0
                    for _,ir in items.iterrows():
                        qty=safe_int(ir["quantity_needed"]); unit_cost=safe_float(ir["unit_cost"])
                        if qty<=0: continue
                        base,cls,mult,pmin,imin=calculate_production_time(unit_cost,qty)
                        production_total += pmin; installation_total += imin
                        item_payload.append((safe_int(ir["object_item_id"]),str(ir["item_name"] or ""),qty,unit_cost,base,cls,mult,pmin,imin))
                    loading,road,unloading,transport_total=calculate_transport_time(safe_float(obj.get("transport_distance_km")))
                    total=production_total+installation_total+transport_total
                    conn=get_connection(); cur=conn.cursor()
                    try:
                        cur.execute("INSERT INTO reklet.work_time_calculations(object_id,distance_km,loading_minutes,road_minutes,unloading_minutes,production_minutes,installation_minutes,transport_minutes,total_minutes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",(wo_id,safe_float(obj.get("transport_distance_km")),loading,road,unloading,production_total,installation_total,transport_total,total))
                        calc_id=safe_int(cur.fetchone()[0])
                        for it in item_payload:
                            cur.execute("INSERT INTO reklet.work_time_calculation_items(calculation_id,object_item_id,item_name,quantity,unit_cost,base_production_minutes,quantity_class,time_multiplier,production_minutes,installation_minutes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(calc_id,*it))
                        conn.commit()
                    except Exception:
                        conn.rollback(); raise
                    finally: cur.close()
                    st.success(f"Расчёт №{calc_id} сохранён."); st.rerun()

            st.markdown("### История расчётов")
            hc1,hc2=st.columns(2)
            hist_clients=["Все заказчики"]+[f"{int(r['id'])} — {r['name']}" for _,r in clients_w.iterrows()]
            with hc1: hf_client=st.selectbox("Отбор по заказчику",hist_clients,key="work_time_history_client_v5")
            hf_cid=None if hf_client=="Все заказчики" else int(hf_client.split(" — ")[0])
            hist=run_query("""SELECT wc.id,wc.object_id,wc.calculated_at,c.name AS client_name,o.object_name,wc.distance_km,wc.production_minutes,wc.transport_minutes,wc.installation_minutes,wc.total_minutes FROM reklet.work_time_calculations wc JOIN reklet.objects o ON o.id=wc.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id ORDER BY wc.calculated_at DESC LIMIT 1000""",fetch=True)
            if hf_cid is not None and not hist.empty: hist=hist[hist["object_id"].isin(objects_w[objects_w["client_id"].eq(hf_cid)]["id"].tolist())].copy()
            hist_obj_options=["Все объекты"]+(hist.apply(lambda r:f"{safe_int(r['object_id'])} — {r['object_name']}",axis=1).drop_duplicates().tolist() if not hist.empty else [])
            with hc2: hf_obj=st.selectbox("Отбор по объекту",hist_obj_options,key="work_time_history_object_v5")
            if hf_obj!="Все объекты" and not hist.empty:
                hf_oid=int(hf_obj.split(" — ")[0]); hist=hist[hist["object_id"].eq(hf_oid)].copy()
            if hist.empty:
                st.info("Сохранённых расчётов по выбранному отбору нет.")
            else:
                hv=hist.copy(); hv["Всего, ч"]=(pd.to_numeric(hv["total_minutes"],errors="coerce").fillna(0)/60).round(2)
                hv=hv.rename(columns={"id":"№","calculated_at":"Когда","client_name":"Заказчик","object_name":"Объект","distance_km":"Км","production_minutes":"Производство, мин","transport_minutes":"Транспорт, мин","installation_minutes":"Монтаж, мин","total_minutes":"Всего, мин"})
                display_cols=["№","Когда","Заказчик","Объект","Км","Производство, мин","Транспорт, мин","Монтаж, мин","Всего, мин","Всего, ч"]
                st.dataframe(hv[display_cols],width="stretch",hide_index=True)
                render_print_html("История расчётов рабочего времени",hv[display_cols],"print_work_time_history_v5")

                hist_labels={f"№{int(r['№'])} — {r['Объект']} — {r['Когда']}":int(r['№']) for _,r in hv.iterrows()}
                st.markdown("#### Детализация")
                chosen=st.selectbox("Расчёт",list(hist_labels.keys()),key="work_time_detail_select_v5")
                chosen_id=hist_labels[chosen]
                chosen_header=hist[hist["id"].eq(chosen_id)].iloc[0]
                with st.expander("▶ Подробно",expanded=True):
                    st.dataframe(pd.DataFrame([{
                        "Расчёт №":chosen_id,"Дата":chosen_header["calculated_at"],"Заказчик":chosen_header["client_name"],"Объект":chosen_header["object_name"],
                        "Расстояние, км":chosen_header["distance_km"],"Погрузка, ч":safe_float(chosen_header["loading_minutes"])/60,
                        "Дорога, ч":safe_float(chosen_header["road_minutes"])/60,"Разгрузка, ч":safe_float(chosen_header["unloading_minutes"])/60,
                        "Производство, ч":safe_float(chosen_header["production_minutes"])/60,"Монтаж, ч":safe_float(chosen_header["installation_minutes"])/60,
                        "Транспорт, ч":safe_float(chosen_header["transport_minutes"])/60,"Всего, ч":safe_float(chosen_header["total_minutes"])/60
                    }]),width="stretch",hide_index=True)
                    details=run_query("""SELECT item_name AS "Изделие",quantity AS "Количество",unit_cost AS "Себестоимость изделия",quantity_class AS "Класс",base_production_minutes AS "База, мин",time_multiplier AS "Коэффициент",production_minutes AS "Производство, мин",installation_minutes AS "Монтаж, мин" FROM reklet.work_time_calculation_items WHERE calculation_id=%s ORDER BY id""",(chosen_id,),fetch=True)
                    if not details.empty: st.dataframe(details,width="stretch",hide_index=True); render_print_html(f"Расчёт рабочего времени №{chosen_id}",details,f"print_work_time_detail_v5_{chosen_id}")

                # Optional comparison: the user can choose two stored calculations.
                compare_labels=list(hist_labels.keys())
                if len(compare_labels)>=2:
                    c1,c2=st.columns(2)
                    with c1: ca=st.selectbox("Было — расчёт",compare_labels,key="work_time_compare_a_v5")
                    with c2: cb=st.selectbox("Стало — расчёт",compare_labels,index=1,key="work_time_compare_b_v5")
                    ida=hist_labels[ca]; idb=hist_labels[cb]
                    ra=hist[hist["id"].eq(ida)].iloc[0]; rb=hist[hist["id"].eq(idb)].iloc[0]
                    compare=pd.DataFrame([
                        {"Показатель":"Производство, ч","Было":safe_float(ra["production_minutes"])/60,"Стало":safe_float(rb["production_minutes"])/60,"Разница":(safe_float(rb["production_minutes"])-safe_float(ra["production_minutes"]))/60},
                        {"Показатель":"Транспорт, ч","Было":safe_float(ra["transport_minutes"])/60,"Стало":safe_float(rb["transport_minutes"])/60,"Разница":(safe_float(rb["transport_minutes"])-safe_float(ra["transport_minutes"]))/60},
                        {"Показатель":"Монтаж, ч","Было":safe_float(ra["installation_minutes"])/60,"Стало":safe_float(rb["installation_minutes"])/60,"Разница":(safe_float(rb["installation_minutes"])-safe_float(ra["installation_minutes"]))/60},
                        {"Показатель":"Всего, ч","Было":safe_float(ra["total_minutes"])/60,"Стало":safe_float(rb["total_minutes"])/60,"Разница":(safe_float(rb["total_minutes"])-safe_float(ra["total_minutes"]))/60},
                    ])
                    st.subheader("Сравнение расчётов")
                    st.dataframe(compare.round(2),width="stretch",hide_index=True)
                    render_print_html("Сравнение расчётов рабочего времени",compare.round(2),"print_work_time_compare_v5")


    # ========================================================
    # 3. OPERATIONAL REPORTS
    # ========================================================
    elif st.session_state["reports_section"] == "Операционные отчёты":
        st.subheader("Операционные отчёты")
        operational = st.selectbox(
            "Отчёт",
            [
                "Карточка объекта",
                "Отчёт по производству",
                "Готово, но не отправлено",
                "Отчёт по доставкам",
                "Отчёт по монтажу",
                "Незавершённые объекты",
            ],
            key="operational_report"
        )

        if report_df.empty:
            st.info("Нет данных.")
        elif operational == "Карточка объекта":
            options = [f"{int(r['object_id'])} — {r['object_name']}" for _, r in report_df[["object_id","object_name"]].drop_duplicates().iterrows()]
            selected = st.selectbox("Объект", options, key="operational_object")
            oid = int(selected.split(" — ")[0])
            card = report_df[report_df["object_id"] == oid]
            operational_view = card[["item_name","quantity_needed","qty_installed","qty_ready","qty_shipped","qty_arrived"]].rename(columns={"item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено","qty_ready":"Готово","qty_shipped":"Отправлено","qty_arrived":"Доставлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html(f"Карточка объекта — {selected}", operational_view, "print_operational_card")
        elif operational == "Отчёт по производству":
            operational_view = report_df.groupby(["object_name","client_name"], as_index=False).agg(Заказано=("quantity_needed", "sum"), Готово=("qty_ready", "sum"), Доставлено=("qty_arrived", "sum"), Установлено=("qty_installed", "sum"))
            operational_view = operational_view.rename(columns={"object_name":"Объект","client_name":"Заказчик"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Отчёт по производству", operational_view, "print_operational_production")
        elif operational == "Готово, но не отправлено":
            operational_view = report_df[report_df["qty_ready"] > report_df["qty_shipped"]][["object_name","client_name","item_name","qty_ready","qty_shipped"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_ready":"Готово","qty_shipped":"Отправлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Готово, но не отправлено", operational_view, "print_operational_ready")
        elif operational == "Отчёт по доставкам":
            operational_view = report_df[["object_name","client_name","item_name","qty_shipped","qty_arrived"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_shipped":"Отправлено","qty_arrived":"Доставлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Отчёт по доставкам", operational_view, "print_operational_deliveries")
        elif operational == "Отчёт по монтажу":
            operational_view = report_df[["object_name","client_name","item_name","quantity_needed","qty_installed"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Отчёт по монтажу", operational_view, "print_operational_installation")
        else:
            incomplete = report_df[report_df["qty_installed"] < report_df["quantity_needed"]]
            operational_view = incomplete.groupby(["object_id","object_name","client_name"], as_index=False).agg(Запланировано=("quantity_needed","sum"), Выполнено=("qty_installed","sum"), Остаток=("Остаток","sum"))
            operational_view = operational_view.rename(columns={"object_id":"№","object_name":"Объект","client_name":"Заказчик"})
            st.dataframe(operational_view, width="stretch", hide_index=True)
            render_print_html("Незавершённые объекты", operational_view, "print_operational_incomplete")

    # ========================================================
    # 4. STOCK REPORTS
    # ========================================================
    else:
        st.subheader("Складские отчёты")
        stock_report = st.selectbox(
            "Отчёт",
            ["Остатки материалов", "Материалы с низким остатком", "Потребность материалов по незавершённым объектам", "Перерасход материала", "Удалённые материалы"],
            key="stock_report"
        )
        stock = run_query("""
            SELECT m.id, m.name AS material, u.name AS unit,
                   COALESCE(m.stock_quantity,0) AS stock_quantity,
                   COALESCE(m.cost_per_unit,0) AS cost_per_unit,
                   COALESCE(m.stock_quantity,0)*COALESCE(m.cost_per_unit,0) AS stock_value
            FROM reklet.materials m
            LEFT JOIN reklet.units u ON u.id=m.unit_id
            ORDER BY m.name
        """, fetch=True)
        if stock_report == "Остатки материалов":
            stock_view = stock.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"})
            st.dataframe(stock_view, width="stretch", hide_index=True)
            render_print_html("Остатки материалов", stock_view, "print_stock_balances")
        elif stock_report == "Материалы с низким остатком":
            low = stock[stock["stock_quantity"] <= 10].copy()
            st.dataframe(low.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        elif stock_report == "Перерасход материала":
            over=run_query("""WITH base AS (SELECT oi.object_id,ptm.material_id,SUM(COALESCE(oi.quantity_needed,0)*COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)) base_need FROM reklet.object_items oi JOIN reklet.product_template_materials ptm ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id) LEFT JOIN reklet.object_item_material_costs oimc ON oimc.object_item_id=oi.id AND oimc.material_id=ptm.material_id GROUP BY oi.object_id,ptm.material_id), issued AS (SELECT object_id,material_id,SUM(quantity) qty FROM reklet.material_transactions WHERE operation_type='production_transfer' AND transaction_type='OUT' GROUP BY object_id,material_id), consumed AS (SELECT object_id,material_id,SUM(quantity) qty FROM reklet.material_consumption GROUP BY object_id,material_id), pw AS (SELECT object_id,material_id,SUM(quantity) qty FROM reklet.material_waste_transactions WHERE source_type='production' GROUP BY object_id,material_id) SELECT c.name AS "Заказчик",o.object_name AS "Объект",m.name AS "Материал",u.name AS "Единица",COALESCE(b.base_need,0) AS "По спецификации без обреза",COALESCE(i.qty,0) AS "Выдано производству",GREATEST(COALESCE(i.qty,0)-COALESCE(co.qty,0)-COALESCE(pw.qty,0),0) AS "Остаток на производстве",GREATEST(COALESCE(co.qty,0)+COALESCE(pw.qty,0),0) AS "Фактически израсходовано с учётом обреза и списаний",GREATEST(COALESCE(i.qty,0)-COALESCE(b.base_need,0),0) AS "Перерасход" FROM reklet.objects o LEFT JOIN reklet.clients c ON c.id=o.client_id JOIN (SELECT object_id,material_id FROM base UNION SELECT object_id,material_id FROM issued UNION SELECT object_id,material_id FROM consumed UNION SELECT object_id,material_id FROM pw) keys ON keys.object_id=o.id LEFT JOIN base b ON b.object_id=keys.object_id AND b.material_id=keys.material_id LEFT JOIN issued i ON i.object_id=keys.object_id AND i.material_id=keys.material_id LEFT JOIN consumed co ON co.object_id=keys.object_id AND co.material_id=keys.material_id LEFT JOIN pw ON pw.object_id=keys.object_id AND pw.material_id=keys.material_id JOIN reklet.materials m ON m.id=keys.material_id LEFT JOIN reklet.units u ON u.id=m.unit_id ORDER BY o.object_name,m.name""",fetch=True)
            st.dataframe(over,width="stretch",hide_index=True); render_print_html("Перерасход материала",over,"print_material_overrun_v5")
        elif stock_report == "Удалённые материалы":
            deleted=run_query("""SELECT mw.created_at AS "Дата",m.name AS "Материал",CASE mw.source_type WHEN 'stock' THEN 'Склад' ELSE 'Производство' END AS "Источник",o.object_name AS "Объект",mw.quantity AS "Количество",mw.unit_cost_snapshot AS "Цена",mw.reason AS "Причина" FROM reklet.material_waste_transactions mw JOIN reklet.materials m ON m.id=mw.material_id LEFT JOIN reklet.objects o ON o.id=mw.object_id ORDER BY mw.created_at DESC LIMIT 1000""",fetch=True); st.dataframe(deleted,width="stretch",hide_index=True); render_print_html("Удалённые материалы",deleted,"print_deleted_materials_v4")
        else:
            need = run_query("""
                SELECT o.object_name, c.name AS client_name, oi.item_name,
                       m.name AS material,
                       (oi.quantity_needed
                         * COALESCE(oimc.quantity_per_unit,ptm.quantity_per_unit,0)
                         * COALESCE(oimc.waste_coefficient,ptm.waste_coefficient,m.default_waste_coefficient,1)) AS required_quantity,
                       COALESCE(m.stock_quantity,0) AS stock_quantity
                FROM reklet.object_items oi
                JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                JOIN reklet.product_template_materials ptm ON ptm.product_template_id=oi.product_template_id
                JOIN reklet.materials m ON m.id=ptm.material_id
                LEFT JOIN reklet.object_item_material_costs oimc
                  ON oimc.object_item_id=oi.id
                 AND oimc.material_id=ptm.material_id
                WHERE COALESCE(oi.qty_installed,0) < COALESCE(oi.quantity_needed,0)
                ORDER BY o.object_name, oi.item_name, m.name
            """, fetch=True)
            stock_need_view = need.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","material":"Материал","required_quantity":"Требуется","stock_quantity":"На складе"})
            st.dataframe(stock_need_view, width="stretch", hide_index=True)
            render_print_html("Потребность материалов по незавершённым объектам", stock_need_view, "print_stock_object_need")




# ============================================================
# REPORTS
# ============================================================
