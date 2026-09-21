import streamlit as st
import pandas as pd
import psycopg2
import uuid
from html import escape


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Reklet — Production Management",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

# All database credentials are stored in Streamlit Cloud Secrets.
#
# Required secrets:
#
# DB_HOST = "aws-0-us-west-2.pooler.supabase.com"
# DB_PORT = "5432"
# DB_NAME = "postgres"
# DB_USER = "postgres.lnkaohubtchmsiniepoc"
# DB_PASSWORD = "YOUR_DATABASE_PASSWORD"
# ADMIN_PASSWORD = "YOUR_ADMIN_PASSWORD"

try:
    DB_HOST = st.secrets["DB_HOST"]
    DB_PORT = int(st.secrets["DB_PORT"])
    DB_NAME = st.secrets["DB_NAME"]
    DB_USER = st.secrets["DB_USER"]
    DB_PASSWORD = st.secrets["DB_PASSWORD"]
    ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]

except Exception as e:

    st.error("Database secrets are not configured.")

    st.code(
        """
DB_HOST = "aws-0-us-west-2.pooler.supabase.com"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "postgres.lnkaohubtchmsiniepoc"
DB_PASSWORD = "YOUR_DATABASE_PASSWORD"
ADMIN_PASSWORD = "YOUR_ADMIN_PASSWORD"
        """
    )

    st.caption(
        "Add these values in Streamlit Cloud → Settings → Secrets."
    )

    st.stop()


# ============================================================
# DATABASE CONNECTION
# ============================================================

@st.cache_resource
def get_connection():

    # This connection is used only for application startup/migrations.
    # Authenticated sessions use their own connection below so demo
    # transactions are isolated from other users.
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
        sslmode="require",
        options="-c statement_timeout=30000 -c lock_timeout=5000"
    )


def get_session_connection():

    if "db_connection" not in st.session_state:
        st.session_state["db_connection"] = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=10,
            sslmode="require"
        )

    return st.session_state["db_connection"]


def close_demo_connection():

    conn = st.session_state.pop("db_connection", None)

    if conn is not None:
        try:
            if not conn.closed:
                conn.rollback()
                conn.close()
        except Exception:
            pass


def run_query(query, params=None, fetch=False):

    # Admin keeps the existing committed-database behaviour.
    # Demo users work inside one PostgreSQL transaction for their entire
    # Streamlit session. All INSERT/UPDATE/DELETE operations are therefore
    # visible to the demo user, but never committed to the real database.
    if st.session_state.get("demo_mode", False):
        conn = get_session_connection()
    else:
        conn = get_connection()

    cursor = conn.cursor()
    demo = st.session_state.get("demo_mode", False)
    savepoint = None

    try:

        if demo:
            savepoint = f"demo_sp_{uuid.uuid4().hex}"
            cursor.execute(f'SAVEPOINT {savepoint}')

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

            if demo:
                cursor.execute(f'RELEASE SAVEPOINT {savepoint}')

            return result

        if demo:
            cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
        else:
            conn.commit()

        return None

    except Exception:

        if demo and savepoint:
            try:
                cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
                cursor.execute(f'RELEASE SAVEPOINT {savepoint}')
            except Exception:
                conn.rollback()
        else:
            conn.rollback()

        raise

    finally:

        cursor.close()


# ============================================================
# DATABASE MIGRATION
# ============================================================

def initialize_database():

    statements = [

        """
        ALTER TABLE reklet.materials
        ADD COLUMN IF NOT EXISTS category_id int4 NULL
        """,

        """
        CREATE TABLE IF NOT EXISTS reklet.material_categories (
            id serial4 PRIMARY KEY,
            name text NOT NULL UNIQUE,
            created_at timestamptz DEFAULT timezone('utc'::text, now()) NOT NULL
        )
        """,

        """
        ALTER TABLE reklet.materials
        ADD COLUMN IF NOT EXISTS category_id int4 NULL
        """,

        """
        ALTER TABLE reklet.suppliers
        ADD COLUMN IF NOT EXISTS notes text NULL
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_materials_category
        ON reklet.materials(category_id)
        """,

        """
        CREATE TABLE IF NOT EXISTS reklet.material_categories (
            id serial4 PRIMARY KEY,
            name text NOT NULL UNIQUE,
            created_at timestamptz DEFAULT timezone('utc'::text, now()) NOT NULL
        )
        """,

        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'materials_category_fk'
            ) THEN
                ALTER TABLE reklet.materials
                ADD CONSTRAINT materials_category_fk
                FOREIGN KEY (category_id)
                REFERENCES reklet.material_categories(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_finished_goods_tx_item_created
        ON reklet.finished_goods_transactions(object_item_id, created_at)
        """,

        """
        CREATE TABLE IF NOT EXISTS reklet.installation_transactions (
            id serial4 PRIMARY KEY,
            object_item_id int4 NOT NULL,
            object_id int4 NULL,
            quantity int4 NOT NULL,
            created_at timestamptz DEFAULT timezone('utc'::text, now()) NOT NULL,
            FOREIGN KEY (object_item_id) REFERENCES reklet.object_items(id) ON DELETE CASCADE,
            FOREIGN KEY (object_id) REFERENCES reklet.objects(id) ON DELETE SET NULL
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS reklet.payroll_records (
            id serial4 PRIMARY KEY,
            object_item_id int4 NULL,
            department text NOT NULL,
            base_material_cost numeric(12,2) DEFAULT 0,
            calculated_amount numeric(12,2) DEFAULT 0,
            manual_override_amount numeric(12,2) NULL,
            is_manual boolean DEFAULT false,
            updated_at timestamptz DEFAULT timezone('utc'::text, now()) NOT NULL,
            FOREIGN KEY (object_item_id) REFERENCES reklet.object_items(id) ON DELETE SET NULL
        )
        """,

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

try:

    initialize_database()

except Exception as e:

    st.error("Database initialization error.")

    st.code(str(e))

    st.stop()


# ============================================================
# AUTHENTICATION
# ============================================================

if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None

if "demo_mode" not in st.session_state:
    st.session_state["demo_mode"] = False


if not st.session_state["authentication_status"]:

    st.title("Reklet — Production Management")
    st.subheader("Login")

    with st.form("login_form"):

        username_input = st.text_input("Username")

        password_input = st.text_input(
            "Password",
            type="password"
        )

        submit_login = st.form_submit_button("Login")

        if submit_login:

            # ==================================================
            # ADMIN LOGIN
            # ==================================================

            if (
                username_input == "admin"
                and password_input == ADMIN_PASSWORD
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

                # Demo mode uses a private, uncommitted PostgreSQL
                # transaction. The user can create/edit/delete anything
                # during the session, but none of it reaches the real DB.
                st.session_state["demo_mode"] = True
                get_session_connection().rollback()

                st.rerun()


            # ==================================================
            # INVALID LOGIN
            # ==================================================

            else:

                st.session_state["authentication_status"] = False

                st.error(
                    "Invalid username or password"
                )

    st.stop()


# ============================================================
# LOGOUT
# ============================================================

if st.sidebar.button("Logout"):

    # Demo data exists only inside the current PostgreSQL transaction.
    # Roll it back and close the session connection before logging out.
    if st.session_state.get("demo_mode", False):
        close_demo_connection()

    st.session_state[
        "authentication_status"
    ] = None
    st.session_state["demo_mode"] = False
    st.session_state.pop("username", None)
    st.session_state.pop("name", None)

    st.rerun()


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


def ru_df(df, mapping):
    """Return a display-only copy with human Russian column names."""
    if df is None or df.empty:
        return df
    out = df.copy()
    return out.rename(columns={k: v for k, v in mapping.items() if k in out.columns})


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


def get_materials():

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


def get_material_categories():
    return run_query(
        """
        SELECT id, name
        FROM reklet.material_categories
        ORDER BY name
        """,
        fetch=True
    )


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

        ORDER BY client_name NULLS LAST, id DESC
        """,
        fetch=True
    )


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
# NAVIGATION
# ============================================================

menu_options = [
    "Заказчики",
    "Объекты",
    "Изделия",
    "Материалы",
    "Поставщики",
    "Производство",
    "Склад готовой продукции",
    "Доставка",
    "Монтаж",
    "Зарплата",
    "Отчёты"
]

menu = st.radio(
    "Навигация",
    menu_options,
    horizontal=True,
    label_visibility="collapsed"
)
menu = {
    "Заказчики":"Clients",
    "Объекты":"Objects",
    "Изделия":"Product Templates",
    "Материалы":"Materials Warehouse",
    "Поставщики":"Suppliers",
    "Производство":"Production",
    "Склад готовой продукции":"Finished Goods",
    "Доставка":"Transport & Logistics",
    "Монтаж":"Installation",
    "Зарплата":"Payroll",
    "Отчёты":"Reports"
}[menu]


st.markdown("---")


# ============================================================
# CLIENTS
# ============================================================

if menu == "Заказчики":

    st.header("Заказчики")

    df = get_clients()

    if not df.empty:

        edited = st.data_editor(
            df,
            key="clients_editor",
            use_container_width=True,
            num_rows="fixed"
        )

        if st.button(
            "Сохранить изменения",
            key="save_clients"
        ):

            for _, row in edited.iterrows():

                run_query(
                    """
                    UPDATE reklet.clients

                    SET
                        name = %s,
                        contact_info = %s

                    WHERE id = %s
                    """,
                    (
                        row["name"],
                        row["contact_info"],
                        safe_int(row["id"])
                    )
                )

            st.success("Изменения сохранены.")

            st.rerun()

    else:

        st.info("No clients.")

    st.markdown("---")

    st.subheader("Add Client")

    with st.form("add_client"):

        name = st.text_input("Название")

        contact = st.text_area(
            "Контактная информация"
        )

        submit = st.form_submit_button(
            "Добавить"
        )

        if submit:

            if not name.strip():

                st.warning(
                    "Name is required."
                )

            else:

                run_query(
                    """
                    INSERT INTO reklet.clients
                    (
                        name,
                        contact_info
                    )

                    VALUES (%s,%s)
                    """,
                    (
                        name.strip(),
                        contact
                    )
                )

                st.success(
                    "Client added."
                )

                st.rerun()


    # --------------------------------------------------------
    # DELETE CLIENT — LAST AND CONTROLLED
    # --------------------------------------------------------
    st.markdown("---")
    with st.expander("Удалить заказчика", expanded=False):
        st.warning(
            "Deleting a client is permanent. A client that is already used "
            "by an object or product cannot be deleted."
        )

        clients_for_delete = get_clients()

        if clients_for_delete.empty:
            st.info("No clients available to delete.")
        else:
            client_delete_map = {
                f"{row['id']} — {row['name']}": int(row['id'])
                for _, row in clients_for_delete.iterrows()
            }

            client_delete_label = st.selectbox(
                "Заказчик для удаления",
                list(client_delete_map.keys()),
                key="delete_client_select"
            )

            client_delete_id = client_delete_map[client_delete_label]

            client_refs = run_query(
                """
                SELECT
                    (SELECT COUNT(*) FROM reklet.objects WHERE client_id = %s) AS object_count,
                    (SELECT COUNT(*) FROM reklet.product_templates pt
                     JOIN reklet.clients c ON c.id = %s
                     WHERE pt.client_name = c.name) AS product_count
                """,
                (client_delete_id, client_delete_id),
                fetch=True
            )

            object_count = int(client_refs.iloc[0]["object_count"])
            product_count = int(client_refs.iloc[0]["product_count"])

            if object_count or product_count:
                st.error(
                    f"Cannot delete this client. It is already used. "
                    f"Objects: {object_count}; Products: {product_count}."
                )
            else:
                confirm_client_delete = st.checkbox(
                    "Подтверждаю окончательное удаление заказчика",
                    key="confirm_client_delete"
                )
                if st.button("Удалить заказчика", key="delete_client_button"):
                    if not confirm_client_delete:
                        st.warning("Please confirm the deletion first.")
                    else:
                        run_query(
                            "DELETE FROM reklet.clients WHERE id = %s",
                            (client_delete_id,)
                        )
                        st.success("Client deleted.")
                        st.rerun()


# ============================================================
# OBJECTS
# ============================================================

elif menu == "Objects":

    st.header("Объекты")

    sub = st.radio(
        "Раздел",
        [
            "Перечень объектов",
            "Содержимое объекта",
            "Потребность в материалах"
        ],
        horizontal=True
    )

    st.markdown("---")


    # ========================================================
    # OBJECT LIST
    # ========================================================

    if sub == "Перечень объектов":

        clients = get_clients()

        df = get_objects()

        if not df.empty:

            display = df[
                ["id", "object_name", "client_name", "address"]
            ].copy()
            display.columns = ["№", "Объект", "Заказчик", "Адрес"]

            edited = st.data_editor(
                display,
                key="objects_editor",
                use_container_width=True
            )

            if st.button(
                "Сохранить изменения",
                key="save_objects"
            ):

                for _, row in edited.iterrows():

                    run_query(
                        """
                        UPDATE reklet.objects

                        SET
                            object_name = %s,
                            address = %s

                        WHERE id = %s
                        """,
                        (
                            row["Объект"],
                            row["Адрес"],
                            safe_int(row["id"])
                        )
                    )

                st.success("Изменения сохранены.")

                st.rerun()


        st.markdown("---")

        st.subheader("Создать объект")

        client_map = {}

        if not clients.empty:

            client_map = {
                str(row["name"]): int(row["id"])
                for _, row in clients.iterrows()
            }


        with st.form("create_object"):

            client_name = st.selectbox(
                "Заказчик",
                list(client_map.keys())
                if client_map
                else []
            )

            object_name = st.text_input(
                "Название объекта"
            )

            address = st.text_input(
                "Адрес"
            )

            phone = st.text_input(
                "Телефон"
            )

            contact_person = st.text_input(
                "Контактное лицо"
            )

            notes = st.text_area(
                "Примечания"
            )

            c1, c2 = st.columns(2)

            with c1:

                distance = st.number_input(
                    "Расстояние доставки (км)",
                    min_value=0.0,
                    value=0.0
                )

                delivery_cost = st.number_input(
                    "Стоимость доставки",
                    min_value=0.0,
                    value=0.0
                )

                contract_date = st.date_input(
                    "Дата договора",
                    value=None
                )

                production_start = st.date_input(
                    "Начало производства",
                    value=None
                )

                production_end = st.date_input(
                    "Окончание производства",
                    value=None
                )

            with c2:

                installation_date = st.date_input(
                    "Дата монтажа",
                    value=None
                )

                installation_end = st.date_input(
                    "Окончание монтажа",
                    value=None
                )

            submit = st.form_submit_button(
                "Создать объект"
            )

            if submit:

                if (
                    not client_name
                    or not object_name.strip()
                ):

                    st.warning(
                        "Необходимо указать заказчика и название объекта."
                    )

                else:

                    run_query(
                        """
                        INSERT INTO reklet.objects
                        (
                            client_id,
                            object_name,
                            address,
                            phone,
                            contact_person,
                            notes,
                            transport_distance_km,
                            delivery_cost,
                            contract_date,
                            production_start_date,
                            production_end_date,
                            installation_date,
                            installation_end_date
                        )

                        VALUES
                        (
                            %s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s
                        )
                        """,
                        (
                            client_map[client_name],
                            object_name,
                            address,
                            phone,
                            contact_person,
                            notes,
                            distance,
                            delivery_cost,
                            contract_date,
                            production_start,
                            production_end,
                            installation_date,
                            installation_end
                        )
                    )

                    st.success(
                        "Объект создан."
                    )

                    st.rerun()


    # ========================================================
    # OBJECT CONTENT
    # ========================================================

    elif sub == "Содержимое объекта":

        objects = get_objects()

        if objects.empty:

            st.info(
                "Объектов пока нет."
            )

        else:

            object_map = {
                f"{row['id']} — "
                f"{row['object_name']} — "
                f"{row['client_name']}":
                    int(row["id"])

                for _, row in objects.iterrows()
            }

            selected = st.selectbox(
                "Объект (сначала последние):",
                list(object_map.keys())
            )

            object_id = object_map[selected]

            object_row = objects[
                objects["id"] == object_id
            ].iloc[0]

            st.subheader(
                f"{object_row['object_name']} / "
                f"{object_row['client_name']}"
            )

            items = get_object_items(
                object_id
            )

            if not items.empty:

                display = items[
                    [
                        "id",
                        "item_name",
                        "quantity",
                        "qty_new",
                        "qty_production",
                        "qty_ready",
                        "qty_shipped",
                        "qty_arrived",
                        "qty_installing",
                        "qty_installed"
                    ]
                ].copy()

                display.columns = [
                    "№", "Изделие", "Всего заказано", "К запуску", "В производстве",
                    "Готово", "Отправлено", "Доставлено", "В монтаже", "Установлено"
                ]
                edited = st.data_editor(
                    display,
                    key=f"object_items_{object_id}",
                    use_container_width=True
                )

                if st.button(
                    "Сохранить количество",
                    key=f"save_items_{object_id}"
                ):

                    for _, row in edited.iterrows():

                        qty_new = safe_int(
                            row["К запуску"]
                        )

                        qty_production = safe_int(
                            row["В производстве"]
                        )

                        qty_ready = safe_int(
                            row["Готово"]
                        )

                        qty_shipped = safe_int(
                            row["Отправлено"]
                        )

                        qty_arrived = safe_int(
                            row["Доставлено"]
                        )

                        qty_installing = safe_int(
                            row["В монтаже"]
                        )

                        qty_installed = safe_int(
                            row["Установлено"]
                        )

                        total = (
                            qty_new
                            + qty_production
                            + qty_ready
                            + qty_shipped
                            + qty_arrived
                            + qty_installing
                            + qty_installed
                        )

                        run_query(
                            """
                            UPDATE reklet.object_items

                            SET
                                item_name = %s,
                                quantity = %s,
                                quantity_needed = %s,
                                qty_new = %s,
                                qty_production = %s,
                                qty_ready = %s,
                                qty_shipped = %s,
                                qty_arrived = %s,
                                qty_installing = %s,
                                qty_installed = %s

                            WHERE id = %s
                            """,
                            (
                                row["Изделие"],
                                total,
                                total,
                                qty_new,
                                qty_production,
                                qty_ready,
                                qty_shipped,
                                qty_arrived,
                                qty_installing,
                                qty_installed,
                                safe_int(row["id"])
                            )
                        )

                    st.success("Изменения сохранены.")

                    st.rerun()

            else:

                st.info(
                    "В этом объекте пока нет изделий."
                )


            st.markdown("---")

            st.subheader(
                "Добавить изделие"
            )

            # Show only product templates belonging to the selected object's client.
            # A product can have the same name/dimensions for different clients,
            # so the client assigned to the object is the filter here.
            templates = get_templates()
            object_client_name = str(
                object_row["client_name"] or ""
            ).strip()

            if not object_client_name:
                st.warning(
                    "This object has no client assigned, so products cannot be filtered by client."
                )
                templates = templates.iloc[0:0]
            else:
                templates = templates[
                    templates["client_name"].fillna("").astype(str).str.strip().eq(
                        object_client_name
                    )
                ].copy()

            if not templates.empty:

                template_map = {
                    f"{row['name']} — {row['client_name']}":
                        int(row["id"])

                    for _, row in templates.iterrows()
                }

                with st.form(
                    f"add_item_{object_id}"
                ):

                    template_label = st.selectbox(
                        "Изделие",
                        list(template_map.keys())
                    )

                    quantity = st.number_input(
                        "Количество",
                        min_value=1,
                        value=1,
                        step=1
                    )

                    submit = st.form_submit_button(
                        "Добавить изделие"
                    )

                    if submit:

                        template_id = template_map[
                            template_label
                        ]

                        template_row = templates[
                            templates["id"] == template_id
                        ].iloc[0]

                        existing_item = run_query(
                            """
                            SELECT id
                            FROM reklet.object_items
                            WHERE object_id = %s
                              AND product_template_id = %s
                            ORDER BY id
                            LIMIT 1
                            """,
                            (object_id, template_id),
                            fetch=True
                        )

                        if not existing_item.empty:
                            run_query(
                                """
                                UPDATE reklet.object_items
                                SET
                                    quantity = COALESCE(quantity, 0) + %s,
                                    quantity_needed = COALESCE(quantity_needed, 0) + %s,
                                    qty_new = COALESCE(qty_new, 0) + %s,
                                    item_name = %s
                                WHERE id = %s
                                """,
                                (
                                    quantity,
                                    quantity,
                                    quantity,
                                    template_row["name"],
                                    int(existing_item.iloc[0]["id"])
                                )
                            )
                            st.success(
                                f"Количество изделия увеличено на {quantity}."
                            )
                        else:
                            run_query(
                                """
                                INSERT INTO reklet.object_items
                                (
                                    object_id,
                                    product_template_id,
                                    template_id,
                                    quantity_needed,
                                    item_name,
                                    quantity,
                                    qty_new,
                                    status
                                )
                                VALUES
                                (%s,%s,%s,%s,%s,%s,%s,'New')
                                """,
                                (
                                    object_id,
                                    template_id,
                                    template_id,
                                    quantity,
                                    template_row["name"],
                                    quantity,
                                    quantity
                                )
                            )
                            st.success("Изделие добавлено.")

                        st.rerun()


            st.markdown("---")

            st.subheader(
                "Спецификация"
            )

            items_print = get_object_items(
                object_id
            )

            rows = ""

            if not items_print.empty:

                for i, row in items_print.iterrows():

                    rows += f"""
                    <tr>
                        <td>{i + 1}</td>
                        <td>
                            {escape(
                                str(
                                    row["item_name"]
                                    or ""
                                )
                            )}
                        </td>
                        <td>
                            {safe_int(
                                row["quantity"]
                            )}
                        </td>
                    </tr>
                    """

            html = f"""
            <!DOCTYPE html>

            <html>

            <head>

                <meta charset="utf-8">

                <title>
                    Specification
                </title>

                <style>

                    body {{
                        font-family: Arial;
                        margin: 40px;
                    }}

                    table {{
                        width: 100%;
                        border-collapse: collapse;
                    }}

                    th, td {{
                        border: 1px solid #999;
                        padding: 8px;
                    }}

                    th {{
                        background: #eee;
                    }}

                </style>

            </head>

            <body>

                <h2>
                    Object Specification
                </h2>

                <p>
                    <b>Заказчик:</b>
                    {escape(
                        str(
                            object_row["client_name"]
                            or ""
                        )
                    )}
                </p>

                <p>
                    <b>Объект:</b>
                    {escape(
                        str(
                            object_row["object_name"]
                            or ""
                        )
                    )}
                </p>

                <p>
                    <b>Адрес:</b>
                    {escape(
                        str(
                            object_row["address"]
                            or ""
                        )
                    )}
                </p>

                <table>

                    <tr>
                        <th>№</th>
                        <th>Изделие</th>
                        <th>Количество</th>
                    </tr>

                    {rows}

                </table>

                <script>
                    window.print();
                </script>

            </body>

            </html>
            """

            st.download_button(
                "Скачать спецификацию",
                data=html,
                file_name=(
                    f"specification_{object_id}.html"
                ),
                mime="text/html"
            )


    # ========================================================
    # MATERIAL REQUIREMENTS
    # ========================================================

    else:

        st.subheader(
            "Потребность в материалах"
        )

        objects = get_objects()

        if objects.empty:

            st.info(
                "Объектов пока нет."
            )

        else:

            object_map = {
                f"{row['id']} — "
                f"{row['object_name']} — "
                f"{row['client_name']}":
                    int(row["id"])

                for _, row in objects.iterrows()
            }

            selected = st.selectbox(
                "Объект",
                list(object_map.keys()),
                key="material_requirement_object"
            )

            object_id = object_map[
                selected
            ]

            object_row = objects[
                objects["id"] == object_id
            ].iloc[0]

            items = get_object_items(
                object_id
            )

            if items.empty:

                st.info(
                    "No products assigned to this object."
                )

            else:

                requirements = run_query(
                    """
                    SELECT

                        oi.id AS object_item_id,

                        oi.item_name,

                        oi.quantity
                            AS product_quantity,

                        ptm.material_id,

                        m.name
                            AS material_name,

                        u.name
                            AS unit_name,

                        ptm.quantity_per_unit,

                        COALESCE(
                            ptm.waste_coefficient,
                            m.default_waste_coefficient,
                            1
                        ) AS waste_coefficient,

                        m.cost_per_unit,

                        m.stock_quantity

                    FROM reklet.object_items oi

                    JOIN reklet.product_templates pt

                        ON pt.id = COALESCE(
                            oi.product_template_id,
                            oi.template_id
                        )

                    JOIN
                        reklet.product_template_materials ptm

                        ON ptm.product_template_id =
                           pt.id

                    JOIN reklet.materials m

                        ON m.id = ptm.material_id

                    LEFT JOIN reklet.units u

                        ON u.id = m.unit_id

                    WHERE oi.object_id = %s

                    ORDER BY
                        oi.item_name,
                        m.name
                    """,
                    (object_id,),
                    fetch=True
                )

                if requirements.empty:

                    st.warning(
                        "No material specifications are "
                        "defined for the products of this object."
                    )

                else:

                    requirements[
                        "required_quantity"
                    ] = (
                        requirements["product_quantity"]
                        *
                        requirements["quantity_per_unit"]
                        *
                        requirements["waste_coefficient"]
                    )

                    requirements[
                        "material_cost"
                    ] = (
                        requirements[
                            "required_quantity"
                        ]
                        *
                        requirements[
                            "cost_per_unit"
                        ]
                    )

                    st.markdown(
                        "### Material Requirements by Product"
                    )

                    product_view = requirements[
                        [
                            "item_name",
                            "product_quantity",
                            "material_name",
                            "unit_name",
                            "quantity_per_unit",
                            "waste_coefficient",
                            "required_quantity",
                            "cost_per_unit",
                            "material_cost"
                        ]
                    ].copy()

                    product_view.columns = [

                        "Изделие",
                        "Количество изделий",
                        "Материал",
                        "Единица",
                        "На изделие",
                        "Коэффициент отходов",
                        "Требуется",
                        "Цена",
                        "Стоимость"

                    ]

                    st.dataframe(
                        product_view,
                        use_container_width=True,
                        hide_index=True
                    )

                    st.markdown(
                        "### Total Material Requirements"
                    )

                    total_materials = (
                        requirements
                        .groupby(
                            [
                                "material_id",
                                "material_name",
                                "unit_name",
                                "stock_quantity",
                                "cost_per_unit"
                            ],
                            dropna=False
                        )
                        .agg(
                            required_quantity=(
                                "required_quantity",
                                "sum"
                            ),
                            material_cost=(
                                "material_cost",
                                "sum"
                            )
                        )
                        .reset_index()
                    )

                    total_materials[
                        "shortage"
                    ] = (
                        total_materials[
                            "required_quantity"
                        ]
                        -
                        total_materials[
                            "stock_quantity"
                        ]
                    ).clip(
                        lower=0
                    )

                    total_view = total_materials[
                        [
                            "material_name",
                            "unit_name",
                            "required_quantity",
                            "stock_quantity",
                            "shortage",
                            "cost_per_unit",
                            "material_cost"
                        ]
                    ].copy()

                    total_view.columns = [

                        "Материал",
                        "Единица",
                        "Требуется",
                        "Остаток",
                        "Недостача",
                        "Цена",
                        "Стоимость"

                    ]

                    st.dataframe(
                        total_view,
                        use_container_width=True,
                        hide_index=True
                    )

                    total_cost = (
                        total_materials[
                            "material_cost"
                        ].sum()
                    )

                    st.metric(
                        "Расчётная стоимость материалов",
                        money(total_cost)
                    )

                    html_rows = ""

                    for i, row in total_materials.iterrows():

                        html_rows += f"""
                        <tr>

                            <td>
                                {i + 1}
                            </td>

                            <td>
                                {escape(
                                    str(
                                        row["material_name"]
                                    )
                                )}
                            </td>

                            <td>
                                {escape(
                                    str(
                                        row["unit_name"]
                                        or ""
                                    )
                                )}
                            </td>

                            <td>
                                {float(
                                    row[
                                        "required_quantity"
                                    ]
                                ):.4f}
                            </td>

                            <td>
                                {float(
                                    row[
                                        "stock_quantity"
                                    ]
                                ):.4f}
                            </td>

                            <td>
                                {float(
                                    row["shortage"]
                                ):.4f}
                            </td>

                            <td>
                                {float(
                                    row[
                                        "material_cost"
                                    ]
                                ):.2f}
                            </td>

                        </tr>
                        """

                    material_html = f"""
                    <!DOCTYPE html>

                    <html>

                    <head>

                        <meta charset="utf-8">

                        <title>
                            Material Requirements
                        </title>

                        <style>

                            body {{
                                font-family: Arial;
                                margin: 35px;
                            }}

                            table {{
                                width: 100%;
                                border-collapse: collapse;
                            }}

                            th, td {{
                                border: 1px solid #999;
                                padding: 8px;
                            }}

                            th {{
                                background-color: #eeeeee;
                            }}

                        </style>

                    </head>

                    <body>

                        <h2>
                            Material Requirements
                        </h2>

                        <p>
                            <b>Заказчик:</b>
                            {escape(
                                str(
                                    object_row[
                                        "client_name"
                                    ]
                                    or ""
                                )
                            )}
                        </p>

                        <p>
                            <b>Объект:</b>
                            {escape(
                                str(
                                    object_row[
                                        "object_name"
                                    ]
                                    or ""
                                )
                            )}
                        </p>

                        <p>
                            <b>Адрес:</b>
                            {escape(
                                str(
                                    object_row[
                                        "address"
                                    ]
                                    or ""
                                )
                            )}
                        </p>

                        <table>

                            <tr>

                                <th>№</th>
                                <th>Material</th>
                                <th>Unit</th>
                                <th>Required</th>
                                <th>Stock</th>
                                <th>Shortage</th>
                                <th>Cost</th>

                            </tr>

                            {html_rows}

                        </table>

                        <h3>

                            Total Material Cost:
                            {float(total_cost):.2f}

                        </h3>

                        <script>
                            window.print();
                        </script>

                    </body>

                    </html>
                    """

                    st.download_button(
                        "Скачать спецификацию материалов для печати",
                        data=material_html,
                        file_name=(
                            f"material_requirements_"
                            f"{object_id}.html"
                        ),
                        mime="text/html"
                    )


    # --------------------------------------------------------
    # DELETE OBJECT — LAST AND CONTROLLED
    # --------------------------------------------------------
    if sub == "Перечень объектов":
        st.markdown("---")
        with st.expander("Удалить объект", expanded=False):
            st.warning(
                "Deleting an object is permanent. An object that has "
                "products, material issues, payroll, or finished goods "
                "cannot be deleted."
            )

            objects_for_delete = get_objects()

            if objects_for_delete.empty:
                st.info("No objects available to delete.")
            else:
                object_delete_map = {
                    f"{row['id']} — {row['object_name']}"
                    + (f" — {row['client_name']}" if row['client_name'] else ""): int(row['id'])
                    for _, row in objects_for_delete.iterrows()
                }

                object_delete_label = st.selectbox(
                    "Объект для удаления",
                    list(object_delete_map.keys()),
                    key="delete_object_select"
                )
                object_delete_id = object_delete_map[object_delete_label]

                object_refs = run_query(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM reklet.object_items WHERE object_id = %s) AS item_count,
                        (SELECT COUNT(*) FROM reklet.material_transactions WHERE object_id = %s) AS material_tx_count,
                        (SELECT COUNT(*)
                         FROM reklet.payroll_records pr
                         JOIN reklet.object_items oi ON oi.id = pr.object_item_id
                         WHERE oi.object_id = %s) AS payroll_count,
                        (SELECT COUNT(*) FROM reklet.finished_goods WHERE object_id = %s) AS finished_goods_count,
                        (SELECT COUNT(*) FROM reklet.finished_goods_transactions WHERE object_id = %s) AS finished_goods_tx_count
                    """,
                    (object_delete_id,) * 5,
                    fetch=True
                )

                refs = object_refs.iloc[0]
                ref_counts = {
                    "Products in object": int(refs["item_count"]),
                    "Material transactions": int(refs["material_tx_count"]),
                    "Payroll records": int(refs["payroll_count"]),
                    "Finished goods": int(refs["finished_goods_count"]),
                    "Finished goods transactions": int(refs["finished_goods_tx_count"]),
                }
                used_refs = {k: v for k, v in ref_counts.items() if v}

                if used_refs:
                    st.error(
                        "Cannot delete this object because it is already used: "
                        + "; ".join(f"{k}: {v}" for k, v in used_refs.items())
                    )
                else:
                    confirm_object_delete = st.checkbox(
                        "Подтверждаю окончательное удаление объекта",
                        key="confirm_object_delete"
                    )
                    if st.button("Удалить объект", key="delete_object_button"):
                        if not confirm_object_delete:
                            st.warning("Please confirm the deletion first.")
                        else:
                            run_query(
                                "DELETE FROM reklet.objects WHERE id = %s",
                                (object_delete_id,)
                            )
                            st.success("Object deleted.")
                            st.rerun()


# ============================================================
# PRODUCT TEMPLATES
# ============================================================

elif menu == "Product Templates":

    st.header("Изделия")

    sub = st.radio(
        "Изделия",
        [
            "Перечень изделий",
            "Содержимое изделия"
        ],
        horizontal=True
    )

    st.markdown("---")


    # ========================================================
    # PRODUCTS LIST
    # ========================================================

    if sub == "Перечень изделий":

        templates = get_templates()
        clients = get_clients()

        client_filter_options = ["Все заказчики"] + [str(x) for x in clients["name"].tolist()] if not clients.empty else ["Все заказчики"]
        product_client_filter = st.selectbox(
            "Отбор по заказчику",
            client_filter_options,
            key="product_client_filter"
        )
        if product_client_filter != "Все заказчики":
            templates = templates[
                templates["client_name"].fillna("").astype(str).eq(product_client_filter)
            ].copy()

        st.subheader("Изделия")

        if templates.empty:
            st.info("No products yet.")
        else:
            display = templates[
                [
                    "id",
                    "name",
                    "type",
                    "client_name",
                    "category"
                ]
            ].copy()

            display.columns = [
                "ID",
                "Изделие",
                "Тип",
                "Заказчик",
                "Категория"
            ]

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True
            )

        st.markdown("---")

        st.subheader("Создать изделие")

        clients = get_clients()
        product_create_clients = clients.copy()
        if product_client_filter != "Все заказчики":
            product_create_clients = product_create_clients[product_create_clients["name"].astype(str).eq(product_client_filter)].copy()
        client_options = ["— Без заказчика —"]
        client_map = {}

        if not clients.empty:
            client_options += [
                f"{row['id']} — {row['name']}"
                for _, row in product_create_clients.iterrows()
            ]
            client_map = {
                f"{row['id']} — {row['name']}": row['name']
                for _, row in product_create_clients.iterrows()
            }

        with st.form("create_template"):

            name = st.text_input("Название изделия")

            type_value = st.selectbox(
                "Тип",
                [
                    "recurrent",
                    "custom"
                ]
            )

            client_selection = st.selectbox(
                "Заказчик",
                client_options,
                key="create_product_client"
            )
            client_name = client_map.get(client_selection)

            # Use existing product categories as a dropdown.
            category_values = sorted({
                str(value).strip()
                for value in templates["category"].dropna().tolist()
                if str(value).strip()
            }) if "category" in templates.columns else []

            category_options = ["— Без категории —"] + category_values

            category_selection = st.selectbox(
                "Категория",
                category_options,
                key="create_product_category"
            )
            category = None if category_selection == "— Без категории —" else category_selection

            submit = st.form_submit_button("Создать изделие")

            if submit:

                if not name.strip():
                    st.warning("Product name is required.")

                else:
                    run_query(
                        """
                        INSERT INTO reklet.product_templates
                        (
                            name,
                            type,
                            client_name,
                            category
                        )
                        VALUES (%s,%s,%s,%s)
                        """,
                        (
                            name.strip(),
                            type_value,
                            client_name or None,
                            category or None
                        )
                    )

                    st.success("Product created.")
                    st.rerun()

        # ----------------------------------------------------
        # EDIT PRODUCT
        # ----------------------------------------------------

        if not templates.empty:

            st.markdown("---")
            st.subheader("Исправить изделие")

            product_map = {
                f"{row['id']} — {row['name']}": int(row["id"])
                for _, row in templates.iterrows()
            }

            edit_label = st.selectbox(
                "Изделие",
                list(product_map.keys()),
                key="edit_product"
            )

            edit_id = product_map[edit_label]
            edit_row = templates[templates["id"] == edit_id].iloc[0]

            with st.form("edit_product_form"):

                edit_name = st.text_input(
                    "Название изделия",
                    value=str(edit_row["name"] or "")
                )

                edit_type = st.selectbox(
                    "Тип",
                    ["recurrent", "custom"],
                    index=(
                        0
                        if edit_row["type"] == "recurrent"
                        else 1
                    )
                )

                edit_client_options = ["— Без заказчика —"]
                edit_client_map = {}

                if not clients.empty:
                    edit_client_options += [
                        f"{row['id']} — {row['name']}"
                        for _, row in product_create_clients.iterrows()
                    ]
                    edit_client_map = {
                        f"{row['id']} — {row['name']}": row['name']
                        for _, row in product_create_clients.iterrows()
                    }

                current_client = str(edit_row["client_name"] or "")
                current_client_option = next(
                    (label for label, client_name in edit_client_map.items()
                     if client_name == current_client),
                    "— Без заказчика —"
                )

                edit_client_selection = st.selectbox(
                    "Заказчик",
                    edit_client_options,
                    index=edit_client_options.index(current_client_option),
                    key="edit_product_client"
                )
                edit_client = edit_client_map.get(edit_client_selection)

                edit_category_values = sorted({
                    str(value).strip()
                    for value in templates["category"].dropna().tolist()
                    if str(value).strip()
                }) if "category" in templates.columns else []

                edit_category_options = ["— Без категории —"] + edit_category_values
                current_category = str(edit_row["category"] or "").strip()

                if current_category and current_category not in edit_category_options:
                    edit_category_options.append(current_category)

                current_category_index = (
                    edit_category_options.index(current_category)
                    if current_category
                    else 0
                )

                edit_category_selection = st.selectbox(
                    "Категория",
                    edit_category_options,
                    index=current_category_index,
                    key="edit_product_category"
                )
                edit_category = (
                    None
                    if edit_category_selection == "— Без категории —"
                    else edit_category_selection
                )

                save_product = st.form_submit_button("Сохранить изменения")

                if save_product:

                    if not edit_name.strip():
                        st.warning("Product name is required.")
                    else:
                        run_query(
                            """
                            UPDATE reklet.product_templates
                            SET
                                name = %s,
                                type = %s,
                                client_name = %s,
                                category = %s
                            WHERE id = %s
                            """,
                            (
                                edit_name.strip(),
                                edit_type,
                                edit_client or None,
                                edit_category or None,
                                edit_id
                            )
                        )

                        st.success("Product updated.")
                        st.rerun()

            # ------------------------------------------------
            # DELETE PRODUCT — LAST
            # ------------------------------------------------

            st.markdown("---")
            with st.expander("Удалить изделие", expanded=False):
                st.warning(
                    "Deleting a product is permanent. A product already used "
                    "in an object or material specification cannot be deleted."
                )

                delete_product = st.selectbox(
                    "Product to delete",
                    list(product_map.keys()),
                    key="delete_product"
                )
                delete_product_id = product_map[delete_product]

                product_refs = run_query(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM reklet.object_items WHERE product_template_id = %s) AS object_count,
                        (SELECT COUNT(*) FROM reklet.product_template_materials WHERE product_template_id = %s) AS material_count
                    """,
                    (delete_product_id, delete_product_id),
                    fetch=True
                )
                product_object_count = int(product_refs.iloc[0]["object_count"])
                product_material_count = int(product_refs.iloc[0]["material_count"])

                if product_object_count or product_material_count:
                    st.error(
                        f"Cannot delete this product. Objects: {product_object_count}; "
                        f"Material specification rows: {product_material_count}."
                    )
                else:
                    confirm_product_delete = st.checkbox(
                        "I understand that this product will be permanently deleted.",
                        key="confirm_product_delete"
                    )
                    if st.button("Удалить изделие", key="delete_product_button"):
                        if not confirm_product_delete:
                            st.warning("Please confirm the deletion first.")
                        else:
                            run_query(
                                "DELETE FROM reklet.product_templates WHERE id = %s",
                                (delete_product_id,)
                            )
                            st.success("Product deleted.")
                            st.rerun()


    # ========================================================
    # PRODUCT MATERIAL SPECIFICATION
    # ========================================================

    else:

        templates = get_templates()
        clients = get_clients()
        client_filter_options = ["Все заказчики"] + [str(x) for x in clients["name"].tolist()] if not clients.empty else ["Все заказчики"]
        spec_client_filter = st.selectbox(
            "Отбор изделий по заказчику",
            client_filter_options,
            key="spec_client_filter"
        )
        if spec_client_filter != "Все заказчики":
            templates = templates[
                templates["client_name"].fillna("").astype(str).eq(spec_client_filter)
            ].copy()

        if templates.empty:
            st.info("Create a product first.")

        else:

            template_map = {
                f"{row['id']} — {row['name']} — "
                f"{row['client_name'] or 'General'}": int(row["id"])
                for _, row in templates.iterrows()
            }

            selected = st.selectbox(
                "Изделие",
                list(template_map.keys()),
                key="template_spec"
            )

            template_id = template_map[selected]

            # =================================================
            # 1. LIST
            # =================================================

            st.subheader("Перечень материалов")

            specification = run_query(
                """
                SELECT
                    ptm.id,
                    ptm.material_id,
                    m.name AS material_name,
                    u.name AS unit_name,
                    ptm.quantity_per_unit,
                    ptm.waste_coefficient
                FROM reklet.product_template_materials ptm
                JOIN reklet.materials m
                    ON m.id = ptm.material_id
                LEFT JOIN reklet.units u
                    ON u.id = m.unit_id
                WHERE ptm.product_template_id = %s
                ORDER BY m.name
                """,
                (template_id,),
                fetch=True
            )

            if specification.empty:
                st.info("No materials in this product specification.")
            else:
                display = specification[
                    [
                        "id",
                        "material_name",
                        "unit_name",
                        "quantity_per_unit",
                        "waste_coefficient"
                    ]
                ].copy()

                display.columns = [
                    "ID",
                    "Материал",
                    "Unit",
                    "Qty / Product",
                    "Waste Coef."
                ]

                st.dataframe(
                    display,
                    use_container_width=True,
                    hide_index=True
                )

            # =================================================
            # 2. ADD — MAIN TASK
            # =================================================

            st.markdown("---")
            st.subheader("Добавить материал")

            materials = get_materials()

            if materials.empty:
                st.warning(
                    "Create materials in Materials Warehouse first."
                )
            else:
                material_map = {
                    f"{row['name']} — {row['unit_name'] or ''}": int(row["id"])
                    for _, row in materials.iterrows()
                }

                with st.form(
                    f"add_material_to_template_{template_id}"
                ):

                    material_label = st.selectbox(
                        "Материал",
                        list(material_map.keys())
                    )

                    quantity_per_unit = st.number_input(
                        "Количество на изделие",
                        min_value=0.0001,
                        value=1.0,
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

                        material_id = material_map[material_label]

                        run_query(
                            """
                            INSERT INTO reklet.product_template_materials
                            (
                                product_template_id,
                                material_id,
                                quantity_per_unit,
                                waste_coefficient
                            )
                            VALUES (%s,%s,%s,%s)
                            """,
                            (
                                template_id,
                                material_id,
                                quantity_per_unit,
                                waste
                            )
                        )

                        st.success("Material added to specification.")
                        st.rerun()

            # =================================================
            # 3. EDIT — SECONDARY TASK
            # =================================================

            st.markdown("---")
            st.subheader("Исправить материал")

            if specification.empty:
                st.info("Add a material first.")
            else:
                spec_map = {
                    f"{row['id']} — {row['material_name']}": int(row["id"])
                    for _, row in specification.iterrows()
                }

                edit_spec_label = st.selectbox(
                    "Материал",
                    list(spec_map.keys()),
                    key="edit_spec_row"
                )

                edit_spec_id = spec_map[edit_spec_label]
                edit_spec = specification[
                    specification["id"] == edit_spec_id
                ].iloc[0]

                with st.form("edit_material_spec_form"):

                    edit_quantity = st.number_input(
                        "Количество на изделие",
                        min_value=0.0001,
                        value=float(edit_spec["quantity_per_unit"]),
                        format="%.4f"
                    )

                    edit_waste = st.number_input(
                        "Коэффициент отходов",
                        min_value=0.0,
                        value=float(edit_spec["waste_coefficient"]),
                        format="%.2f"
                    )

                    save_spec = st.form_submit_button(
                        "Сохранить изменения"
                    )

                    if save_spec:

                        run_query(
                            """
                            UPDATE reklet.product_template_materials
                            SET
                                quantity_per_unit = %s,
                                waste_coefficient = %s
                            WHERE id = %s
                            """,
                            (
                                edit_quantity,
                                edit_waste,
                                edit_spec_id
                            )
                        )

                        st.success("Material specification updated.")
                        st.rerun()

            # =================================================
            # 4. DELETE — LAST
            # =================================================

            st.markdown("---")
            with st.expander("Delete Material from Specification", expanded=False):
                st.warning(
                    "This removes the material only from this product specification. "
                    "It does not delete the material from the warehouse."
                )

                if specification.empty:
                    st.info("Nothing to delete.")
                else:
                    delete_map = {
                        f"{row['id']} — {row['material_name']}": int(row["id"])
                        for _, row in specification.iterrows()
                    }

                    delete_label = st.selectbox(
                        "Material to remove",
                        list(delete_map.keys()),
                        key="delete_spec_row"
                    )

                    confirm_spec_delete = st.checkbox(
                        "I understand that this specification row will be removed.",
                        key="confirm_spec_delete"
                    )
                    if st.button("Delete Material", key="delete_spec_button"):
                        if not confirm_spec_delete:
                            st.warning("Please confirm the deletion first.")
                        else:
                            run_query(
                                "DELETE FROM reklet.product_template_materials WHERE id = %s",
                                (delete_map[delete_label],)
                            )
                            st.success("Material deleted from specification.")
                            st.rerun()


# ============================================================
# MATERIALS WAREHOUSE
# ============================================================

elif menu == "Materials Warehouse":

    st.header("Материалы")

    sub = st.radio(
        "Materials Warehouse",
        [
            "Перечень материалов",
            "Приходная накладная",
            "Расходная накладная"
        ],
        horizontal=True,
        label_visibility="collapsed"
    )

    st.markdown("---")

    # ========================================================
    # MATERIALS LIST
    # ========================================================

    if sub == "Перечень материалов":

        materials = get_materials()
        categories = get_material_categories()
        category_map = {str(r["name"]): int(r["id"]) for _, r in categories.iterrows()}

        st.subheader("Перечень материалов")

        category_options = ["Все материалы", "Без категории"] + (
            categories["name"].astype(str).tolist() if not categories.empty else []
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
                filtered_materials["category_name"].fillna("").astype(str).eq(material_category_filter)
            ].copy()

        if filtered_materials.empty:
            st.info("Материалы по выбранному отбору отсутствуют.")
        else:
            display = filtered_materials[
                ["id", "name", "category_name", "unit_name", "cost_per_unit", "stock_quantity", "default_waste_coefficient"]
            ].copy()
            display.columns = [
                "№", "Материал", "Категория", "Единица", "Цена за единицу",
                "Остаток", "Коэффициент отходов"
            ]
            st.dataframe(display, use_container_width=True, hide_index=True)

            st.markdown("### Исправление материалов")
            edited = st.data_editor(
                display,
                key="materials_editor",
                use_container_width=True,
                hide_index=True,
                disabled=["№", "Единица"]
            )

            category_map = {str(r["name"]): int(r["id"]) for _, r in categories.iterrows()}
            if st.button("Сохранить изменения", key="save_materials"):
                for _, row in edited.iterrows():
                    cat_name = str(row["Категория"] or "").strip()
                    cat_id = category_map.get(cat_name) if cat_name else None
                    run_query(
                        """
                        UPDATE reklet.materials
                        SET name = %s,
                            category_id = %s,
                            cost_per_unit = %s,
                            stock_quantity = %s,
                            default_waste_coefficient = %s
                        WHERE id = %s
                        """,
                        (
                            str(row["Материал"]).strip(), cat_id,
                            safe_float(row["Цена за единицу"]),
                            safe_float(row["Остаток"]),
                            safe_float(row["Коэффициент отходов"], 1.20),
                            safe_int(row["№"])
                        )
                    )
                st.success("Изменения сохранены.")
                st.rerun()

        st.markdown("---")
        st.subheader("Добавить материал")

        units = run_query(
            "SELECT id, name FROM reklet.units ORDER BY name", fetch=True
        )
        unit_map = {str(r["name"]): int(r["id"]) for _, r in units.iterrows()} if not units.empty else {}
        create_category_options = ["— Без категории —"] + (
            categories["name"].astype(str).tolist() if not categories.empty else []
        )
        with st.form("create_material"):
            material_name = st.text_input("Название материала")
            unit_name = st.selectbox("Единица измерения", list(unit_map.keys())) if unit_map else None
            create_category = st.selectbox("Категория", create_category_options)
            cost = st.number_input("Цена за единицу", min_value=0.0, value=0.0, format="%.2f")
            stock = st.number_input("Начальный остаток", min_value=0.0, value=0.0, format="%.4f")
            waste = st.number_input("Коэффициент отходов", min_value=0.0, value=1.20, format="%.2f")
            submit = st.form_submit_button("Добавить материал")
            if submit:
                if not material_name.strip() or not unit_map:
                    st.warning("Укажите название материала и единицу измерения.")
                else:
                    cat_id = category_map.get(create_category) if create_category != "— Без категории —" else None
                    run_query(
                        """
                        INSERT INTO reklet.materials
                        (name, unit_id, category_id, cost_per_unit, stock_quantity, default_waste_coefficient)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        """,
                        (material_name.strip(), unit_map[unit_name], cat_id, cost, stock, waste)
                    )
                    st.success("Материал добавлен.")
                    st.rerun()

        st.markdown("---")
        st.subheader("Категории материалов")
        cat_display = categories.copy()
        if not cat_display.empty:
            cat_display.columns = ["№", "Категория"] + [c for c in cat_display.columns[2:]]
            st.dataframe(cat_display[["№", "Категория"]], use_container_width=True, hide_index=True)
            edit_cat_map = {f"{r['id']} — {r['name']}": int(r['id']) for _, r in categories.iterrows()}
            edit_cat_label = st.selectbox("Категория для исправления", list(edit_cat_map.keys()), key="edit_material_category")
            edit_cat_id = edit_cat_map[edit_cat_label]
            edit_cat_name = str(categories[categories["id"] == edit_cat_id].iloc[0]["name"])
            with st.form("edit_material_category_form"):
                new_cat_name = st.text_input("Название категории", value=edit_cat_name)
                if st.form_submit_button("Сохранить категорию"):
                    if new_cat_name.strip():
                        run_query("UPDATE reklet.material_categories SET name = %s WHERE id = %s", (new_cat_name.strip(), edit_cat_id))
                        st.success("Категория сохранена.")
                        st.rerun()

        with st.form("add_material_category"):
            new_category = st.text_input("Новая категория")
            if st.form_submit_button("Добавить категорию"):
                if new_category.strip():
                    try:
                        run_query("INSERT INTO reklet.material_categories (name) VALUES (%s)", (new_category.strip(),))
                        st.success("Категория добавлена.")
                        st.rerun()
                    except Exception:
                        st.error("Такая категория уже существует или не может быть добавлена.")

        # Suppliers linked to a material remain below the main list.
        st.markdown("---")
        st.subheader("Поставщики материала")
        if not filtered_materials.empty:
            material_map = {
                f"{row['name']} — {row['category_name'] or 'Без категории'}": int(row['id'])
                for _, row in filtered_materials.iterrows()
            }
            material_label = st.selectbox("Материал", list(material_map.keys()), key="material_supplier_material")
            material_id = material_map[material_label]
            supplier_data = run_query(
                """
                SELECT ms.id, s.name AS supplier, ms.purchase_price, ms.supplier_code,
                       ms.is_preferred, ms.conditions
                FROM reklet.material_suppliers ms
                JOIN reklet.suppliers s ON s.id = ms.supplier_id
                WHERE ms.material_id = %s
                ORDER BY s.name
                """, (material_id,), fetch=True
            )
            if not supplier_data.empty:
                supplier_display = supplier_data.rename(columns={
                    "id":"№", "supplier":"Поставщик", "purchase_price":"Цена закупки",
                    "supplier_code":"Код поставщика", "is_preferred":"Основной", "conditions":"Условия"
                })
                st.dataframe(supplier_display, use_container_width=True, hide_index=True)

        st.markdown("---")
        with st.expander("Удаление материала", expanded=False):
            st.warning("Используемый материал удалить нельзя.")
            if materials.empty:
                st.info("Нет материалов.")
            else:
                delete_map = {f"{r['id']} — {r['name']}": int(r['id']) for _, r in materials.iterrows()}
                delete_label = st.selectbox("Материал", list(delete_map.keys()), key="delete_material")
                delete_id = delete_map[delete_label]
                refs = run_query(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM reklet.material_transactions WHERE material_id = %s) AS tx_count,
                        (SELECT COUNT(*) FROM reklet.product_template_materials WHERE material_id = %s) AS spec_count,
                        (SELECT COUNT(*) FROM reklet.material_suppliers WHERE material_id = %s) AS supplier_count
                    """, (delete_id, delete_id, delete_id), fetch=True
                ).iloc[0]
                if any(int(refs[x]) for x in ["tx_count", "spec_count", "supplier_count"]):
                    st.error("Материал уже используется и не может быть удалён.")
                else:
                    confirm = st.checkbox("Подтверждаю удаление", key="confirm_material_delete")
                    if st.button("Удалить материал", key="delete_material_button"):
                        if confirm:
                            run_query("DELETE FROM reklet.materials WHERE id = %s", (delete_id,))
                            st.success("Материал удалён.")
                            st.rerun()
                        else:
                            st.warning("Сначала подтвердите удаление.")

    # ========================================================
    # GOODS RECEIPT — MULTI-LINE INVOICE
    # ========================================================

    elif sub == "Приходная накладная":

        st.subheader("Приходная накладная")
        st.caption("One supplier invoice can contain multiple materials.")

        materials = get_materials()
        suppliers = get_suppliers()

        if materials.empty:
            st.info("Create materials first in Materials List.")
        elif suppliers.empty:
            st.info("Create suppliers first.")
        else:
            material_options = [""] + materials["name"].tolist()
            supplier_map = {
                row["name"]: int(row["id"])
                for _, row in suppliers.iterrows()
            }
            material_map = {
                row["name"]: int(row["id"])
                for _, row in materials.iterrows()
            }

            with st.form("goods_receipt_invoice"):
                receipt_supplier = st.selectbox(
                    "Supplier",
                    list(supplier_map.keys())
                )

                receipt_date = st.date_input(
                    "Invoice Date"
                )

                receipt_number = st.text_input(
                    "Invoice Number"
                )

                receipt_rows = pd.DataFrame(
                    [
                        {"Material": "", "Quantity": 0.0, "Unit Price": 0.0}
                    ]
                )

                receipt_table = st.data_editor(
                    receipt_rows,
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key="goods_receipt_table",
                    column_config={
                        "Material": st.column_config.SelectboxColumn(
                            "Material",
                            options=material_options,
                            required=False
                        ),
                        "Quantity": st.column_config.NumberColumn(
                            "Quantity",
                            min_value=0.0,
                            step=0.001,
                            format="%.4f"
                        ),
                        "Unit Price": st.column_config.NumberColumn(
                            "Unit Price",
                            min_value=0.0,
                            step=0.01,
                            format="%.2f"
                        )
                    }
                )

                submit = st.form_submit_button("Внести на склад")

                if submit:
                    valid_rows = []
                    errors = []

                    for idx, row in receipt_table.iterrows():
                        material_name = str(row.get("Material", "")).strip()
                        quantity = safe_float(row.get("Quantity", 0))
                        unit_price = safe_float(row.get("Unit Price", 0))

                        if not material_name:
                            if quantity > 0 or unit_price > 0:
                                errors.append(f"Row {idx + 1}: material is not selected.")
                            continue

                        if quantity <= 0:
                            errors.append(f"Row {idx + 1}: quantity must be greater than 0.")
                            continue

                        valid_rows.append(
                            (
                                material_map[material_name],
                                quantity,
                                unit_price
                            )
                        )

                    if errors:
                        for error in errors:
                            st.error(error)
                    elif not valid_rows:
                        st.warning("Add at least one material to the invoice.")
                    else:
                        supplier_id = supplier_map[receipt_supplier]

                        for material_id, quantity, unit_price in valid_rows:
                            run_query(
                                """
                                INSERT INTO reklet.material_transactions
                                (
                                    material_id,
                                    supplier_id,
                                    operation_type,
                                    quantity,
                                    unit_price,
                                    transaction_type
                                )
                                VALUES (%s,%s,'purchase',%s,%s,'IN')
                                """,
                                (
                                    material_id,
                                    supplier_id,
                                    quantity,
                                    unit_price
                                )
                            )

                            run_query(
                                """
                                UPDATE reklet.materials
                                SET stock_quantity =
                                    COALESCE(stock_quantity, 0) + %s
                                WHERE id = %s
                                """,
                                (quantity, material_id)
                            )

                            run_query(
                                """
                                INSERT INTO reklet.material_suppliers
                                (
                                    material_id,
                                    supplier_id,
                                    purchase_price
                                )
                                VALUES (%s,%s,%s)
                                ON CONFLICT (material_id, supplier_id)
                                DO UPDATE SET
                                    purchase_price = EXCLUDED.purchase_price
                                """,
                                (
                                    material_id,
                                    supplier_id,
                                    unit_price
                                )
                            )

                        st.success(
                            f"Invoice posted. {len(valid_rows)} material line(s) added to stock."
                        )
                        st.rerun()

    # ========================================================
    # MATERIAL ISSUE — MULTI-LINE INVOICE
    # ========================================================

    elif sub == "Расходная накладная":

        st.subheader("Расходная накладная")
        st.caption("One production issue can contain multiple materials.")

        materials = get_materials()
        objects = get_objects()

        if materials.empty:
            st.info("Create materials first in Materials List.")
        elif objects.empty:
            st.info("Create objects first in Objects.")
        else:
            material_options = [""] + materials["name"].tolist()
            material_map = {
                row["name"]: int(row["id"])
                for _, row in materials.iterrows()
            }
            object_map = {
                f"{row['id']} — {row['object_name']}": int(row['id'])
                for _, row in objects.iterrows()
            }

            with st.form("material_issue_invoice"):
                issue_object = st.selectbox(
                    "Object / Production Order",
                    list(object_map.keys())
                )

                issue_date = st.date_input(
                    "Issue Date"
                )

                issue_number = st.text_input(
                    "Issue Number"
                )

                issue_rows = pd.DataFrame(
                    [
                        {"Material": "", "Quantity": 0.0}
                    ]
                )

                issue_table = st.data_editor(
                    issue_rows,
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key="material_issue_table",
                    column_config={
                        "Material": st.column_config.SelectboxColumn(
                            "Material",
                            options=material_options,
                            required=False
                        ),
                        "Quantity": st.column_config.NumberColumn(
                            "Quantity",
                            min_value=0.0,
                            step=0.001,
                            format="%.4f"
                        )
                    }
                )

                submit = st.form_submit_button("Списать на производство")

                if submit:
                    valid_rows = []
                    errors = []

                    for idx, row in issue_table.iterrows():
                        material_name = str(row.get("Material", "")).strip()
                        quantity = safe_float(row.get("Quantity", 0))

                        if not material_name:
                            if quantity > 0:
                                errors.append(f"Row {idx + 1}: material is not selected.")
                            continue

                        if quantity <= 0:
                            errors.append(f"Row {idx + 1}: quantity must be greater than 0.")
                            continue

                        valid_rows.append(
                            (
                                material_map[material_name],
                                quantity
                            )
                        )

                    if errors:
                        for error in errors:
                            st.error(error)
                    elif not valid_rows:
                        st.warning("Add at least one material to the issue invoice.")
                    else:
                        object_id = object_map[issue_object]

                        # Validate the complete invoice before changing stock.
                        stock_errors = []
                        for material_id, quantity in valid_rows:
                            current_stock = run_query(
                                """
                                SELECT stock_quantity
                                FROM reklet.materials
                                WHERE id = %s
                                """,
                                (material_id,),
                                fetch=True
                            )

                            stock = safe_float(
                                current_stock.iloc[0]["stock_quantity"]
                            )

                            already_requested = sum(
                                q for mid, q in valid_rows
                                if mid == material_id
                            )

                            if already_requested > stock:
                                material_name = next(
                                    name for name, mid in material_map.items()
                                    if mid == material_id
                                )
                                stock_errors.append(
                                    f"{material_name}: requested {already_requested:.4f}, "
                                    f"available {stock:.4f}."
                                )

                        if stock_errors:
                            for error in stock_errors:
                                st.error(error)
                        else:
                            for material_id, quantity in valid_rows:
                                run_query(
                                    """
                                    INSERT INTO reklet.material_transactions
                                    (
                                        material_id,
                                        object_id,
                                        operation_type,
                                        quantity,
                                        transaction_type
                                    )
                                    VALUES (%s,%s,'production_transfer',%s,'OUT')
                                    """,
                                    (
                                        material_id,
                                        object_id,
                                        quantity
                                    )
                                )

                                run_query(
                                    """
                                    UPDATE reklet.materials
                                    SET stock_quantity = stock_quantity - %s
                                    WHERE id = %s
                                    """,
                                    (quantity, material_id)
                                )

                            st.success(
                                f"Issue posted. {len(valid_rows)} material line(s) written off to production."
                            )
                            st.rerun()

    # ========================================================
    # MOVEMENT HISTORY
    # ========================================================

    st.markdown("---")
    st.subheader("Material Movement")

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
        FROM reklet.material_transactions mt
        LEFT JOIN reklet.materials m
            ON m.id = mt.material_id
        LEFT JOIN reklet.suppliers s
            ON s.id = mt.supplier_id
        LEFT JOIN reklet.objects o
            ON o.id = mt.object_id
        ORDER BY mt.created_at DESC
        LIMIT 500
        """,
        fetch=True
    )

    if not movements.empty:
        st.dataframe(
            movements,
            use_container_width=True,
            hide_index=True
        )


elif menu == "Suppliers":

    st.header("Поставщики")
    suppliers = get_suppliers()

    if suppliers.empty:
        st.info("Поставщиков пока нет.")
    else:
        display = suppliers[["id", "name", "type", "contact_person", "phone", "email", "category"]].copy()
        display.columns = ["№", "Поставщик", "Тип", "Контактное лицо", "Телефон", "Email", "Категория"]
        st.subheader("Перечень поставщиков")
        st.dataframe(display, use_container_width=True, hide_index=True)

        supplier_map = {f"{r['id']} — {r['name']}": int(r['id']) for _, r in suppliers.iterrows()}
        selected_supplier_label = st.selectbox("Открыть поставщика", list(supplier_map.keys()), key="supplier_details_select")
        selected_supplier_id = supplier_map[selected_supplier_label]
        supplier_row = suppliers[suppliers["id"] == selected_supplier_id].iloc[0]

        st.markdown("---")
        st.subheader("Карточка поставщика")
        with st.form("supplier_details_form"):
            d1, d2 = st.columns(2)
            with d1:
                detail_name = st.text_input("Поставщик", value=str(supplier_row["name"] or ""))
                detail_type = st.selectbox("Тип", ["material_supplier", "subcontractor", "both"], index=["material_supplier", "subcontractor", "both"].index(str(supplier_row["type"] or "material_supplier")) if str(supplier_row["type"] or "material_supplier") in ["material_supplier", "subcontractor", "both"] else 0)
                detail_contact = st.text_input("Контактное лицо", value=str(supplier_row["contact_person"] or ""))
                detail_phone = st.text_input("Телефон", value=str(supplier_row["phone"] or ""))
                detail_email = st.text_input("Email", value=str(supplier_row["email"] or ""))
                detail_category = st.text_input("Категория", value=str(supplier_row["category"] or ""))
            with d2:
                detail_notes = st.text_area("Notes / Дополнительные сведения", value=str(supplier_row.get("notes", "") or ""), height=300)
                st.caption("Здесь можно хранить менеджера, историю переговоров, условия, договорённости и другие рабочие заметки.")
            if st.form_submit_button("Сохранить изменения"):
                run_query(
                    """
                    UPDATE reklet.suppliers
                    SET name=%s, type=%s, contact_person=%s, phone=%s, email=%s,
                        category=%s, notes=%s
                    WHERE id=%s
                    """,
                    (detail_name.strip(), detail_type, detail_contact, detail_phone, detail_email, detail_category, detail_notes, selected_supplier_id)
                )
                st.success("Карточка поставщика сохранена.")
                st.rerun()

    st.markdown("---")
    with st.expander("Добавить поставщика", expanded=False):
        with st.form("create_supplier"):
            name = st.text_input("Поставщик")
            supplier_type = st.selectbox("Тип", ["material_supplier", "subcontractor", "both"])
            contact_person = st.text_input("Контактное лицо")
            phone = st.text_input("Телефон")
            email = st.text_input("Email")
            category = st.text_input("Категория")
            conditions = st.text_area("Условия")
            notes = st.text_area("Дополнительные сведения")
            contact_info = st.text_area("Контактная информация")
            if st.form_submit_button("Добавить поставщика"):
                if not name.strip():
                    st.warning("Укажите название поставщика.")
                else:
                    run_query(
                        """
                        INSERT INTO reklet.suppliers
                        (name, type, contact_info, contact_person, phone, email, category, conditions, notes)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (name.strip(), supplier_type, contact_info, contact_person, phone, email, category, conditions, notes)
                    )
                    st.success("Поставщик добавлен.")
                    st.rerun()

    st.markdown("---")
    with st.expander("Удаление поставщика", expanded=False):
        st.warning("Поставщика, который уже использован в материалах или операциях, удалить нельзя.")
        if not suppliers.empty:
            delete_map = {f"{r['id']} — {r['name']}": int(r['id']) for _, r in suppliers.iterrows()}
            delete_label = st.selectbox("Поставщик", list(delete_map.keys()), key="delete_supplier")
            delete_id = delete_map[delete_label]
            refs = run_query(
                """
                SELECT
                    (SELECT COUNT(*) FROM reklet.material_suppliers WHERE supplier_id=%s) AS material_links,
                    (SELECT COUNT(*) FROM reklet.material_transactions WHERE supplier_id=%s) AS transactions
                """, (delete_id, delete_id), fetch=True
            ).iloc[0]
            if int(refs["material_links"]) or int(refs["transactions"]):
                st.error("Поставщик уже используется и не может быть удалён.")
            else:
                confirm = st.checkbox("Подтверждаю удаление", key="confirm_supplier_delete")
                if st.button("Удалить поставщика", key="delete_supplier_button"):
                    if confirm:
                        run_query("DELETE FROM reklet.suppliers WHERE id=%s", (delete_id,))
                        st.success("Поставщик удалён.")
                        st.rerun()
                    else:
                        st.warning("Сначала подтвердите удаление.")


# ============================================================
# PRODUCTION
# ============================================================

elif menu == "Production":

    st.header("Производство")
    objects = get_objects()

    if objects.empty:
        st.info("Объектов пока нет.")
    else:
        object_options = ["Все объекты"] + [
            f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or 'Без заказчика'}"
            for _, r in objects.iterrows()
        ]
        object_filter = st.selectbox("Отбор по объекту", object_options, key="production_object_filter")

        query = """
        SELECT oi.id, o.object_name, c.name AS client_name, oi.item_name,
               oi.quantity_needed, oi.qty_new, oi.qty_production, oi.qty_ready,
               oi.qty_shipped, oi.qty_arrived, oi.qty_installing, oi.qty_installed
        FROM reklet.object_items oi
        JOIN reklet.objects o ON o.id = oi.object_id
        LEFT JOIN reklet.clients c ON c.id = o.client_id
        WHERE (COALESCE(oi.qty_new,0) > 0 OR COALESCE(oi.qty_production,0) > 0)
        """
        params=[]
        if object_filter != "Все объекты":
            oid=int(object_filter.split(" — ")[0]); query += " AND oi.object_id=%s"; params.append(oid)
        query += " ORDER BY oi.id DESC"
        df=run_query(query, tuple(params), fetch=True)

        if df.empty:
            st.success("Все изделия по выбранному отбору уже переданы дальше.")
        else:
            display=df[["id","object_name","client_name","item_name","quantity_needed","qty_new","qty_production","qty_ready"]].copy()
            display.columns=["№","Объект","Заказчик","Изделие","Заказано","Осталось запустить","В производстве","Готово"]
            st.subheader("Перечень изделий в производстве")
            st.dataframe(display, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("Действие по производству")
            item_map={f"{int(r['id'])} — {r['object_name']} — {r['item_name']} — {r['client_name'] or 'Без заказчика'}":int(r['id']) for _,r in df.iterrows()}
            selected_item=st.selectbox("Изделие", list(item_map.keys()), key="production_item")
            item_id=item_map[selected_item]
            item_row=df[df["id"]==item_id].iloc[0]
            action=st.radio("Действие", ["Запустить в производство","Передать на склад готовой продукции"], horizontal=True, key="production_action")
            if action=="Запустить в производство":
                max_qty=safe_int(item_row["qty_new"])
                st.info(f"Можно запустить сейчас: {max_qty} шт.")
            else:
                max_qty=safe_int(item_row["qty_production"])
                st.info(f"В производстве сейчас: {max_qty} шт.")
            action_qty=st.number_input("Количество", min_value=1, max_value=max(max_qty,1), value=1, step=1, key="production_action_qty")

            if st.button("Исполнить", key="apply_production_action"):
                if max_qty <= 0:
                    st.warning("Нет доступного количества для выбранного действия.")
                elif action=="Запустить в производство":
                    run_query(
                        """
                        UPDATE reklet.object_items
                        SET qty_new=qty_new-%s,
                            qty_production=qty_production+%s,
                            production_status='in_progress',
                            production_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND(((quantity_needed-qty_new+%s)::numeric/quantity_needed)*100)) ELSE 0 END
                        WHERE id=%s
                        """, (action_qty, action_qty, action_qty, item_id)
                    )
                    st.success("Количество запущено в производство.")
                    st.rerun()
                else:
                    run_query(
                        """
                        UPDATE reklet.object_items
                        SET qty_production=qty_production-%s,
                            qty_ready=qty_ready+%s,
                            production_status=CASE WHEN qty_production-%s<=0 AND qty_new<=0 THEN 'completed' ELSE 'in_progress' END,
                            production_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND(((quantity_needed-qty_new-(qty_production-%s))::numeric/quantity_needed)*100)) ELSE 0 END
                        WHERE id=%s
                        """, (action_qty, action_qty, action_qty, action_qty, item_id)
                    )
                    run_query(
                        """
                        INSERT INTO reklet.finished_goods(object_item_id,object_id,quantity,status)
                        SELECT id,object_id,%s,'ready' FROM reklet.object_items WHERE id=%s
                        """, (action_qty,item_id)
                    )
                    run_query(
                        """
                        INSERT INTO reklet.finished_goods_transactions(object_item_id,object_id,operation_type,quantity)
                        SELECT id,object_id,'ready',%s FROM reklet.object_items WHERE id=%s
                        """, (action_qty,item_id)
                    )
                    st.success("Изделия переданы на склад готовой продукции.")
                    st.rerun()

    st.markdown("---")
    st.subheader("Движения по производству")
    prod_objects=st.selectbox("Архив: объект", ["Все объекты"]+[f"{int(r['id'])} — {r['object_name']}" for _,r in objects.iterrows()] if not objects.empty else ["Все объекты"], key="production_archive_object")
    prod_clients=run_query("SELECT id,name FROM reklet.clients ORDER BY name",fetch=True)
    prod_client=st.selectbox("Архив: заказчик", ["Все заказчики"]+prod_clients["name"].astype(str).tolist() if not prod_clients.empty else ["Все заказчики"], key="production_archive_client")
    movement_query="""
    SELECT fgt.created_at AS date, o.object_name, c.name AS client_name, oi.item_name, fgt.quantity
    FROM reklet.finished_goods_transactions fgt
    JOIN reklet.object_items oi ON oi.id=fgt.object_item_id
    JOIN reklet.objects o ON o.id=fgt.object_id
    LEFT JOIN reklet.clients c ON c.id=o.client_id
    WHERE fgt.operation_type='ready'
    """
    mparams=[]
    if prod_objects!="Все объекты": movement_query+=" AND fgt.object_id=%s"; mparams.append(int(prod_objects.split(" — ")[0]))
    if prod_client!="Все заказчики": movement_query+=" AND c.name=%s"; mparams.append(prod_client)
    movement_query+=" ORDER BY fgt.created_at DESC LIMIT 500"
    movements=run_query(movement_query,tuple(mparams),fetch=True)
    if movements.empty: st.info("Движений пока нет.")
    else:
        movements.columns=["Дата","Объект","Заказчик","Изделие","Количество"]
        st.dataframe(movements,use_container_width=True,hide_index=True)


# ============================================================
# FINISHED GOODS
# ============================================================

elif menu == "Finished Goods":

    st.header("Склад готовой продукции")
    objects=get_objects()
    if objects.empty:
        st.info("Объектов пока нет.")
    else:
        object_options=["Все объекты"]+[f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or 'Без заказчика'}" for _,r in objects.iterrows()]
        fg_object_filter=st.selectbox("Отбор по объекту",object_options,key="fg_object_filter")
        q="""
        SELECT oi.id AS object_item_id, oi.object_id, o.object_name, c.name AS client_name,
               oi.item_name, oi.quantity_needed,
               COALESCE(SUM(CASE WHEN fg.status='ready' THEN fg.quantity ELSE 0 END),0) AS ready_stock,
               COALESCE(SUM(CASE WHEN fg.status='shipped' THEN fg.quantity ELSE 0 END),0) AS shipped_stock,
               COALESCE(SUM(CASE WHEN fg.status='arrived' THEN fg.quantity ELSE 0 END),0) AS arrived_stock
        FROM reklet.object_items oi
        JOIN reklet.objects o ON o.id=oi.object_id
        LEFT JOIN reklet.clients c ON c.id=o.client_id
        LEFT JOIN reklet.finished_goods fg ON fg.object_item_id=oi.id
        """
        params=[]
        if fg_object_filter!="Все объекты": q+=" WHERE oi.object_id=%s"; params.append(int(fg_object_filter.split(" — ")[0]))
        q+=" GROUP BY oi.id,oi.object_id,o.object_name,c.name,oi.item_name,oi.quantity_needed ORDER BY oi.id DESC"
        summary=run_query(q,tuple(params),fetch=True)
        if summary.empty:
            st.info("Нет данных по складу готовой продукции.")
        else:
            active=summary[(summary["ready_stock"]>0)|(summary["shipped_stock"]>0)].copy()
            if active.empty: st.success("Весь готовый товар уже доставлен.")
            else:
                display=active[["object_name","client_name","item_name","quantity_needed","ready_stock","shipped_stock","arrived_stock"]].copy()
                display.columns=["Объект","Заказчик","Изделие","Заказано","Ждёт отправки","Отправлено","Доставлено"]
                st.subheader("Готовая продукция по объектам")
                st.dataframe(display,use_container_width=True,hide_index=True)

                st.markdown("---")
                st.subheader("Отправка")
                ship_df=active[active["ready_stock"]>0].copy()
                if not ship_df.empty:
                    smap={f"{int(r['object_item_id'])} — {r['object_name']} — {r['item_name']} — готово: {int(r['ready_stock'])}":int(r['object_item_id']) for _,r in ship_df.iterrows()}
                    sel=st.selectbox("Объект / изделие",list(smap.keys()),key="fg_ship_select")
                    iid=smap[sel]; row=ship_df[ship_df["object_item_id"]==iid].iloc[0]
                    qty=st.number_input("Количество",min_value=1,max_value=int(row["ready_stock"]),value=1,key="fg_ship_qty")
                    if st.button("Передать в доставку",key="ship_finished_goods"):
                        batches=run_query("""SELECT id,quantity FROM reklet.finished_goods WHERE object_item_id=%s AND status='ready' AND quantity>0 ORDER BY created_at,id FOR UPDATE""",(iid,),fetch=True)
                        if int(batches["quantity"].sum())<qty:
                            st.error("Недостаточно готовой продукции именно для этого объекта.")
                        else:
                            rem=int(qty)
                            for _,b in batches.iterrows():
                                if rem<=0: break
                                take=min(rem,int(b["quantity"])); newq=int(b["quantity"])-take
                                run_query("UPDATE reklet.finished_goods SET quantity=%s,status=%s WHERE id=%s",(newq,"shipped" if newq==0 else "ready",int(b["id"])))
                                run_query("""INSERT INTO reklet.finished_goods_transactions(finished_goods_id,object_item_id,object_id,operation_type,quantity) SELECT id,object_item_id,object_id,'ship',%s FROM reklet.finished_goods WHERE id=%s""",(take,int(b["id"])))
                                rem-=take
                            run_query("UPDATE reklet.object_items SET qty_shipped=qty_shipped+%s WHERE id=%s",(qty,iid))
                            st.success("Продукция передана в доставку."); st.rerun()

                st.markdown("---")
                st.subheader("Доставка на объект")
                ship_q="""
                SELECT oi.id AS object_item_id,o.object_name,c.name AS client_name,oi.item_name,
                       COALESCE(SUM(CASE WHEN fg.status='shipped' THEN fg.quantity ELSE 0 END),0) AS shipped_stock
                FROM reklet.object_items oi JOIN reklet.objects o ON o.id=oi.object_id
                LEFT JOIN reklet.clients c ON c.id=o.client_id LEFT JOIN reklet.finished_goods fg ON fg.object_item_id=oi.id
                GROUP BY oi.id,o.object_name,c.name,oi.item_name
                HAVING COALESCE(SUM(CASE WHEN fg.status='shipped' THEN fg.quantity ELSE 0 END),0)>0
                ORDER BY oi.id DESC
                """
                shipped=run_query(ship_q,fetch=True)
                if shipped.empty: st.info("Нет продукции, ожидающей доставки.")
                else:
                    amap={f"{int(r['object_item_id'])} — {r['object_name']} — {r['item_name']} — в доставке: {int(r['shipped_stock'])}":int(r['object_item_id']) for _,r in shipped.iterrows()}
                    asel=st.selectbox("Объект / изделие",list(amap.keys()),key="fg_arrival_select")
                    aiid=amap[asel]; ar=shipped[shipped["object_item_id"]==aiid].iloc[0]
                    aq=st.number_input("Количество",min_value=1,max_value=int(ar["shipped_stock"]),value=1,key="fg_arrival_qty")
                    if st.button("Подтвердить доставку",key="arrive_finished_goods"):
                        batches=run_query("SELECT id,quantity FROM reklet.finished_goods WHERE object_item_id=%s AND status='shipped' AND quantity>0 ORDER BY created_at,id FOR UPDATE",(aiid,),fetch=True)
                        rem=int(aq)
                        for _,b in batches.iterrows():
                            if rem<=0: break
                            take=min(rem,int(b["quantity"])); newq=int(b["quantity"])-take
                            run_query("UPDATE reklet.finished_goods SET quantity=%s,status=%s WHERE id=%s",(newq,"arrived" if newq==0 else "shipped",int(b["id"])))
                            run_query("""INSERT INTO reklet.finished_goods_transactions(finished_goods_id,object_item_id,object_id,operation_type,quantity) SELECT id,object_item_id,object_id,'arrive',%s FROM reklet.finished_goods WHERE id=%s""",(take,int(b["id"])))
                            rem-=take
                        run_query("UPDATE reklet.object_items SET qty_arrived=qty_arrived+%s WHERE id=%s",(aq,aiid))
                        st.success("Доставка подтверждена."); st.rerun()

        st.markdown("---")
        st.subheader("Движения по складу готовой продукции")
        fg_client_df=run_query("SELECT id,name FROM reklet.clients ORDER BY name",fetch=True)
        fc1,fc2=st.columns(2)
        with fc1: archive_obj=st.selectbox("Объект",["Все объекты"]+[f"{int(r['id'])} — {r['object_name']}" for _,r in objects.iterrows()],key="fg_archive_obj")
        with fc2: archive_client=st.selectbox("Заказчик",["Все заказчики"]+fg_client_df["name"].astype(str).tolist() if not fg_client_df.empty else ["Все заказчики"],key="fg_archive_client")
        tq="""SELECT fgt.created_at,o.object_name,c.name AS client_name,oi.item_name,fgt.operation_type,fgt.quantity
              FROM reklet.finished_goods_transactions fgt JOIN reklet.object_items oi ON oi.id=fgt.object_item_id
              JOIN reklet.objects o ON o.id=fgt.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id WHERE fgt.operation_type IN ('ship','arrive')"""
        tp=[]
        if archive_obj!="Все объекты": tq+=" AND fgt.object_id=%s";tp.append(int(archive_obj.split(" — ")[0]))
        if archive_client!="Все заказчики": tq+=" AND c.name=%s";tp.append(archive_client)
        tq+=" ORDER BY fgt.created_at DESC LIMIT 500"
        hist=run_query(tq,tuple(tp),fetch=True)
        if hist.empty: st.info("Движений нет.")
        else:
            hist["operation_type"]=hist["operation_type"].map({"ship":"Отправлено","arrive":"Доставлено"})
            hist.columns=["Дата","Объект","Заказчик","Изделие","Операция","Количество"]
            st.dataframe(hist,use_container_width=True,hide_index=True)


# ============================================================
# TRANSPORT & LOGISTICS
# ============================================================

elif menu == "Transport & Logistics":

    st.header("Доставка")

    df = run_query(
        """
        SELECT

            o.id,

            o.object_name,

            c.name AS client_name,

            o.address,

            COALESCE(
                SUM(oi.qty_ready),
                0
            ) AS ready,

            COALESCE(
                SUM(oi.qty_shipped),
                0
            ) AS shipped,

            COALESCE(
                SUM(oi.qty_arrived),
                0
            ) AS arrived

        FROM reklet.objects o

        LEFT JOIN reklet.clients c
            ON c.id = o.client_id

        LEFT JOIN reklet.object_items oi
            ON oi.object_id = o.id

        GROUP BY

            o.id,
            o.object_name,
            c.name,
            o.address

        ORDER BY
            o.object_name
        """,
        fetch=True
    )

    if df.empty:

        st.info(
            "Нет данных по доставке."
        )

    else:

        display = df[["id","object_name","client_name","address","ready","shipped","arrived"]].copy()
        display.columns = ["№","Объект","Заказчик","Адрес","Готово","Отправлено","Доставлено"]
        st.dataframe(display,use_container_width=True,hide_index=True)

        st.markdown("---")

        st.subheader(
            "Доставка по объекту"
        )

        object_map = {

            f"{row['id']} — "
            f"{row['object_name']}":
                int(row["id"])

            for _, row in df.iterrows()
        }

        selected = st.selectbox(
            "Объект",
            list(object_map.keys())
        )

        object_id = object_map[
            selected
        ]

        detail = run_query(
            """
            SELECT

                oi.item_name,

                oi.quantity_needed,

                oi.qty_ready,

                oi.qty_shipped,

                oi.qty_arrived,

                (
                    oi.quantity_needed
                    -
                    oi.qty_arrived
                ) AS remaining

            FROM
                reklet.object_items oi

            WHERE
                oi.object_id = %s

            ORDER BY
                oi.item_name
            """,
            (object_id,),
            fetch=True
        )

        detail.columns = ["Изделие","Заказано","Готово","Отправлено","Доставлено","Осталось"]
        st.dataframe(detail,use_container_width=True,hide_index=True)


# ============================================================
# INSTALLATION
# ============================================================

elif menu == "Installation":

    st.header("Монтаж")
    objects=get_objects()
    if objects.empty:
        st.info("Объектов пока нет.")
    else:
        object_options=["Все объекты"]+[f"{int(r['id'])} — {r['object_name']} — {r['client_name'] or 'Без заказчика'}" for _,r in objects.iterrows()]
        inst_filter=st.selectbox("Отбор по объекту",object_options,key="installation_object_filter")
        q="""
        SELECT oi.id,o.object_name,c.name AS client_name,oi.item_name,oi.quantity_needed,
               oi.qty_arrived,oi.qty_installing,oi.qty_installed,
               GREATEST(oi.quantity_needed-oi.qty_installed,0) AS remaining
        FROM reklet.object_items oi JOIN reklet.objects o ON o.id=oi.object_id
        LEFT JOIN reklet.clients c ON c.id=o.client_id
        WHERE COALESCE(oi.qty_installed,0) < COALESCE(oi.quantity_needed,0)
          AND (COALESCE(oi.qty_arrived,0)>0 OR COALESCE(oi.qty_installing,0)>0)
        """
        ip=[]
        if inst_filter!="Все объекты": q+=" AND oi.object_id=%s";ip.append(int(inst_filter.split(" — ")[0]))
        q+=" ORDER BY oi.id DESC"
        df=run_query(q,tuple(ip),fetch=True)
        if df.empty:
            st.success("Все доступные для монтажа изделия по выбранному отбору выполнены.")
        else:
            display=df[["id","object_name","client_name","item_name","quantity_needed","qty_arrived","qty_installing","qty_installed"]].copy()
            display.columns=["№","Объект","Заказчик","Изделие","Всего по заказу","Поступило","В монтаже","Установлено"]
            st.subheader("Перечень изделий для монтажа")
            st.dataframe(display,use_container_width=True,hide_index=True)

            st.markdown("---")
            st.subheader("Исполнение")
            item_map={f"{int(r['id'])} — {r['object_name']} — {r['item_name']}":int(r['id']) for _,r in df.iterrows()}
            selected=st.selectbox("Изделие",list(item_map.keys()),key="installation_item")
            item_id=item_map[selected]; item_row=df[df["id"]==item_id].iloc[0]
            st.write(f"Всего по заказу: **{safe_int(item_row['quantity_needed'])}**")
            st.write(f"Поступило: **{safe_int(item_row['qty_arrived'])}** | В монтаже: **{safe_int(item_row['qty_installing'])}** | Установлено: **{safe_int(item_row['qty_installed'])}**")
            action=st.radio("Действие",["Начать монтаж","Завершить монтаж"],horizontal=True,key="installation_action")
            available=safe_int(item_row["qty_arrived"]) if action=="Начать монтаж" else safe_int(item_row["qty_installing"])
            qty=st.number_input("Количество",min_value=1,max_value=max(available,1),value=1,key="installation_qty")
            if st.button("Исполнить",key="apply_installation_action"):
                if available<=0: st.warning("Нет доступного количества для выбранного действия.")
                elif action=="Начать монтаж":
                    run_query("""UPDATE reklet.object_items SET qty_arrived=qty_arrived-%s,qty_installing=qty_installing+%s,installation_status='in_progress' WHERE id=%s""",(qty,qty,item_id))
                    st.success("Изделия переданы в монтаж.");st.rerun()
                else:
                    run_query("""UPDATE reklet.object_items SET qty_installing=qty_installing-%s,qty_installed=qty_installed+%s,installation_status=CASE WHEN qty_installing-%s<=0 AND qty_arrived<=0 THEN 'completed' ELSE 'in_progress' END,installation_progress_pct=CASE WHEN quantity_needed>0 THEN LEAST(100,ROUND(((qty_installed+%s)::numeric/quantity_needed)*100)) ELSE 0 END WHERE id=%s""",(qty,qty,qty,qty,item_id))
                    run_query("""INSERT INTO reklet.installation_transactions(object_item_id,object_id,quantity) SELECT id,object_id,%s FROM reklet.object_items WHERE id=%s""",(qty,item_id))
                    st.success("Монтаж обновлён.");st.rerun()

    st.markdown("---")
    st.subheader("Архив — движения по монтажу")
    clients=run_query("SELECT id,name FROM reklet.clients ORDER BY name",fetch=True)
    ac1,ac2=st.columns(2)
    with ac1: ao=st.selectbox("Объект",["Все объекты"]+[f"{int(r['id'])} — {r['object_name']}" for _,r in objects.iterrows()],key="inst_archive_obj")
    with ac2: ac=st.selectbox("Заказчик",["Все заказчики"]+clients["name"].astype(str).tolist() if not clients.empty else ["Все заказчики"],key="inst_archive_client")
    hq="""SELECT it.created_at,o.object_name,c.name AS client_name,oi.item_name,it.quantity FROM reklet.installation_transactions it JOIN reklet.object_items oi ON oi.id=it.object_item_id JOIN reklet.objects o ON o.id=it.object_id LEFT JOIN reklet.clients c ON c.id=o.client_id WHERE 1=1"""
    hp=[]
    if ao!="Все объекты": hq+=" AND it.object_id=%s";hp.append(int(ao.split(" — ")[0]))
    if ac!="Все заказчики": hq+=" AND c.name=%s";hp.append(ac)
    hq+=" ORDER BY it.created_at DESC LIMIT 500"
    hist=run_query(hq,tuple(hp),fetch=True)
    if hist.empty: st.info("Архивных движений нет.")
    else:
        hist.columns=["Дата","Объект","Заказчик","Изделие","Количество"]
        st.dataframe(hist,use_container_width=True,hide_index=True)


# ============================================================
# PAYROLL
# ============================================================

elif menu == "Payroll":

    st.header("Зарплата")
    section=st.radio("Раздел",["Зарплата производства","Зарплата транспортировки","Зарплата монтажа","Сводка по зарплате"],horizontal=True)

    base_q="""
    SELECT oi.id AS object_item_id,o.id AS object_id,o.object_name,c.name AS client_name,oi.item_name,
           oi.quantity_needed,COALESCE(o.transport_distance_km,0) AS distance_km,
           COALESCE(SUM(ptm.quantity_per_unit * m.cost_per_unit * COALESCE(ptm.waste_coefficient,1)),0) AS material_unit_cost
    FROM reklet.object_items oi
    JOIN reklet.objects o ON o.id=oi.object_id
    LEFT JOIN reklet.clients c ON c.id=o.client_id
    LEFT JOIN reklet.product_template_materials ptm ON ptm.product_template_id=oi.product_template_id
    LEFT JOIN reklet.materials m ON m.id=ptm.material_id
    GROUP BY oi.id,o.id,o.object_name,c.name,oi.item_name,oi.quantity_needed,o.transport_distance_km
    ORDER BY oi.id DESC
    """
    costs=run_query(base_q,fetch=True)
    if costs.empty:
        st.info("Нет данных для расчёта зарплаты.")
    else:
        costs["material_total_cost"]=costs["material_unit_cost"]*costs["quantity_needed"]
        costs["production_salary"]=costs["material_total_cost"]*1.50
        costs["installation_salary"]=costs["material_total_cost"]*1.40
        costs["transport_salary"]=costs["material_total_cost"]*0.10+costs["distance_km"]*2

        if section=="Зарплата производства":
            d=costs[["object_name","client_name","item_name","quantity_needed","material_total_cost","production_salary"]].copy()
            d.columns=["Объект","Заказчик","Изделие","Количество","Себестоимость материалов","Зарплата производства"]
            st.dataframe(d,use_container_width=True,hide_index=True)
        elif section=="Зарплата монтажа":
            d=costs[["object_name","client_name","item_name","quantity_needed","material_total_cost","installation_salary"]].copy()
            d.columns=["Объект","Заказчик","Изделие","Количество","Себестоимость материалов","Зарплата монтажа"]
            st.dataframe(d,use_container_width=True,hide_index=True)
        elif section=="Зарплата транспортировки":
            d=costs[["object_name","client_name","item_name","quantity_needed","material_total_cost","distance_km","transport_salary"]].copy()
            d.columns=["Объект","Заказчик","Изделие","Количество","Себестоимость материалов","Расстояние, км","Зарплата доставки"]
            st.dataframe(d,use_container_width=True,hide_index=True)
        else:
            d=costs[["object_name","client_name","item_name","quantity_needed","production_salary","installation_salary","transport_salary"]].copy()
            d["Итого"] = d["production_salary"]+d["installation_salary"]+d["transport_salary"]
            d.columns=["Объект","Заказчик","Изделие","Количество","Производство","Монтаж","Доставка","Итого"]
            st.subheader("По элементам")
            st.dataframe(d,use_container_width=True,hide_index=True)
            summary=d.groupby(["Объект","Заказчик"],dropna=False)[["Производство","Монтаж","Доставка","Итого"]].sum().reset_index()
            st.subheader("Сводка по объектам")
            st.dataframe(summary,use_container_width=True,hide_index=True)
            client_summary=d.groupby(["Заказчик"],dropna=False)[["Производство","Монтаж","Доставка","Итого"]].sum().reset_index()
            st.subheader("Сводка по заказчикам")
            st.dataframe(client_summary,use_container_width=True,hide_index=True)

    st.caption("Расчёт: производство = себестоимость материалов × 1,50; монтаж = × 1,40; доставка = 10% от себестоимости материалов + расстояние × 2 условные единицы.")


# ============================================================
# REPORTS
# ============================================================

elif menu == "Reports":

    st.header("Отчёты")
    report_section=st.radio("Раздел",["Сводные таблицы","Печать документов"],horizontal=True)

    # Shared cost query
    cost_q="""
    SELECT o.id AS object_id,o.object_name,c.name AS client_name,o.address,
           oi.id AS object_item_id,oi.item_name,oi.quantity_needed,oi.qty_installed,
           COALESCE(o.transport_distance_km,0) AS distance_km,
           COALESCE(SUM(ptm.quantity_per_unit*m.cost_per_unit*COALESCE(ptm.waste_coefficient,1)),0) AS material_unit_cost
    FROM reklet.object_items oi JOIN reklet.objects o ON o.id=oi.object_id
    LEFT JOIN reklet.clients c ON c.id=o.client_id
    LEFT JOIN reklet.product_template_materials ptm ON ptm.product_template_id=oi.product_template_id
    LEFT JOIN reklet.materials m ON m.id=ptm.material_id
    GROUP BY o.id,o.object_name,c.name,o.address,oi.id,oi.item_name,oi.quantity_needed,oi.qty_installed,o.transport_distance_km
    ORDER BY o.id DESC,oi.id DESC
    """
    report_df=run_query(cost_q,fetch=True)
    if not report_df.empty:
        report_df["Материалы"]=report_df["material_unit_cost"]*report_df["quantity_needed"]
        report_df["Производство"]=report_df["Материалы"]*1.50
        report_df["Монтаж"]=report_df["Материалы"]*1.40
        report_df["Доставка"]=report_df["Материалы"]*0.10+report_df["distance_km"]*2
        report_df["Себестоимость"]=report_df["Материалы"]
        report_df["Наценка"]=report_df["Себестоимость"]+report_df["Производство"]+report_df["Монтаж"]+report_df["Доставка"]
        report_df["Цена с наценкой 100%"]=report_df["Наценка"]*2

    if report_section=="Сводные таблицы":
        clients_summary=run_query("""
            SELECT c.name AS client_name,COUNT(DISTINCT o.id) AS objects_count,
                   COALESCE(SUM(oi.quantity_needed),0) AS items_count
            FROM reklet.clients c LEFT JOIN reklet.objects o ON o.client_id=c.id
            LEFT JOIN reklet.object_items oi ON oi.object_id=o.id
            GROUP BY c.id,c.name ORDER BY c.name
        """,fetch=True)
        st.subheader("По заказчикам")
        if not clients_summary.empty:
            clients_summary.columns=["Заказчик","Количество объектов","Количество изделий"]
            st.dataframe(clients_summary,use_container_width=True,hide_index=True)

        st.subheader("По объектам")
        if not report_df.empty:
            obj=report_df.groupby(["object_id","object_name","client_name"],dropna=False).agg(
                Количество_изделий=("quantity_needed","sum"),
                Установлено=("qty_installed","sum"),
                Материалы=("Материалы","sum"),
                Зарплата_производства=("Производство","sum"),
                Зарплата_монтажа=("Монтаж","sum"),
                Зарплата_доставки=("Доставка","sum"),
                Цена_с_наценкой=("Цена с наценкой 100%","sum")
            ).reset_index()
            obj.columns=["№","Объект","Заказчик","Изделий","Установлено","Материалы","Производство","Монтаж","Доставка","Цена с наценкой 100%"]
            st.dataframe(obj,use_container_width=True,hide_index=True)

        st.subheader("Остатки материалов")
        stock=run_query("""
            SELECT m.name,u.name AS unit,m.stock_quantity,m.cost_per_unit,(m.stock_quantity*m.cost_per_unit) AS stock_value
            FROM reklet.materials m LEFT JOIN reklet.units u ON u.id=m.unit_id ORDER BY m.name
        """,fetch=True)
        if not stock.empty:
            stock.columns=["Материал","Единица","Остаток","Цена","Стоимость остатка"]
            st.dataframe(stock,use_container_width=True,hide_index=True)

    else:
        if report_df.empty:
            st.info("Нет данных для формирования документов.")
        else:
            objects=report_df[["object_id","object_name","client_name"]].drop_duplicates()
            obj_map={f"{int(r['object_id'])} — {r['object_name']} — {r['client_name'] or 'Без заказчика'}":int(r['object_id']) for _,r in objects.iterrows()}
            selected_obj=st.selectbox("Объект",list(obj_map.keys()),key="report_object")
            object_id=obj_map[selected_obj]
            object_data=report_df[report_df["object_id"]==object_id].copy()
            client_name=str(object_data.iloc[0]["client_name"] or "Без заказчика")
            doc_type=st.selectbox("Документ",["Выверка по объекту","Выверка по заказчику","Смета объекта","Акт сдачи-приёмки работ","Приходная накладная","Расходная накладная"],key="print_document_type")

            if doc_type=="Выверка по заказчику":
                doc_data=report_df[report_df["client_name"].fillna("Без заказчика").eq(client_name)].copy()
                title=f"Выверка по заказчику: {client_name}"
            else:
                doc_data=object_data
                title=f"{doc_type}: {object_data.iloc[0]['object_name']}"

            rows=[]
            for _,r in doc_data.iterrows():
                rows.append(f"<tr><td>{escape(str(r['object_name']))}</td><td>{escape(str(r['item_name']))}</td><td>{int(r['quantity_needed'])}</td><td>{int(r['qty_installed'])}</td><td>{float(r['Материалы']):.2f}</td><td>{float(r['Производство']+r['Монтаж']+r['Доставка']):.2f}</td><td>{float(r['Цена с наценкой 100%']):.2f}</td></tr>")
            headers="<th>Объект</th><th>Изделие</th><th>Запланировано</th><th>Выполнено</th><th>Материалы</th><th>Зарплаты</th><th>Цена</th>"
            if doc_type=="Акт сдачи-приёмки работ":
                planned=int(doc_data["quantity_needed"].sum()); done=int(doc_data["qty_installed"].sum())
                act_title="Акт сдачи-приёмки работ" if done>=planned else "Промежуточный акт сдачи-приёмки работ"
                title=f"{act_title}: {object_data.iloc[0]['object_name']}"
                rows=[]
                for _,r in doc_data.iterrows(): rows.append(f"<tr><td>{escape(str(r['item_name']))}</td><td>{int(r['quantity_needed'])}</td><td>{int(r['qty_installed'])}</td></tr>")
                headers="<th>Изделие</th><th>Запланировано</th><th>Выполнено</th>"
            elif doc_type in ["Приходная накладная","Расходная накладная"]:
                if doc_type=="Приходная накладная":
                    tx=run_query("""SELECT mt.created_at,m.name,s.name AS supplier,mt.quantity,mt.unit_price FROM reklet.material_transactions mt JOIN reklet.materials m ON m.id=mt.material_id LEFT JOIN reklet.suppliers s ON s.id=mt.supplier_id WHERE mt.transaction_type='IN' ORDER BY mt.created_at DESC LIMIT 500""",fetch=True)
                    rows=[f"<tr><td>{escape(str(r['created_at']))}</td><td>{escape(str(r['material']))}</td><td>{escape(str(r['supplier'] or ''))}</td><td>{float(r['quantity']):.4f}</td><td>{float(r['unit_price'] or 0):.2f}</td></tr>" for _,r in tx.iterrows()]
                    headers="<th>Дата</th><th>Материал</th><th>Поставщик</th><th>Количество</th><th>Цена</th>"
                else:
                    tx=run_query("""SELECT mt.created_at,m.name,o.object_name,mt.quantity FROM reklet.material_transactions mt JOIN reklet.materials m ON m.id=mt.material_id LEFT JOIN reklet.objects o ON o.id=mt.object_id WHERE mt.transaction_type='OUT' ORDER BY mt.created_at DESC LIMIT 500""",fetch=True)
                    rows=[f"<tr><td>{escape(str(r['created_at']))}</td><td>{escape(str(r['material']))}</td><td>{escape(str(r['object_name'] or ''))}</td><td>{float(r['quantity']):.4f}</td></tr>" for _,r in tx.iterrows()]
                    headers="<th>Дата</th><th>Материал</th><th>Объект</th><th>Количество</th>"

            html=f"""<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title><style>body{{font-family:Arial;margin:35px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #777;padding:7px;text-align:left}}th{{background:#eee}}h1{{font-size:22px}}.sign{{margin-top:70px;display:flex;justify-content:space-between}}</style></head><body><h1>{escape(title)}</h1><table><tr>{headers}</tr>{''.join(rows)}</table><div class='sign'><div>Заказчик: __________________</div><div>Исполнитель: __________________</div></div><script>window.print();</script></body></html>"""
            st.download_button("Открыть / скачать документ для печати",data=html,file_name="reklet_document.html",mime="text/html")

            st.info("Смета включает материалы + расчётные зарплаты производства, монтажа и доставки + 100% наценку на эту себестоимость.")

