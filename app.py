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
            o.address
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

if menu == "Клиенты":

    st.header("Клиенты")

    client_sub = render_button_nav(
        ["Клиенты", "Добавить клиента", "Корректировка"],
        "clients_navigation",
        "clients_nav",
        columns_per_row=3
    )

    clients = get_clients()

    if client_sub in ("Клиенты", "Корректировка"):
        client_options = ["Все клиенты"] + (
            clients["name"].fillna("").astype(str).str.strip().loc[lambda x: x != ""].sort_values().unique().tolist()
            if not clients.empty else []
        )
        selected_client = st.selectbox(
            "Отбор по клиенту",
            client_options,
            key=f"client_filter_{client_sub}"
        )
        if selected_client != "Все клиенты":
            clients = clients[clients["name"].fillna("").astype(str).str.strip().eq(selected_client)].copy()

    if client_sub == "Клиенты":
        st.subheader("Перечень клиентов")
        if clients.empty:
            st.info("Клиентов нет.")
        else:
            display = clients[["id", "name", "phone", "address", "email", "website", "notes"]].copy()
            display.columns = ["ID", "Наименование", "Телефон", "Адрес", "Имейл", "Веб-сайт", "Примечание"]
            st.dataframe(display, width="stretch", hide_index=True)

    elif client_sub == "Добавить клиента":
        st.subheader("Добавить клиента")
        with st.form("add_client_form"):
            name = st.text_input("Наименование")
            phone = st.text_input("Телефон")
            address = st.text_input("Адрес")
            email = st.text_input("Имейл")
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
        st.subheader("Корректировка клиента")
        if clients.empty:
            st.info("Нет клиентов для корректировки.")
        else:
            client_map = {f"{row['id']} — {row['name']}": int(row['id']) for _, row in clients.iterrows()}
            selected_label = st.selectbox("Клиент", list(client_map.keys()), key="edit_client_select")
            client_id = client_map[selected_label]
            row = clients[clients["id"] == client_id].iloc[0]

            with st.form("edit_client_form"):
                name = st.text_input("Наименование", value=str(row["name"] or ""))
                phone = st.text_input("Телефон", value=str(row["phone"] or ""))
                address = st.text_input("Адрес", value=str(row["address"] or ""))
                email = st.text_input("Имейл", value=str(row["email"] or ""))
                website = st.text_input("Веб-сайт", value=str(row["website"] or ""))
                notes = st.text_area("Примечание", value=str(row["notes"] or ""))
                save = st.form_submit_button("Сохранить изменения")
                if save:
                    if not name.strip():
                        st.warning("Наименование не может быть пустым.")
                    else:
                        run_query(
                            """
                            UPDATE reklet.clients
                            SET name=%s, phone=%s, address=%s, email=%s, website=%s, notes=%s, contact_info=%s
                            WHERE id=%s
                            """,
                            (name.strip(), phone.strip() or None, address.strip() or None,
                             email.strip() or None, website.strip() or None, notes.strip() or None,
                             phone.strip() or None, client_id)
                        )
                        st.success("Данные клиента изменены.")
                        st.rerun()

            st.markdown("---")
            st.warning("Удаление клиента необратимо. Клиент, используемый объектами, не может быть удалён.")
            confirm = st.checkbox("Я подтверждаю удаление выбранного клиента.", key="confirm_delete_client")
            if st.button("Удалить клиента", key="delete_client_button", disabled=not confirm):
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
            "Список объектов",
            "Добавить изделия на объект",
            "Состав объекта",
            "Управление объектами",
            "Потребность в материалах",
            "Добавить объект",
            "Корректировка"
        ],
        "objects_navigation",
        "objects_nav",
        columns_per_row=7
    )

    st.markdown("---")

    # ------------------------------------------------------------
    # СПИСОК ОБЪЕКТОВ
    # ------------------------------------------------------------
    if sub == "Список объектов":
        df = get_objects()
        if df.empty:
            st.info("Объектов нет.")
        else:
            object_filter_options = ["Все объекты"] + (
                sorted(df["object_name"].fillna("").astype(str).str.strip().loc[lambda x: x != ""].unique().tolist())
            )
            object_filter = st.selectbox("Отбор по объекту", object_filter_options, key="object_list_filter")
            if object_filter != "Все объекты":
                df = df[df["object_name"].eq(object_filter)].copy()
            display = df[["id", "object_name", "client_name", "address"]].copy()
            display.columns = ["ID", "Объект", "Заказчик", "Адрес"]
            st.dataframe(display, width="stretch", hide_index=True)

    # ------------------------------------------------------------
    # ДОБАВИТЬ ИЗДЕЛИЯ НА ОБЪЕКТ
    # ------------------------------------------------------------
    elif sub == "Добавить изделия на объект":
        objects = get_objects()
        if objects.empty:
            st.info("Объектов нет.")
        else:
            # Новые объекты сверху. ID используется как надёжный второй ключ.
            objects = objects.sort_values("id", ascending=False).reset_index(drop=True)
            object_map = {}
            object_options = []
            for _, row in objects.iterrows():
                oid = int(row["id"])
                name = str(row.get("object_name", "") or "").strip()
                client = str(row.get("client_name", "") or "").strip()
                address = str(row.get("address", "") or "").strip()
                label = f"{oid} — {name} — {client}"
                if address:
                    label += f" — {address}"
                object_options.append(label)
                object_map[label] = row

            selected_label = st.selectbox("Отбор по объекту", object_options, key="add_items_object_select")
            object_row = object_map[selected_label]
            object_id = int(object_row["id"])
            client_name = str(object_row.get("client_name", "") or "").strip()
            object_name = str(object_row.get("object_name", "") or "").strip()

            st.subheader(f"Добавить изделия на объект: {object_name}")
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
                object_options = [
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

    # ------------------------------------------------------------
    # СОСТАВ ОБЪЕКТА — ТОЛЬКО ПРОСМОТР
    # ------------------------------------------------------------
    elif sub == "Состав объекта":
        clients = get_clients()
        objects = get_objects()
        if clients.empty:
            st.info("Заказчики отсутствуют.")
        else:
            client_map = {
                f"{int(row['id'])} — {str(row['name'] or '').strip()}": int(row['id'])
                for _, row in clients.iterrows()
            }
            selected_client_label = st.selectbox("Отбор по заказчику", list(client_map.keys()), key="spec_client_select")
            selected_client_id = client_map[selected_client_label]

            client_objects = objects[objects["client_id"].fillna(-1).astype(int).eq(selected_client_id)].sort_values("id", ascending=False).copy()
            if client_objects.empty:
                st.info("У выбранного заказчика ещё нет объектов.")
            else:
                object_map = {}
                object_options = []
                for _, row in client_objects.iterrows():
                    oid = int(row["id"])
                    label = f"{oid} — {str(row['object_name'] or '').strip()}"
                    object_options.append(label)
                    object_map[label] = oid

                selected_object_label = st.selectbox("Отбор по объекту", object_options, key="spec_object_select")
                object_id = object_map[selected_object_label]
                row = client_objects[client_objects["id"] == object_id].iloc[0]

                st.subheader(f"Состав объекта: {row['object_name']}")
                items = get_object_items(object_id)
                if items.empty:
                    st.info("Для этого объекта ещё не созданы изделия.")
                else:
                    display = items[["id", "item_name", "quantity", "qty_new", "qty_production", "qty_ready", "qty_shipped", "qty_arrived", "qty_installing", "qty_installed"]].copy()
                    display.columns = ["ID", "Изделие", "Количество", "Новые", "Производство", "Готовая продукция", "Отгружено", "Прибыло", "Монтаж", "Смонтировано"]
                    st.dataframe(display, width="stretch", hide_index=True)

    # ------------------------------------------------------------
    # ПОТРЕБНОСТЬ В МАТЕРИАЛАХ
    # ------------------------------------------------------------
    elif sub == "Потребность в материалах":
        objects = get_objects()
        if objects.empty:
            st.info("Нет объектов.")
        else:
            objects = objects.sort_values("id", ascending=False).copy()
            object_map = {
                f"{int(row['id'])} — {row['object_name']} — {row['client_name']}": int(row["id"])
                for _, row in objects.iterrows()
            }
            selected = st.selectbox("Объект", list(object_map.keys()), key="material_requirement_object")
            object_id = object_map[selected]
            object_row = objects[objects["id"] == object_id].iloc[0]
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
                        ptm.quantity_per_unit,
                        COALESCE(ptm.waste_coefficient, m.default_waste_coefficient, 1) AS waste_coefficient,
                        m.cost_per_unit,
                        m.stock_quantity
                    FROM reklet.object_items oi
                    JOIN reklet.product_templates pt
                      ON pt.id = COALESCE(oi.product_template_id, oi.template_id)
                    JOIN reklet.product_template_materials ptm
                      ON ptm.product_template_id = pt.id
                    JOIN reklet.materials m ON m.id = ptm.material_id
                    LEFT JOIN reklet.units u ON u.id = m.unit_id
                    WHERE oi.object_id = %s
                    ORDER BY oi.item_name, m.name
                    """,
                    (object_id,), fetch=True
                )
                if requirements.empty:
                    st.warning("Для изделий этого объекта ещё не создана спецификация материалов.")
                else:
                    requirements["required_quantity"] = requirements["product_quantity"] * requirements["quantity_per_unit"] * requirements["waste_coefficient"]
                    requirements["material_cost"] = requirements["required_quantity"] * requirements["cost_per_unit"]
                    st.dataframe(requirements[["item_name", "product_quantity", "material_name", "unit_name", "quantity_per_unit", "waste_coefficient", "required_quantity", "cost_per_unit", "material_cost"]], width="stretch", hide_index=True)

    # ------------------------------------------------------------
    # ДОБАВИТЬ ОБЪЕКТ
    # ------------------------------------------------------------
    elif sub == "Добавить объект":
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
                distance = st.number_input("Расстояние доставки (км)", min_value=0.0, value=0.0)
                delivery_cost = st.number_input("Стоимость доставки", min_value=0.0, value=0.0)
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
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (client_map[client_name], object_name.strip(), address or None, phone or None,
                         contact_person or None, notes or None, distance, delivery_cost,
                         contract_date, production_start, production_end, installation_date, installation_end)
                    )
                    st.success("Объект создан.")

    # ------------------------------------------------------------
    # КОРРЕКТИРОВКА ОБЪЕКТА
    # ------------------------------------------------------------
    elif sub == "Корректировка":
        objects = get_objects()
        if objects.empty:
            st.info("Нет объектов для корректировки.")
        else:
            objects = objects.sort_values("id", ascending=False)
            object_map = {f"{int(row['id'])} — {row['object_name']}": int(row['id']) for _, row in objects.iterrows()}
            selected = st.selectbox("Отбор по объекту", list(object_map.keys()), key="object_correction_select")
            object_id = object_map[selected]
            row = objects[objects["id"] == object_id].iloc[0]
            with st.form("edit_object_form"):
                object_name = st.text_input("Название объекта", value=str(row.get("object_name", "") or ""))
                address = st.text_input("Адрес", value=str(row.get("address", "") or ""))
                save = st.form_submit_button("Сохранить изменения")
                if save:
                    if object_name.strip():
                        run_query("UPDATE reklet.objects SET object_name=%s, address=%s WHERE id=%s", (object_name.strip(), address.strip() or None, object_id))
                        st.success("Объект изменён.")
                    else:
                        st.warning("Название объекта не может быть пустым.")
            st.warning("Удаление объекта безопасное: объект с изделиями удалить нельзя.")
            confirm = st.checkbox("Я подтверждаю удаление выбранного объекта.", key="confirm_delete_object")
            if st.button("Удалить объект", disabled=not confirm, key="delete_object_button"):
                used = run_query("SELECT COUNT(*) AS cnt FROM reklet.object_items WHERE object_id=%s", (object_id,), fetch=True)
                if int(used.iloc[0]["cnt"]) > 0:
                    st.error("Удаление невозможно: в объекте есть изделия.")
                else:
                    run_query("DELETE FROM reklet.objects WHERE id=%s", (object_id,))
                    st.success("Объект удалён.")


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
    if product_sub != "Добавить изделие":
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
        action = st.radio(
            "Действие",
            ["Создать категорию","Корректировать категорию","Удалить категорию"],
            horizontal=True,key="product_category_action"
        )
        if action == "Создать категорию":
            with st.form("create_product_category"):
                name = st.text_input("Название категории")
                if st.form_submit_button("Создать категорию"):
                    if not name.strip():
                        st.warning("Название не может быть пустым.")
                    else:
                        try:
                            run_query("INSERT INTO reklet.product_categories (name) VALUES (%s)",(name.strip(),))
                            st.success("Категория изделия создана.")
                            st.rerun()
                        except Exception as e:
                            st.error("Не удалось создать категорию. Возможно, она уже существует.")
                            st.code(str(e))
        elif action == "Корректировать категорию":
            if categories.empty:
                st.info("Категорий изделий нет.")
            else:
                cmap={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in categories.iterrows()}
                label=st.selectbox("Категория",list(cmap.keys()),key="edit_product_category")
                cid=cmap[label]
                old_name=str(categories[categories["id"]==cid].iloc[0]["name"])
                with st.form("edit_product_category_form"):
                    new_name=st.text_input("Новое название",value=old_name)
                    if st.form_submit_button("Сохранить категорию"):
                        if not new_name.strip():
                            st.warning("Название не может быть пустым.")
                        else:
                            try:
                                run_transaction([
                                    ("UPDATE reklet.product_categories SET name=%s WHERE id=%s",(new_name.strip(),cid)),
                                    ("UPDATE reklet.product_templates SET category=%s WHERE category=%s",(new_name.strip(),old_name))
                                ])
                                st.success("Категория изменена.")
                                st.rerun()
                            except Exception as e:
                                st.error("Не удалось изменить категорию.")
                                st.code(str(e))
        else:
            if categories.empty:
                st.info("Категорий изделий нет.")
            else:
                cmap={f"{int(r['id'])} — {r['name']}":int(r['id']) for _,r in categories.iterrows()}
                label=st.selectbox("Категория",list(cmap.keys()),key="delete_product_category")
                cid=cmap[label]
                cat_name=str(categories[categories["id"]==cid].iloc[0]["name"])
                with st.expander("Удаление категории",expanded=False):
                    st.warning("Категория не будет удалена, если она используется изделиями.")
                    confirm=st.checkbox("Я подтверждаю удаление категории.",key="confirm_delete_product_category")
                    if st.button("Удалить категорию",key="delete_product_category",disabled=not confirm):
                        used=run_query("SELECT COUNT(*) AS cnt FROM reklet.product_templates WHERE category=%s",(cat_name,),fetch=True)
                        if int(used.iloc[0]["cnt"])>0:
                            st.error("Удаление невозможно: категория используется изделиями.")
                        else:
                            run_query("DELETE FROM reklet.product_categories WHERE id=%s",(cid,))
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

    st.header("Склад материалов")

    materials = get_materials_with_categories()
    categories = get_material_categories()
    category_map = {str(row["name"]): int(row["id"]) for _, row in categories.iterrows()}

    # ========================================================
    # НАВИГАЦИЯ СКЛАДА МАТЕРИАЛОВ
    # ========================================================

    material_sections = [
        ("Перечень материалов", "list"),
        ("Добавить материал", "add"),
        ("Категории материалов", "categories"),
        ("Приход материалов", "receipt"),
        ("Выдача материалов", "issue"),
        ("Движение материалов", "movement"),
    ]

    if "material_section" not in st.session_state:
        st.session_state.material_section = "list"

    nav_cols = st.columns(len(material_sections))
    for col, (label, value) in zip(nav_cols, material_sections):
        if col.button(label, key=f"material_nav_{value}", use_container_width=True):
            st.session_state.material_section = value
            st.rerun()

    active_material_section = st.session_state.material_section

    if active_material_section == "list":

        # ========================================================
        # MATERIAL LIST
        # ========================================================

        categories = get_material_categories()
        category_map = {
            str(row["name"]): int(row["id"])
            for _, row in categories.iterrows()
        }

        st.subheader("Перечень материалов")

        category_options = ["Все материалы", "Без категории"] + (
            categories["name"].astype(str).tolist()
            if not categories.empty else []
        )

        material_category_filter = st.selectbox(
            "Отбор по категории",
            category_options,
            key="material_category_filter"
        )

        filtered_materials = materials.copy()

        if material_category_filter == "Без категории":
            filtered_materials = filtered_materials[
                filtered_materials["category_id"].isna()
            ].copy()
        elif material_category_filter != "Все материалы":
            filtered_materials = filtered_materials[
                filtered_materials["category_name"].fillna("").astype(str).eq(
                    material_category_filter
                )
            ].copy()

        if filtered_materials.empty:
            st.info("Материалы по выбранному отбору отсутствуют.")
        else:
            display = filtered_materials[
                [
                    "id",
                    "name",
                    "category_name",
                    "unit_name",
                    "cost_per_unit",
                    "stock_quantity",
                    "default_waste_coefficient"
                ]
            ].copy()

            column_config = {
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "name": st.column_config.TextColumn("Материал"),
                "category_name": st.column_config.SelectboxColumn(
                    "Категория",
                    options=[""] + categories["name"].astype(str).tolist(),
                    required=False
                ),
                "unit_name": st.column_config.TextColumn("Единица", disabled=True),
                "cost_per_unit": st.column_config.NumberColumn("Цена за единицу", min_value=0.0, format="%.2f"),
                "stock_quantity": st.column_config.NumberColumn("Остаток", min_value=0.0, format="%.4f"),
                "default_waste_coefficient": st.column_config.NumberColumn("Коэффициент отходов", min_value=0.0, format="%.2f")
            }

            edited = st.data_editor(
                display,
                key="materials_editor",
                width="stretch",
                hide_index=True,
                column_config=column_config,
                disabled=["id", "unit_name"]
            )

            if st.button(
                "Сохранить изменения материалов",
                key="save_materials"
            ):
                for _, row in edited.iterrows():
                    cat_name = "" if pd.isna(row["category_name"]) else str(row["category_name"]).strip()
                    cat_id = category_map.get(cat_name) if cat_name else None

                    run_query(
                        """
                        UPDATE reklet.materials
                        SET
                            name = %s,
                            category_id = %s,
                            cost_per_unit = %s,
                            stock_quantity = %s,
                            default_waste_coefficient = %s
                        WHERE id = %s
                        """,
                        (
                            str(row["name"]).strip(),
                            cat_id,
                            safe_float(row["cost_per_unit"]),
                            safe_float(row["stock_quantity"]),
                            safe_float(row["default_waste_coefficient"], 1.20),
                            safe_int(row["id"])
                        )
                    )

                st.success("Изменения сохранены.")
                st.rerun()


    elif active_material_section == "add":

        st.markdown("---")
        st.subheader("Добавить материал")

        units = run_query(
            "SELECT id, name FROM reklet.units ORDER BY name",
            fetch=True
        )

        unit_map = {
            str(row["name"]): int(row["id"])
            for _, row in units.iterrows()
        } if not units.empty else {}

        create_category_options = ["— Без категории —"] + (
            categories["name"].astype(str).tolist()
            if not categories.empty else []
        )

        with st.form("add_material_form"):
            material_name = st.text_input("Название материала")

            unit_name = (
                st.selectbox("Единица измерения", list(unit_map.keys()))
                if unit_map else None
            )

            create_category = st.selectbox(
                "Категория",
                create_category_options
            )

            cost = st.number_input(
                "Цена за единицу",
                min_value=0.0,
                value=0.0,
                format="%.2f"
            )

            stock = st.number_input(
                "Начальный остаток",
                min_value=0.0,
                value=0.0,
                format="%.4f"
            )

            waste = st.number_input(
                "Коэффициент отходов",
                min_value=0.0,
                value=1.20,
                format="%.2f"
            )

            submit = st.form_submit_button("Добавить материал")

            if submit:
                if not material_name.strip() or not unit_map:
                    st.warning("Укажите название материала и единицу измерения.")
                else:
                    cat_id = (
                        category_map.get(create_category)
                        if create_category != "— Без категории —"
                        else None
                    )

                    run_query(
                        """
                        INSERT INTO reklet.materials
                        (
                            name,
                            unit_id,
                            category_id,
                            cost_per_unit,
                            stock_quantity,
                            default_waste_coefficient
                        )
                        VALUES (%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            material_name.strip(),
                            unit_map[unit_name],
                            cat_id,
                            cost,
                            stock,
                            waste
                        )
                    )

                    st.success("Материал добавлен.")
                    st.rerun()


    elif active_material_section == "categories":

        st.markdown("---")
        st.subheader("Категории материалов")

        category_action = st.radio(
            "Категории",
            ["Добавить категорию", "Корректировать категорию", "Удалить категорию"],
            horizontal=True,
            key="category_action"
        )

        categories = get_material_categories()

        if category_action == "Добавить категорию":
            with st.form("add_material_category_form_new"):
                new_category = st.text_input("Название категории")
                add_category = st.form_submit_button("Добавить категорию")
                if add_category:
                    if not new_category.strip():
                        st.warning("Укажите название категории.")
                    else:
                        try:
                            run_query("INSERT INTO reklet.material_categories (name) VALUES (%s)", (new_category.strip(),))
                            st.success("Категория добавлена.")
                            st.rerun()
                        except Exception:
                            st.error("Не удалось добавить категорию. Возможно, такое название уже существует.")

        elif category_action == "Корректировать категорию":
            if categories.empty:
                st.info("Категорий нет.")
            else:
                cat_map = {f"{r['id']} — {r['name']}": int(r['id']) for _, r in categories.iterrows()}
                label = st.selectbox("Категория", list(cat_map.keys()), key="edit_category_select_new")
                cat_id = cat_map[label]
                current = categories[categories["id"] == cat_id].iloc[0]["name"]
                with st.form("edit_category_form_new"):
                    new_name = st.text_input("Новое название категории", value=str(current))
                    save = st.form_submit_button("Сохранить категорию")
                    if save:
                        if not new_name.strip():
                            st.warning("Название не может быть пустым.")
                        else:
                            try:
                                run_query("UPDATE reklet.material_categories SET name=%s WHERE id=%s", (new_name.strip(), cat_id))
                                st.success("Категория изменена.")
                                st.rerun()
                            except Exception:
                                st.error("Не удалось изменить категорию. Возможно, такое название уже существует.")

        else:
            if categories.empty:
                st.info("Категорий нет.")
            else:
                cat_map = {f"{r['id']} — {r['name']}": int(r['id']) for _, r in categories.iterrows()}
                label = st.selectbox("Категория", list(cat_map.keys()), key="delete_category_select_new")
                cat_id = cat_map[label]
                st.warning("Удаление безопасное: категория, используемая материалами, не будет удалена.")
                confirm = st.checkbox("Я подтверждаю удаление категории.", key="confirm_delete_category_new")
                if st.button("Удалить категорию", key="delete_category_new", disabled=not confirm):
                    used = run_query("SELECT COUNT(*) AS cnt FROM reklet.materials WHERE category_id=%s", (cat_id,), fetch=True)
                    if int(used.iloc[0]["cnt"]) > 0:
                        st.error("Удаление невозможно: категория используется материалами.")
                    else:
                        run_query("DELETE FROM reklet.material_categories WHERE id=%s", (cat_id,))
                        st.success("Категория удалена.")
                        st.rerun()


    elif active_material_section == "receipt":

        st.subheader("Приход материалов")
        suppliers = get_suppliers()
        supplier_options = ["Без поставщика"] + ([str(x) for x in suppliers["name"].tolist()] if not suppliers.empty else [])
        supplier_map = {str(row["name"]): int(row["id"]) for _, row in suppliers.iterrows()} if not suppliers.empty else {}

        receipt_category_options = ["Все категории", "Без категории"] + (
            categories["name"].astype(str).tolist()
            if not categories.empty else []
        )
        receipt_category_label = st.selectbox(
            "Категория материала",
            receipt_category_options,
            key="receipt_category_batch"
        )

        receipt_materials = materials.copy()
        if receipt_category_label == "Без категории":
            receipt_materials = receipt_materials[
                receipt_materials["category_id"].isna()
            ].copy()
        elif receipt_category_label != "Все категории":
            receipt_materials = receipt_materials[
                receipt_materials["category_name"].fillna("").astype(str).eq(
                    receipt_category_label
                )
            ].copy()

        receipt_df = receipt_materials[["id", "name", "unit_name"]].copy()
        receipt_df.insert(0, "Выбрать", False)
        receipt_df["Количество"] = 0.0
        receipt_df["Цена"] = 0.0
        receipt_df.columns = ["Выбрать", "ID", "Материал", "Единица", "Количество", "Цена"]

        supplier_label = st.selectbox("Поставщик", supplier_options, key="receipt_supplier_batch")
        edited_receipt = st.data_editor(
            receipt_df, key="receipt_materials_editor", width="stretch", hide_index=True,
            column_config={
                "Выбрать": st.column_config.CheckboxColumn("Выбрать"),
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "Материал": st.column_config.TextColumn("Материал", disabled=True),
                "Единица": st.column_config.TextColumn("Единица", disabled=True),
                "Количество": st.column_config.NumberColumn("Количество", min_value=0.0, step=0.001, format="%.4f"),
                "Цена": st.column_config.NumberColumn("Цена", min_value=0.0, step=0.01, format="%.2f"),
            }, disabled=["ID", "Материал", "Единица"]
        )

        if st.button("Выполнить приход", key="execute_receipt_batch", use_container_width=True):
            selected = edited_receipt[edited_receipt["Выбрать"].fillna(False) & (edited_receipt["Количество"].fillna(0).astype(float) > 0)]
            if selected.empty:
                st.warning("Выберите материалы и укажите количество.")
            else:
                supplier_id = supplier_map.get(supplier_label)
                statements=[]
                for _, row in selected.iterrows():
                    material_id=safe_int(row["ID"]); qty=safe_float(row["Количество"]); price=safe_float(row["Цена"])
                    statements.append((
                        """INSERT INTO reklet.material_transactions (material_id,supplier_id,operation_type,quantity,unit_price,transaction_type) VALUES (%s,%s,'purchase',%s,%s,'IN')""",
                        (material_id,supplier_id,qty,price)
                    ))
                    statements.append((
                        "UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)+%s WHERE id=%s",
                        (qty,material_id)
                    ))
                    if supplier_id:
                        statements.append((
                            """INSERT INTO reklet.material_suppliers (material_id,supplier_id,purchase_price) VALUES (%s,%s,%s) ON CONFLICT (material_id,supplier_id) DO UPDATE SET purchase_price=EXCLUDED.purchase_price""",
                            (material_id,supplier_id,price)
                        ))
                run_transaction(statements)
                st.success(f"Приход выполнен: {len(selected)} поз.")
                st.rerun()

    elif active_material_section == "issue":
        st.subheader("Выдача материалов в производство")
        objects = get_objects()
        if materials.empty or objects.empty:
            st.info("Нужны материалы и объекты.")
        else:
            object_options = {
                f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}": int(r['id'])
                for _,r in objects.sort_values("id",ascending=False).iterrows()
            }
            object_label = st.selectbox(
                "Объект",
                list(object_options.keys()),
                key="issue_object_batch"
            )
            object_id = object_options[object_label]

            # Потребность материалов по выбранному объекту:
            # сумма по всем изделиям объекта: количество изделия × норма материала × коэффициент отходов.
            demand = run_query(
                """
                SELECT
                    ptm.material_id,
                    SUM(
                        COALESCE(oi.quantity_needed, 0)
                        * COALESCE(ptm.quantity_per_unit, 0)
                        * COALESCE(ptm.waste_coefficient, 1)
                    ) AS required_quantity
                FROM reklet.object_items oi
                JOIN reklet.product_template_materials ptm
                  ON ptm.product_template_id=COALESCE(oi.product_template_id,oi.template_id)
                WHERE oi.object_id=%s
                  AND COALESCE(oi.quantity_needed,0) > 0
                  AND COALESCE(oi.qty_installed,0) < COALESCE(oi.quantity_needed,0)
                GROUP BY ptm.material_id
                """,
                (object_id,),fetch=True
            )
            demand_map = {}
            if not demand.empty:
                demand_map = {
                    safe_int(r["material_id"]): safe_float(r["required_quantity"])
                    for _, r in demand.iterrows()
                }
            required_ids = set(demand_map.keys())

            # Сколько материала уже выдано в производство именно этому объекту.
            issued = run_query(
                """
                SELECT
                    material_id,
                    COALESCE(SUM(quantity),0) AS issued_quantity
                FROM reklet.material_transactions
                WHERE object_id=%s
                  AND operation_type='production_transfer'
                  AND transaction_type='OUT'
                GROUP BY material_id
                """,
                (object_id,),
                fetch=True
            )
            issued_map = {}
            if not issued.empty:
                issued_map = {
                    safe_int(r["material_id"]): safe_float(r["issued_quantity"])
                    for _, r in issued.iterrows()
                }

            material_scope = st.selectbox(
                "Материалы для выбранного объекта",
                ["Все материалы","Только необходимые для объекта"],
                key="issue_material_scope"
            )

            issue_materials = materials.copy()
            if material_scope == "Только необходимые для объекта":
                issue_materials = issue_materials[issue_materials["id"].isin(required_ids)].copy()
                if issue_materials.empty:
                    st.info("Для выбранного объекта по спецификациям материалов потребности нет.")
            if not issue_materials.empty:
                issue_df=issue_materials[["id","name","unit_name","stock_quantity"]].copy()
                issue_df["required_quantity"] = issue_df["id"].map(demand_map).fillna(0.0)
                issue_df["issued_quantity"] = issue_df["id"].map(issued_map).fillna(0.0)
                issue_df.insert(0,"Выбрать",False)
                issue_df["Выдать"]=0.0
                issue_df.columns=["Выбрать","ID","Материал","Единица","На складе","Потребность объекта","Выдано","Выдать"]
                with st.form(f"issue_materials_form_{object_id}",clear_on_submit=False):
                    edited_issue=st.data_editor(
                        issue_df,key=f"issue_materials_editor_{object_id}_{material_scope}",
                        width="stretch",hide_index=True,
                        column_config={
                            "Выбрать":st.column_config.CheckboxColumn("Выбрать"),
                            "ID":st.column_config.NumberColumn("ID",disabled=True),
                            "Материал":st.column_config.TextColumn("Материал",disabled=True),
                            "Единица":st.column_config.TextColumn("Единица",disabled=True),
                            "На складе":st.column_config.NumberColumn("На складе",disabled=True,format="%.4f"),
                            "Потребность объекта":st.column_config.NumberColumn("Потребность объекта",disabled=True,format="%.4f"),
                            "Выдано":st.column_config.NumberColumn("Выдано",disabled=True,format="%.4f"),
                            "Выдать":st.column_config.NumberColumn("Выдать",min_value=0.0,step=0.001,format="%.4f")
                        },
                        disabled=["ID","Материал","Единица","На складе","Потребность объекта","Выдано"]
                    )
                    execute_issue=st.form_submit_button("Выполнить выдачу в производство",use_container_width=True)
                if execute_issue:
                    selected=edited_issue[
                        edited_issue["Выбрать"].fillna(False) &
                        (edited_issue["Выдать"].fillna(0).astype(float)>0)
                    ]
                    if selected.empty:
                        st.warning("Выберите материалы и укажите количество.")
                    elif any(safe_float(r["Выдать"])>safe_float(r["На складе"]) for _,r in selected.iterrows()):
                        st.error("Нельзя выдать больше, чем есть на складе.")
                    else:
                        statements=[]
                        for _,r in selected.iterrows():
                            mid=safe_int(r["ID"]); qty=safe_float(r["Выдать"])
                            statements.extend([
                                ("INSERT INTO reklet.material_transactions(material_id,object_id,operation_type,quantity,transaction_type) VALUES (%s,%s,'production_transfer',%s,'OUT')",(mid,object_id,qty)),
                                ("UPDATE reklet.materials SET stock_quantity=COALESCE(stock_quantity,0)-%s WHERE id=%s",(qty,mid))
                            ])
                        run_transaction(statements)
                        st.success(f"Выдача выполнена: {len(selected)} поз.")
                        st.rerun()

    elif active_material_section == "supplier_search":
        st.subheader("Поставщики материала")
        all_materials = get_materials_with_categories()
        if all_materials.empty:
            st.info("Материалов нет.")
        else:
            categories = get_material_categories()
            category_options = ["Все категории","Без категории"] + (
                categories["name"].astype(str).tolist() if not categories.empty else []
            )
            category = st.selectbox(
                "Категория материала",
                category_options,
                key="supplier_search_material_category"
            )
            filtered = all_materials.copy()
            if category == "Без категории":
                filtered = filtered[filtered["category_id"].isna()].copy()
            elif category != "Все категории":
                filtered = filtered[
                    filtered["category_name"].fillna("").astype(str).eq(category)
                ].copy()

            if filtered.empty:
                st.info("В выбранной категории материалов нет.")
            else:
                material_map = {
                    f"{int(r['id'])} — {r['name']}": int(r['id'])
                    for _,r in filtered.sort_values("name").iterrows()
                }
                selected_material = st.selectbox(
                    "Материал",
                    list(material_map.keys()),
                    key="supplier_search_material"
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
                    JOIN reklet.suppliers s ON s.id=ms.supplier_id
                    WHERE ms.material_id=%s
                    ORDER BY s.name
                    """,
                    (material_id,),fetch=True
                )
                if suppliers_for_material.empty:
                    st.info("Для этого материала поставщики не назначены.")
                else:
                    view=suppliers_for_material.copy()
                    view.columns=["ID","Поставщик","Цена","Код поставщика","Условия","Предпочтительный"]
                    st.dataframe(view,width="stretch",hide_index=True)

    elif active_material_section == "movement":

        # ========================================================
        # MOVEMENT HISTORY
        # ========================================================

        st.markdown("---")

        st.subheader(
            "Движение материалов"
        )

        movements = run_query(
            """
            SELECT

                mt.id,

                mt.created_at,

                m.name AS material,

                s.name AS supplier,

                o.object_name AS object_name,

                mt.operation_type,

                mt.quantity,

                mt.unit_price,

                mt.transaction_type

            FROM
                reklet.material_transactions mt

            LEFT JOIN reklet.materials m
                ON m.id = mt.material_id

            LEFT JOIN reklet.suppliers s
                ON s.id = mt.supplier_id

            LEFT JOIN reklet.objects o
                ON o.id = mt.object_id

            ORDER BY
                mt.created_at DESC

            LIMIT 500
            """,
            fetch=True
        )

        if not movements.empty:

            movement_view = movements.copy()
            st.dataframe(
                movement_view,
                width="stretch",
                hide_index=True
            )



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
            display_cols=[c for c in ["id","name","type","contact_person","phone","email","category","conditions"] if c in suppliers.columns]
            st.dataframe(suppliers[display_cols],width="stretch",hide_index=True)

    elif supplier_sub=="Создать поставщика":
        st.subheader("Создать поставщика")
        with st.form("create_supplier_new"):
            name=st.text_input("Название")
            supplier_type=st.selectbox("Тип поставщика",["material_supplier","subcontractor","both"])
            contact_person=st.text_input("Контактное лицо")
            phone=st.text_input("Телефон")
            email=st.text_input("Email")
            category=st.text_input("Категория")
            conditions=st.text_area("Условия")
            contact_info=st.text_area("Контактная информация")
            submit=st.form_submit_button("Создать поставщика")
            if submit:
                if not name.strip():
                    st.warning("Необходимо указать название.")
                else:
                    run_query(
                        """INSERT INTO reklet.suppliers
                           (name,type,contact_info,contact_person,phone,email,category,conditions)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (name.strip(),supplier_type,contact_info.strip() or None,
                         contact_person.strip() or None,phone.strip() or None,
                         email.strip() or None,category.strip() or None,conditions.strip() or None)
                    )
                    st.success("Поставщик создан.")
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

            all_materials=get_materials_with_categories()
            material_options={
                f"{r['name']} — {r['category_name'] or 'Без категории'}":int(r['id'])
                for _,r in all_materials.iterrows()
            }
            if material_options:
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
                category=st.text_input("Категория",value=str(row.get("category") or ""))
                conditions=st.text_area("Условия",value=str(row.get("conditions") or ""))
                contact_info=st.text_area("Контактная информация",value=str(row.get("contact_info") or ""))
                if st.form_submit_button("Сохранить изменения"):
                    if not name.strip():
                        st.warning("Название поставщика не может быть пустым.")
                    else:
                        run_query(
                            """UPDATE reklet.suppliers SET name=%s,type=%s,contact_info=%s,
                                      contact_person=%s,phone=%s,email=%s,category=%s,conditions=%s
                               WHERE id=%s""",
                            (name.strip(),supplier_type,contact_info.strip() or None,
                             contact_person.strip() or None,phone.strip() or None,email.strip() or None,
                             category.strip() or None,conditions.strip() or None,selected_id)
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
                             (SELECT COUNT(*) FROM reklet.material_transactions WHERE supplier_id=%s) AS transactions""",
                        (selected_id,selected_id),fetch=True
                    )
                    if int(used.iloc[0]["material_links"])>0 or int(used.iloc[0]["transactions"])>0:
                        st.error("Удаление невозможно: поставщик используется в связанных данных.")
                    else:
                        run_query("DELETE FROM reklet.suppliers WHERE id=%s",(selected_id,))
                        st.success("Поставщик удалён.")
                        st.rerun()

# ============================================================
# PRODUCTION
# ============================================================

elif menu == "Производство":

    st.header("Производство")
    ensure_stage_movement_tables()

    objects = get_stage_objects("production")
    if objects.empty:
        st.success("На производстве нет незавершённых заданий.")
    else:
        object_options = [f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _, r in objects.iterrows()]
        object_map = {x: int(x.split(" — ")[0]) for x in object_options}
        selected_object = st.selectbox("Объект", object_options, key="production_object_table")
        object_id = object_map[selected_object]

        production_df = run_query(
            """SELECT oi.id, oi.item_name, oi.quantity_needed,
                      COALESCE(oi.qty_new,0) AS qty_new,
                      COALESCE(oi.qty_production,0) AS qty_production,
                      COALESCE(oi.qty_ready,0) AS qty_ready,
                      (COALESCE(oi.quantity_needed,0) - COALESCE(oi.qty_new,0)) AS manufactured_total
               FROM reklet.object_items oi
               WHERE oi.object_id=%s
                 AND (COALESCE(oi.qty_new,0) > 0 OR COALESCE(oi.qty_production,0) > 0)
               ORDER BY oi.id""",
            (object_id,), fetch=True
        )

        if production_df.empty:
            st.success("Для выбранного объекта производство завершено.")
        else:
            editor = production_df[["id","item_name","quantity_needed","manufactured_total","qty_production","qty_ready"]].copy()
            editor.columns = ["ID","Изделие","Заказано","Изготовлено","В производстве","Уже на готовой продукции"]
            editor["Передать на склад"] = 0
            editor["Сразу смонтировать"] = 0

            with st.form(f"production_form_{object_id}", clear_on_submit=False):
                edited = st.data_editor(
                    editor, key=f"production_excel_editor_{object_id}", width="stretch", hide_index=True,
                    column_config={
                        "ID": st.column_config.NumberColumn("ID", disabled=True),
                        "Изделие": st.column_config.TextColumn("Изделие", disabled=True),
                        "Заказано": st.column_config.NumberColumn("Заказано", disabled=True),
                        "Изготовлено": st.column_config.NumberColumn("Изготовлено", min_value=0, step=1, format="%d"),
                        "В производстве": st.column_config.NumberColumn("В производстве", disabled=True),
                        "Уже на готовой продукции": st.column_config.NumberColumn("Уже на готовой продукции", disabled=True),
                        "Передать на склад": st.column_config.NumberColumn("Передать на склад", min_value=0, step=1, format="%d"),
                        "Сразу смонтировать": st.column_config.NumberColumn("Сразу смонтировать", min_value=0, step=1, format="%d"),
                    },
                    disabled=["ID","Изделие","Заказано","В производстве","Уже на готовой продукции"],
                )
                execute = st.form_submit_button("Выполнить", use_container_width=True)

            if execute:
                selected = edited[(pd.to_numeric(edited["Передать на склад"], errors="coerce").fillna(0) > 0) | (pd.to_numeric(edited["Сразу смонтировать"], errors="coerce").fillna(0) > 0) | (pd.to_numeric(edited["Изготовлено"], errors="coerce").fillna(0) != production_df["manufactured_total"].values)] .copy()
                errors=[]
                statements=[]
                for idx, r in edited.iterrows():
                    src = production_df.iloc[idx]
                    item_id=safe_int(r["ID"])
                    ordered=safe_int(src["quantity_needed"])
                    old_manufactured=safe_int(src["manufactured_total"])
                    new_manufactured=safe_int(r["Изготовлено"])
                    in_prod=safe_int(src["qty_production"])
                    to_stock=safe_int(r["Передать на склад"])
                    direct_install=safe_int(r["Сразу смонтировать"])
                    if new_manufactured < old_manufactured:
                        errors.append(f"{r['Изделие']}: количество изготовленного нельзя уменьшить ниже {old_manufactured}.")
                    if new_manufactured > ordered:
                        errors.append(f"{r['Изделие']}: изготовлено {new_manufactured}, заказано только {ordered}.")
                    added = new_manufactured - old_manufactured
                    available_for_transfer = in_prod + max(added,0)
                    if to_stock + direct_install > available_for_transfer:
                        errors.append(f"{r['Изделие']}: передача {to_stock + direct_install} шт., доступно максимум {available_for_transfer} шт.")
                    if to_stock < 0 or direct_install < 0:
                        errors.append(f"{r['Изделие']}: количество не может быть отрицательным.")
                    if to_stock and direct_install:
                        pass
                    if errors and len(errors)>50: break

                    if new_manufactured != old_manufactured:
                        statements.append((
                            "UPDATE reklet.object_items SET qty_new=GREATEST(quantity_needed-%s-COALESCE(qty_ready,0)-COALESCE(qty_shipped,0)-COALESCE(qty_arrived,0)-COALESCE(qty_installing,0)-COALESCE(qty_installed,0),0), qty_production=COALESCE(qty_production,0)+%s, production_status='in_progress' WHERE id=%s",
                            (new_manufactured, added, item_id)
                        ))

                    total_transfer = to_stock + direct_install
                    if total_transfer:
                        statements.append((
                            "UPDATE reklet.object_items SET qty_production=GREATEST(COALESCE(qty_production,0)-%s,0), qty_ready=COALESCE(qty_ready,0)+%s WHERE id=%s",
                            (total_transfer, to_stock, item_id)
                        ))
                        statements.append((
                            "INSERT INTO reklet.production_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'completed',%s FROM reklet.object_items WHERE id=%s",
                            (total_transfer,item_id)
                        ))
                        if to_stock:
                            statements.append((
                                "INSERT INTO reklet.finished_goods (object_item_id,object_id,quantity,status) SELECT id,object_id,%s,'ready' FROM reklet.object_items WHERE id=%s",
                                (to_stock,item_id)
                            ))
                            statements.append((
                                "INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ready',%s FROM reklet.object_items WHERE id=%s",
                                (to_stock,item_id)
                            ))
                        if direct_install:
                            # Прямая передача: история проходит все четыре этапа,
                            # но промежуточные остатки не задерживаются на складе/транспорте.
                            statements.extend([
                                ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ready',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("UPDATE reklet.object_items SET qty_installed=COALESCE(qty_installed,0)+%s, installation_status='completed', installation_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND((COALESCE(qty_installed,0)+%s)::numeric/quantity_needed*100)) ELSE 0 END WHERE id=%s", (direct_install,direct_install,item_id)),
                                ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'ship',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                                ("INSERT INTO reklet.installation_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'complete',%s FROM reklet.object_items WHERE id=%s", (direct_install,item_id)),
                            ])

                if errors:
                    st.error("Операция не выполнена:\n" + "\n".join(errors))
                elif not statements:
                    st.info("Изменений нет.")
                else:
                    run_transaction(statements)
                    st.success("Производственные данные обновлены. Выполненные позиции исчезнут из рабочего списка.")
                    st.rerun()

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
        st.dataframe(movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]],width="stretch",hide_index=True)

# ============================================================
# TRANSPORT & LOGISTICS
# ============================================================

elif menu == "Транспорт и логистика":

    st.header("Транспорт и логистика")
    ensure_stage_movement_tables()
    objects=get_stage_objects("transport")
    if objects.empty:
        st.success("В транспорте нет незавершённых заданий.")
    else:
        object_options=[f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or ''}" for _,r in objects.iterrows()]
        object_map={x:int(x.split(" — ")[0]) for x in object_options}
        selected_object=st.selectbox("Объект",object_options,key="transport_object_filter")
        object_id=object_map[selected_object]
        df=run_query("""SELECT oi.id,oi.item_name,oi.quantity_needed AS ordered,COALESCE(oi.qty_shipped,0) AS shipped,COALESCE(oi.qty_arrived,0) AS arrived,GREATEST(COALESCE(oi.qty_shipped,0)-COALESCE(oi.qty_arrived,0),0) AS in_transit FROM reklet.object_items oi WHERE oi.object_id=%s AND COALESCE(oi.qty_shipped,0)>COALESCE(oi.qty_arrived,0) ORDER BY oi.id""",(object_id,),fetch=True)
        if df.empty:
            st.success("Для выбранного объекта нет изделий, ожидающих доставки.")
        else:
            editor=df[["id","item_name","ordered","shipped","arrived","in_transit"]].copy(); editor.columns=["ID","Изделие","Заказано","Отправлено","Доставлено","В пути"]; editor["Доставить на объект"]=0
            with st.form(f"transport_form_{object_id}",clear_on_submit=False):
                edited=st.data_editor(editor,key=f"transport_editor_{object_id}",width="stretch",hide_index=True,column_config={
                    "ID":st.column_config.NumberColumn("ID",disabled=True),"Изделие":st.column_config.TextColumn("Изделие",disabled=True),"Заказано":st.column_config.NumberColumn("Заказано",disabled=True),"Отправлено":st.column_config.NumberColumn("Отправлено",disabled=True),"Доставлено":st.column_config.NumberColumn("Доставлено",disabled=True),"В пути":st.column_config.NumberColumn("В пути",disabled=True),"Доставить на объект":st.column_config.NumberColumn("Доставить на объект",min_value=0,step=1,format="%d")},disabled=["ID","Изделие","Заказано","Отправлено","Доставлено","В пути"])
                execute=st.form_submit_button("Выполнить",use_container_width=True)
            if execute:
                errors=[]; statements=[]
                for _,r in edited.iterrows():
                    qty=safe_int(r["Доставить на объект"]); available=safe_int(r["В пути"]); item_id=safe_int(r["ID"])
                    if qty>available: errors.append(f"{r['Изделие']}: указано {qty}, в пути только {available}.")
                    if qty>0:
                        statements.extend([
                            ("UPDATE reklet.object_items SET qty_shipped=GREATEST(COALESCE(qty_shipped,0)-%s,0), qty_arrived=COALESCE(qty_arrived,0)+%s WHERE id=%s",(qty,qty,item_id)),
                            ("INSERT INTO reklet.finished_goods_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                            ("INSERT INTO reklet.transport_transactions (object_item_id,object_id,operation_type,quantity) SELECT id,object_id,'arrive',%s FROM reklet.object_items WHERE id=%s",(qty,item_id)),
                        ])
                if errors: st.error("Операция не выполнена:\n"+"\n".join(errors))
                elif not statements: st.info("Введите количество хотя бы для одной строки.")
                else: run_transaction(statements); st.success("Изделия доставлены на объект."); st.rerun()

    st.markdown("---"); st.subheader("Движения транспорта")
    movements=run_query("""SELECT tt.id,o.object_name,c.name AS client_name,oi.item_name,tt.operation_type,tt.quantity,tt.created_at FROM reklet.transport_transactions tt LEFT JOIN reklet.objects o ON o.id=tt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.object_items oi ON oi.id=tt.object_item_id ORDER BY tt.created_at DESC LIMIT 500""",fetch=True)
    if not movements.empty:
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"}); st.dataframe(movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]],width="stretch",hide_index=True)
    else: st.info("Движений транспорта пока нет.")

# ============================================================
# INSTALLATION
# ============================================================

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
        movements=movements.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","operation_type":"Операция","quantity":"Количество","created_at":"Когда"}); st.dataframe(movements[["Объект","Заказчик","Изделие","Операция","Количество","Когда"]],width="stretch",hide_index=True)
    else: st.info("Движений монтажа пока нет.")

# ============================================================
# PAYROLL
# ============================================================

elif menu == "Зарплата":

    st.header("Зарплата")

    if "payroll_section" not in st.session_state:
        st.session_state.payroll_section = "Производство"

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("Зарплата производства", key="payroll_production_btn", width="stretch"):
            st.session_state.payroll_section = "Производство"
    with b2:
        if st.button("Зарплата транспортировки", key="payroll_transport_btn", width="stretch"):
            st.session_state.payroll_section = "Транспортировка"
    with b3:
        if st.button("Зарплата монтажа", key="payroll_install_btn", width="stretch"):
            st.session_state.payroll_section = "Монтаж"
    with b4:
        if st.button("Сводка по зарплате", key="payroll_summary_btn", width="stretch"):
            st.session_state.payroll_section = "Сводка"

    st.markdown("---")

    # Себестоимость материалов одного элемента.
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
            COALESCE(o.delivery_cost, 0) AS stored_delivery_cost,
            COALESCE(SUM(
                ptm.quantity_per_unit *
                COALESCE(ptm.waste_coefficient, m.default_waste_coefficient, 1) *
                COALESCE(m.cost_per_unit, 0)
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
        GROUP BY
            oi.id, oi.object_id, o.object_name, c.name, oi.item_name,
            oi.quantity_needed, o.transport_distance_km, o.delivery_cost
        ORDER BY o.object_name, oi.item_name
        """,
        fetch=True
    )

    if payroll_items.empty:
        st.info("Нет элементов для расчёта зарплаты.")
    else:
        # Отбор по объекту применяется ко всем четырём разделам зарплаты.
        payroll_object_options = ["Все объекты"] + [
            f"{int(row['object_id'])} — {row['object_name']}"
            for _, row in payroll_items[["object_id", "object_name"]].drop_duplicates().iterrows()
        ]
        payroll_object_filter = st.selectbox(
            "Отбор по объекту",
            payroll_object_options,
            key=f"payroll_object_filter_{st.session_state.payroll_section}"
        )
        if payroll_object_filter != "Все объекты":
            payroll_object_id = int(payroll_object_filter.split(" — ")[0])
            payroll_items = payroll_items[payroll_items["object_id"] == payroll_object_id].copy()

        if payroll_items.empty:
            st.info("По выбранному объекту данных для расчёта зарплаты нет.")
            st.stop()

        # PostgreSQL numeric/Decimal values and nullable quantities are normalized
        # before arithmetic so Pandas never tries to multiply strings by numbers.
        numeric_cols = [
            "material_cost_per_unit",
            "distance_km",
            "quantity_needed"
        ]
        for col in numeric_cols:
            if col in payroll_items.columns:
                payroll_items[col] = pd.to_numeric(
                    payroll_items[col], errors="coerce"
                ).fillna(0.0)

        if st.session_state.payroll_section == "Производство":
            view = payroll_items.copy()
            view["Себестоимость материалов"] = view["material_cost_per_unit"]
            view["Количество"] = view["quantity_needed"]
            view["Зарплата производства"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
            view = view.rename(columns={"object_name":"Объект", "client_name":"Заказчик", "item_name":"Изделие"})
            st.caption("Зарплата производства рассчитывается сразу на всё количество изделий, указанное в объекте: себестоимость материалов × количество изделий × 1,50 (+50%).")
            st.dataframe(view[["Объект", "Заказчик", "Изделие", "Себестоимость материалов", "Количество", "Зарплата производства"]], width="stretch", hide_index=True)

        elif st.session_state.payroll_section == "Монтаж":
            view = payroll_items.copy()
            view["Себестоимость материалов"] = view["material_cost_per_unit"]
            view["Количество"] = view["quantity_needed"]
            view["Зарплата монтажа"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
            view = view.rename(columns={"object_name":"Объект", "client_name":"Заказчик", "item_name":"Изделие"})
            st.caption("Зарплата монтажа рассчитывается сразу на всё количество изделий, указанное в объекте: себестоимость материалов × количество изделий × 1,40 (+40%).")
            st.dataframe(view[["Объект", "Заказчик", "Изделие", "Себестоимость материалов", "Количество", "Зарплата монтажа"]], width="stretch", hide_index=True)

        elif st.session_state.payroll_section == "Транспортировка":
            view = payroll_items.copy()
            view["Себестоимость материалов"] = view["material_cost_per_unit"] * view["quantity_needed"]
            view["Количество"] = view["quantity_needed"]
            # 10% рассчитывается отдельно по каждому изделию, но стоимость
            # расстояния до объекта начисляется один раз на весь объект.
            view["Зарплата 10%"] = view["Себестоимость материалов"] * 0.10
            view = view.rename(columns={
                "object_name":"Объект",
                "client_name":"Заказчик",
                "item_name":"Изделие",
                "distance_km":"Расстояние, км"
            })
            st.caption(
                "Транспортировка = 10% от общей себестоимости материалов всех изделий объекта "
                "+ расстояние до объекта × 2. Расстояние оплачивается только один раз на объект, "
                "независимо от количества изделий."
            )
            st.dataframe(
                view[["Объект", "Заказчик", "Изделие", "Себестоимость материалов", "Количество", "Зарплата 10%"]],
                width="stretch",
                hide_index=True
            )

            transport_summary = (
                payroll_items.assign(
                    material_total=lambda x: x["material_cost_per_unit"] * x["quantity_needed"],
                    salary_10=lambda x: x["material_cost_per_unit"] * x["quantity_needed"] * 0.10
                )
                .groupby(["object_id", "object_name", "client_name"], as_index=False)
                .agg(
                    **{
                        "Себестоимость материалов": ("material_total", "sum"),
                        "Зарплата 10%": ("salary_10", "sum"),
                        "Расстояние, км": ("distance_km", "first")
                    }
                )
            )
            transport_summary["Расстояние × 2"] = transport_summary["Расстояние, км"] * 2
            transport_summary["Итого зарплата транспортировки"] = (
                transport_summary["Зарплата 10%"] + transport_summary["Расстояние × 2"]
            )
            transport_summary = transport_summary.rename(columns={
                "object_name":"Объект",
                "client_name":"Заказчик"
            })
            st.subheader("Итого по объектам")
            st.dataframe(
                transport_summary[[
                    "Объект", "Заказчик", "Себестоимость материалов",
                    "Зарплата 10%", "Расстояние, км", "Расстояние × 2",
                    "Итого зарплата транспортировки"
                ]],
                width="stretch",
                hide_index=True
            )

        else:
            view = payroll_items.copy()
            view["Производство"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
            view["Монтаж"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
            view["Доставка 10%"] = view["material_cost_per_unit"] * view["quantity_needed"] * 0.10
            view["Итого без расстояния"] = view["Производство"] + view["Монтаж"] + view["Доставка 10%"]
            view = view.rename(columns={"object_name":"Объект", "client_name":"Заказчик", "item_name":"Изделие"})
            st.dataframe(
                view[["Объект", "Заказчик", "Изделие", "Производство", "Монтаж", "Доставка 10%", "Итого без расстояния"]],
                width="stretch",
                hide_index=True
            )

            summary = (
                payroll_items.assign(
                    Производство=lambda x: x["material_cost_per_unit"] * x["quantity_needed"] * 1.50,
                    Монтаж=lambda x: x["material_cost_per_unit"] * x["quantity_needed"] * 1.40,
                    **{
                        "Доставка 10%": lambda x: x["material_cost_per_unit"] * x["quantity_needed"] * 0.10
                    }
                )
                .groupby(["object_id", "object_name", "client_name"], as_index=False)
                .agg(
                    Производство=("Производство", "sum"),
                    Монтаж=("Монтаж", "sum"),
                    **{
                        "Доставка 10%": ("Доставка 10%", "sum"),
                        "Расстояние, км": ("distance_km", "first")
                    }
                )
            )
            summary["Расстояние × 2"] = summary["Расстояние, км"] * 2
            summary["Доставка"] = summary["Доставка 10%"] + summary["Расстояние × 2"]
            summary["Итого"] = summary["Производство"] + summary["Монтаж"] + summary["Доставка"]
            summary = summary.rename(columns={"object_name":"Объект", "client_name":"Заказчик"})
            st.subheader("Сводка по объектам")
            st.dataframe(
                summary[["Объект", "Заказчик", "Производство", "Монтаж", "Доставка 10%", "Расстояние, км", "Расстояние × 2", "Доставка", "Итого"]],
                width="stretch",
                hide_index=True
            )


# ============================================================
# REPORTS
# ============================================================

elif menu == "Отчёты":

    st.header("Отчёты")

    # ========================================================
    # REPORT BUTTONS
    # ========================================================
    if "reports_section" not in st.session_state:
        st.session_state["reports_section"] = "Сводные таблицы"

    rb1, rb2 = st.columns(2)
    rb3, rb4 = st.columns(2)

    with rb1:
        if st.button("Сводные таблицы", key="reports_summary_btn", use_container_width=True):
            st.session_state["reports_section"] = "Сводные таблицы"
            st.rerun()
    with rb2:
        if st.button("Печать документов", key="reports_print_btn", use_container_width=True):
            st.session_state["reports_section"] = "Печать документов"
            st.rerun()
    with rb3:
        if st.button("Операционные отчёты", key="reports_operational_btn", use_container_width=True):
            st.session_state["reports_section"] = "Операционные отчёты"
            st.rerun()
    with rb4:
        if st.button("Складские отчёты", key="reports_stock_btn", use_container_width=True):
            st.session_state["reports_section"] = "Складские отчёты"
            st.rerun()

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
            ptm.quantity_per_unit
            * m.cost_per_unit
            * COALESCE(ptm.waste_coefficient, 1)
        ), 0) AS material_unit_cost
    FROM reklet.object_items oi
    JOIN reklet.objects o ON o.id = oi.object_id
    LEFT JOIN reklet.clients c ON c.id = o.client_id
    LEFT JOIN reklet.product_template_materials ptm
        ON ptm.product_template_id = oi.product_template_id
    LEFT JOIN reklet.materials m ON m.id = ptm.material_id
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

    # ========================================================
    # 2. PRINT DOCUMENTS
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
                    "Скачать документ для печати (HTML)",
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
                st.download_button("Скачать документ для печати (HTML)", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_client_document")

        else:
            st.info("Накладные будут связаны непосредственно с движениями склада материалов. Выберите тип накладной — система покажет соответствующее движение для печати.")

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
            st.dataframe(card[["item_name","quantity_needed","qty_installed","qty_ready","qty_shipped","qty_arrived"]].rename(columns={"item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено","qty_ready":"Готово","qty_shipped":"Отправлено","qty_arrived":"Доставлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по производству":
            st.dataframe(report_df.groupby(["object_name","client_name"], as_index=False).agg(Заказано=("quantity_needed","sum"), Готово=("qty_ready","sum"), Доставлено=("qty_arrived","sum"), Установлено=("qty_installed","sum")), width="stretch", hide_index=True)
        elif operational == "Готово, но не отправлено":
            st.dataframe(report_df[report_df["qty_ready"] > report_df["qty_shipped"]][["object_name","client_name","item_name","qty_ready","qty_shipped"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_ready":"Готово","qty_shipped":"Отправлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по доставкам":
            st.dataframe(report_df[["object_name","client_name","item_name","qty_shipped","qty_arrived"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_shipped":"Отправлено","qty_arrived":"Доставлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по монтажу":
            st.dataframe(report_df[["object_name","client_name","item_name","quantity_needed","qty_installed"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено"}), width="stretch", hide_index=True)
        else:
            incomplete = report_df[report_df["qty_installed"] < report_df["quantity_needed"]]
            st.dataframe(incomplete.groupby(["object_id","object_name","client_name"], as_index=False).agg(Запланировано=("quantity_needed","sum"), Выполнено=("qty_installed","sum"), Остаток=("Остаток","sum")), width="stretch", hide_index=True)

    # ========================================================
    # 4. STOCK REPORTS
    # ========================================================
    else:
        st.subheader("Складские отчёты")
        stock_report = st.selectbox(
            "Отчёт",
            ["Остатки материалов", "Материалы с низким остатком", "Потребность материалов по незавершённым объектам"],
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
            st.dataframe(stock.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        elif stock_report == "Материалы с низким остатком":
            low = stock[stock["stock_quantity"] <= 10].copy()
            st.dataframe(low.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        else:
            need = run_query("""
                SELECT o.object_name, c.name AS client_name, oi.item_name,
                       m.name AS material,
                       (oi.quantity_needed * ptm.quantity_per_unit * COALESCE(ptm.waste_coefficient,1)) AS required_quantity,
                       COALESCE(m.stock_quantity,0) AS stock_quantity
                FROM reklet.object_items oi
                JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                JOIN reklet.product_template_materials ptm ON ptm.product_template_id=oi.product_template_id
                JOIN reklet.materials m ON m.id=ptm.material_id
                WHERE COALESCE(oi.qty_installed,0) < COALESCE(oi.quantity_needed,0)
                ORDER BY o.object_name, oi.item_name, m.name
            """, fetch=True)
            st.dataframe(need.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","material":"Материал","required_quantity":"Требуется","stock_quantity":"На складе"}), width="stretch", hide_index=True)




# ============================================================
# PAYROLL
# ============================================================

elif menu == "Зарплата":

    st.header("Зарплата")

    if "payroll_section" not in st.session_state:
        st.session_state.payroll_section = "Производство"

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("Зарплата производства", key="payroll_production_btn", width="stretch"):
            st.session_state.payroll_section = "Производство"
    with b2:
        if st.button("Зарплата транспортировки", key="payroll_transport_btn", width="stretch"):
            st.session_state.payroll_section = "Транспортировка"
    with b3:
        if st.button("Зарплата монтажа", key="payroll_install_btn", width="stretch"):
            st.session_state.payroll_section = "Монтаж"
    with b4:
        if st.button("Сводка по зарплате", key="payroll_summary_btn", width="stretch"):
            st.session_state.payroll_section = "Сводка"

    st.markdown("---")

    # Себестоимость материалов одного элемента.
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
            COALESCE(o.delivery_cost, 0) AS stored_delivery_cost,
            COALESCE(SUM(
                ptm.quantity_per_unit *
                COALESCE(ptm.waste_coefficient, m.default_waste_coefficient, 1) *
                COALESCE(m.cost_per_unit, 0)
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
        GROUP BY
            oi.id, oi.object_id, o.object_name, c.name, oi.item_name,
            oi.quantity_needed, o.transport_distance_km, o.delivery_cost
        ORDER BY o.object_name, oi.item_name
        """,
        fetch=True
    )

    if payroll_items.empty:
        st.info("Нет элементов для расчёта зарплаты.")
    else:
        # Отбор по объекту применяется ко всем четырём разделам зарплаты.
        payroll_object_options = ["Все объекты"] + [
            f"{int(row['object_id'])} — {row['object_name']}"
            for _, row in payroll_items[["object_id", "object_name"]].drop_duplicates().iterrows()
        ]
        payroll_object_filter = st.selectbox(
            "Отбор по объекту",
            payroll_object_options,
            key=f"payroll_object_filter_{st.session_state.payroll_section}"
        )
        if payroll_object_filter != "Все объекты":
            payroll_object_id = int(payroll_object_filter.split(" — ")[0])
            payroll_items = payroll_items[payroll_items["object_id"] == payroll_object_id].copy()

        if payroll_items.empty:
            st.info("По выбранному объекту данных для расчёта зарплаты нет.")
            st.stop()

        # PostgreSQL numeric/Decimal values and nullable quantities are normalized
        # before arithmetic so Pandas never tries to multiply strings by numbers.
        numeric_cols = [
            "material_cost_per_unit",
            "distance_km",
            "quantity_needed"
        ]
        for col in numeric_cols:
            if col in payroll_items.columns:
                payroll_items[col] = pd.to_numeric(
                    payroll_items[col], errors="coerce"
                ).fillna(0.0)

        if st.session_state.payroll_section == "Производство":
            view = payroll_items.copy()
            view["Себестоимость материалов"] = view["material_cost_per_unit"]
            view["Количество"] = view["quantity_needed"]
            view["Зарплата производства"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
            view = view.rename(columns={"object_name":"Объект", "client_name":"Заказчик", "item_name":"Изделие"})
            st.caption("Зарплата производства рассчитывается сразу на всё количество изделий, указанное в объекте: себестоимость материалов × количество изделий × 1,50 (+50%).")
            st.dataframe(view[["Объект", "Заказчик", "Изделие", "Себестоимость материалов", "Количество", "Зарплата производства"]], width="stretch", hide_index=True)

        elif st.session_state.payroll_section == "Монтаж":
            view = payroll_items.copy()
            view["Себестоимость материалов"] = view["material_cost_per_unit"]
            view["Количество"] = view["quantity_needed"]
            view["Зарплата монтажа"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
            view = view.rename(columns={"object_name":"Объект", "client_name":"Заказчик", "item_name":"Изделие"})
            st.caption("Зарплата монтажа рассчитывается сразу на всё количество изделий, указанное в объекте: себестоимость материалов × количество изделий × 1,40 (+40%).")
            st.dataframe(view[["Объект", "Заказчик", "Изделие", "Себестоимость материалов", "Количество", "Зарплата монтажа"]], width="stretch", hide_index=True)

        elif st.session_state.payroll_section == "Транспортировка":
            view = payroll_items.copy()
            view["Себестоимость материалов"] = view["material_cost_per_unit"] * view["quantity_needed"]
            view["Количество"] = view["quantity_needed"]
            view["Зарплата транспортировки"] = view["Себестоимость материалов"] * 0.10 + view["distance_km"] * 2
            view = view.rename(columns={"object_name":"Объект", "client_name":"Заказчик", "item_name":"Изделие", "distance_km":"Расстояние, км"})
            st.caption("Зарплата транспортировки рассчитывается сразу на всё количество изделий, указанное в объекте: 10% от себестоимости материалов этого количества + расстояние × 2 условные единицы.")
            st.dataframe(view[["Объект", "Заказчик", "Изделие", "Себестоимость материалов", "Количество", "Расстояние, км", "Зарплата транспортировки"]], width="stretch", hide_index=True)

        else:
            view = payroll_items.copy()
            view["Производство"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.50
            view["Монтаж"] = view["material_cost_per_unit"] * view["quantity_needed"] * 1.40
            view["Доставка"] = (view["material_cost_per_unit"] * view["quantity_needed"] * 0.10) + view["distance_km"] * 2
            view["Итого"] = view["Производство"] + view["Монтаж"] + view["Доставка"]
            view = view.rename(columns={"object_name":"Объект", "client_name":"Заказчик", "item_name":"Изделие"})
            st.dataframe(view[["Объект", "Заказчик", "Изделие", "Производство", "Монтаж", "Доставка", "Итого"]], width="stretch", hide_index=True)

            summary = view.groupby(["Объект", "Заказчик"], as_index=False)[["Производство", "Монтаж", "Доставка", "Итого"]].sum()
            st.subheader("Сводка по объектам")
            st.dataframe(summary, width="stretch", hide_index=True)


# ============================================================
# REPORTS
# ============================================================

elif menu == "Отчёты":

    st.header("Отчёты")

    # ========================================================
    # REPORT BUTTONS
    # ========================================================
    if "reports_section" not in st.session_state:
        st.session_state["reports_section"] = "Сводные таблицы"

    rb1, rb2 = st.columns(2)
    rb3, rb4 = st.columns(2)

    with rb1:
        if st.button("Сводные таблицы", key="reports_summary_btn", use_container_width=True):
            st.session_state["reports_section"] = "Сводные таблицы"
            st.rerun()
    with rb2:
        if st.button("Печать документов", key="reports_print_btn", use_container_width=True):
            st.session_state["reports_section"] = "Печать документов"
            st.rerun()
    with rb3:
        if st.button("Операционные отчёты", key="reports_operational_btn", use_container_width=True):
            st.session_state["reports_section"] = "Операционные отчёты"
            st.rerun()
    with rb4:
        if st.button("Складские отчёты", key="reports_stock_btn", use_container_width=True):
            st.session_state["reports_section"] = "Складские отчёты"
            st.rerun()

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
            ptm.quantity_per_unit
            * m.cost_per_unit
            * COALESCE(ptm.waste_coefficient, 1)
        ), 0) AS material_unit_cost
    FROM reklet.object_items oi
    JOIN reklet.objects o ON o.id = oi.object_id
    LEFT JOIN reklet.clients c ON c.id = o.client_id
    LEFT JOIN reklet.product_template_materials ptm
        ON ptm.product_template_id = oi.product_template_id
    LEFT JOIN reklet.materials m ON m.id = ptm.material_id
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

    # ========================================================
    # 2. PRINT DOCUMENTS
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
                    "Скачать документ для печати (HTML)",
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
                st.download_button("Скачать документ для печати (HTML)", printable_html(title, body), title.replace(" ", "_") + ".html", "text/html", key="download_client_document")

        else:
            st.info("Накладные будут связаны непосредственно с движениями склада материалов. Выберите тип накладной — система покажет соответствующее движение для печати.")

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
            st.dataframe(card[["item_name","quantity_needed","qty_installed","qty_ready","qty_shipped","qty_arrived"]].rename(columns={"item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено","qty_ready":"Готово","qty_shipped":"Отправлено","qty_arrived":"Доставлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по производству":
            st.dataframe(report_df.groupby(["object_name","client_name"], as_index=False).agg(Заказано=("quantity_needed","sum"), Готово=("qty_ready","sum"), Доставлено=("qty_arrived","sum"), Установлено=("qty_installed","sum")), width="stretch", hide_index=True)
        elif operational == "Готово, но не отправлено":
            st.dataframe(report_df[report_df["qty_ready"] > report_df["qty_shipped"]][["object_name","client_name","item_name","qty_ready","qty_shipped"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_ready":"Готово","qty_shipped":"Отправлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по доставкам":
            st.dataframe(report_df[["object_name","client_name","item_name","qty_shipped","qty_arrived"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","qty_shipped":"Отправлено","qty_arrived":"Доставлено"}), width="stretch", hide_index=True)
        elif operational == "Отчёт по монтажу":
            st.dataframe(report_df[["object_name","client_name","item_name","quantity_needed","qty_installed"]].rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","quantity_needed":"Запланировано","qty_installed":"Установлено"}), width="stretch", hide_index=True)
        else:
            incomplete = report_df[report_df["qty_installed"] < report_df["quantity_needed"]]
            st.dataframe(incomplete.groupby(["object_id","object_name","client_name"], as_index=False).agg(Запланировано=("quantity_needed","sum"), Выполнено=("qty_installed","sum"), Остаток=("Остаток","sum")), width="stretch", hide_index=True)

    # ========================================================
    # 4. STOCK REPORTS
    # ========================================================
    else:
        st.subheader("Складские отчёты")
        stock_report = st.selectbox(
            "Отчёт",
            ["Остатки материалов", "Материалы с низким остатком", "Потребность материалов по незавершённым объектам"],
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
            st.dataframe(stock.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        elif stock_report == "Материалы с низким остатком":
            low = stock[stock["stock_quantity"] <= 10].copy()
            st.dataframe(low.rename(columns={"material":"Материал","unit":"Единица","stock_quantity":"Остаток","cost_per_unit":"Цена","stock_value":"Стоимость остатка"}), width="stretch", hide_index=True)
        else:
            need = run_query("""
                SELECT o.object_name, c.name AS client_name, oi.item_name,
                       m.name AS material,
                       (oi.quantity_needed * ptm.quantity_per_unit * COALESCE(ptm.waste_coefficient,1)) AS required_quantity,
                       COALESCE(m.stock_quantity,0) AS stock_quantity
                FROM reklet.object_items oi
                JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id
                JOIN reklet.product_template_materials ptm ON ptm.product_template_id=oi.product_template_id
                JOIN reklet.materials m ON m.id=ptm.material_id
                WHERE COALESCE(oi.qty_installed,0) < COALESCE(oi.quantity_needed,0)
                ORDER BY o.object_name, oi.item_name, m.name
            """, fetch=True)
            st.dataframe(need.rename(columns={"object_name":"Объект","client_name":"Заказчик","item_name":"Изделие","material":"Материал","required_quantity":"Требуется","stock_quantity":"На складе"}), width="stretch", hide_index=True)

