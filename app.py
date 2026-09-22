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
        sslmode="require"
    )


def run_query(query, params=None, fetch=False):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(query, params)

        if fetch:

            rows = cursor.fetchall()

            columns = [
                description[0]
                for description in cursor.description
            ]

            return pd.DataFrame(
                rows,
                columns=columns
            )

        conn.commit()

        return None

    except Exception:

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


menu = st.radio(
    "Раздел",
    menu_options,
    horizontal=True,
    label_visibility="collapsed"
)


st.markdown("---")


# ============================================================
# CLIENTS
# ============================================================

if menu == "Клиенты":

    st.header("Клиенты")

    df = get_clients()

    if not df.empty:

        edited = data_editor_ru(
            df,
            key="clients_editor",
            width="stretch",
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

            st.success("Сохранено.")

            st.rerun()

    else:

        st.info("Нет клиентов.")

    st.markdown("---")

    st.subheader("Добавить клиента")

    with st.form("add_client"):

        name = st.text_input("Название")

        contact = st.text_area(
            "Контакт"
        )

        submit = st.form_submit_button(
            "Добавить"
        )

        if submit:

            if not name.strip():

                st.warning(
                    "Необходимо указать название."
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
                    "Клиент добавлен."
                )

                st.rerun()


# ============================================================
# OBJECTS
# ============================================================

elif menu == "Объекты":

    st.header("Объекты")

    sub = st.radio(
        "Объекты",
        [
            "Список объектов",
            "Состав объекта",
            "Потребность в материалах"
        ],
        horizontal=True
    )

    st.markdown("---")


    # ========================================================
    # OBJECT LIST
    # ========================================================

    if sub == "Список объектов":

        clients = get_clients()

        df = get_objects()

        if not df.empty:

            display = df[
                [
                    "id",
                    "object_name",
                    "client_name",
                    "address"
                ]
            ].copy()

            edited = data_editor_ru(
                display,
                key="objects_editor",
                width="stretch"
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
                            row["object_name"],
                            row["address"],
                            safe_int(row["id"])
                        )
                    )

                st.success("Сохранено.")

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
                "Клиент",
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
                        "Необходимо указать клиента и название объекта."
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

    elif sub == "Состав объекта":

        objects = get_objects()

        if objects.empty:

            st.info(
                "Нет объектов."
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

                edited = data_editor_ru(
                    display,
                    key=f"object_items_{object_id}",
                    width="stretch"
                )

                if st.button(
                    "Сохранить количество",
                    key=f"save_items_{object_id}"
                ):

                    for _, row in edited.iterrows():

                        qty_new = safe_int(
                            row["qty_new"]
                        )

                        qty_production = safe_int(
                            row["qty_production"]
                        )

                        qty_ready = safe_int(
                            row["qty_ready"]
                        )

                        qty_shipped = safe_int(
                            row["qty_shipped"]
                        )

                        qty_arrived = safe_int(
                            row["qty_arrived"]
                        )

                        qty_installing = safe_int(
                            row["qty_installing"]
                        )

                        qty_installed = safe_int(
                            row["qty_installed"]
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
                                row["item_name"],
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

                    st.success("Сохранено.")

                    st.rerun()

            else:

                st.info(
                    "В этом объекте нет изделий."
                )


            st.markdown("---")

            st.subheader(
                "Добавить изделие"
            )

            templates = get_templates()

            # Показываем при добавлении только изделия заказчика выбранного объекта.
            # Это не меняет принадлежность изделия в справочнике и не затрагивает БД.
            object_client_name = str(
                object_row["client_name"] or ""
            ).strip()

            if not object_client_name:
                st.warning(
                    "У объекта не указан заказчик — нельзя определить список изделий."
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
                    f"{row['name']} — "
                    f"{row['client_name'] or 'Общее'}":
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

                            existing_id = safe_int(
                                existing_item.iloc[0]["id"]
                            )

                            run_query(
                                """
                                UPDATE reklet.object_items
                                SET
                                    quantity = COALESCE(quantity, 0) + %s,
                                    quantity_needed = COALESCE(quantity_needed, 0) + %s,
                                    qty_new = COALESCE(qty_new, 0) + %s
                                WHERE id = %s
                                """,
                                (quantity, quantity, quantity, existing_id)
                            )

                            st.success(
                                "Количество изделия увеличено."
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
                                (
                                    %s,%s,%s,%s,%s,%s,%s,'New'
                                )
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

                            st.success(
                                "Изделие добавлено."
                            )

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
                    Спецификация
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
                    Объект Спецификация
                </h2>

                <p>
                    <b>Клиент:</b>
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
                        <th>No.</th>
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
                "Скачать спецификацию HTML",
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
                "Нет объектов."
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
                    "К этому объекту не привязаны изделия."
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
                        "### Потребность в материалах by Изделие"
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

                    st.dataframe(
                        product_view,
                        width="stretch",
                        hide_index=True
                    )

                    st.markdown(
                        "### Общая потребность в материалах"
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

                    st.dataframe(
                        total_view,
                        width="stretch",
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
                            Потребность в материалах
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
                            Потребность в материалах
                        </h2>

                        <p>
                            <b>Клиент:</b>
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

                                <th>No.</th>
                                <th>Материал</th>
                                <th>Единица</th>
                                <th>Требуется</th>
                                <th>Остаток</th>
                                <th>Недостаток</th>
                                <th>Стоимость</th>

                            </tr>

                            {html_rows}

                        </table>

                        <h3>

                            Total Стоимость материалов:
                            {float(total_cost):.2f}

                        </h3>

                        <script>
                            window.print();
                        </script>

                    </body>

                    </html>
                    """

                    st.download_button(
                        "Скачать потребность в материалах HTML",
                        data=material_html,
                        file_name=(
                            f"material_requirements_"
                            f"{object_id}.html"
                        ),
                        mime="text/html"
                    )


# ============================================================
# PRODUCT TEMPLATES
# ============================================================

elif menu == "Изделия":

    st.header(
        "Изделия"
    )

    templates = get_templates()

    client_filter_options = ["Все заказчики"]
    if not templates.empty:
        client_filter_options += sorted(
            templates["client_name"]
            .dropna()
            .astype(str)
            .str.strip()
            .loc[lambda x: x != ""]
            .unique()
            .tolist()
        )

    selected_client_filter = st.selectbox(
        "Заказчик",
        client_filter_options,
        key="products_client_filter"
    )

    if selected_client_filter != "Все заказчики":
        templates = templates[
            templates["client_name"].fillna("").astype(str).str.strip().eq(
                selected_client_filter
            )
        ].copy()


    # ========================================================
    # CREATE
    # ========================================================

    with st.expander(
        "Создать изделие",
        expanded=False
    ):

        with st.form(
            "create_template"
        ):

            name = st.text_input(
                "Название изделия"
            )

            type_value = st.selectbox(
                "Тип",
                [
                    "recurrent",
                    "custom"
                ]
            )

            client_name = st.text_input(
                "Клиент"
            )

            category = st.text_input(
                "Категория"
            )

            submit = st.form_submit_button(
                "Создать изделие"
            )

            if submit:

                if not name.strip():

                    st.warning(
                        "Необходимо указать название изделия."
                    )

                else:

                    run_query(
                        """
                        INSERT INTO
                        reklet.product_templates
                        (
                            name,
                            type,
                            client_name,
                            category
                        )

                        VALUES (%s,%s,%s,%s)
                        """,
                        (
                            name,
                            type_value,
                            client_name or None,
                            category or None
                        )
                    )

                    st.success(
                        "Изделие создано."
                    )

                    st.rerun()


    # ========================================================
    # EDIT
    # ========================================================

    if not templates.empty:

        st.subheader(
            "Изделия"
        )

        edited = data_editor_ru(
            templates,
            key="templates_editor",
            width="stretch",
            num_rows="fixed"
        )

        if st.button(
            "Сохранить изменения изделий",
            key="save_templates"
        ):

            for _, row in edited.iterrows():

                run_query(
                    """
                    UPDATE
                        reklet.product_templates

                    SET
                        name = %s,
                        type = %s,
                        client_name = %s,
                        category = %s

                    WHERE id = %s
                    """,
                    (
                        row["name"],
                        row["type"],
                        row["client_name"],
                        row["category"],
                        safe_int(row["id"])
                    )
                )

            st.success(
                "Сохранено."
            )

            st.rerun()


    st.markdown("---")

    st.subheader(
        "Спецификация материалов изделия"
    )

    if templates.empty:

        st.info(
            "Сначала создайте изделие."
        )

    else:

        template_map = {

            f"{row['id']} — "
            f"{row['name']} — "
            f"{row['client_name'] or 'Общее'}":
                int(row["id"])

            for _, row in templates.iterrows()
        }

        selected = st.selectbox(
            "Изделие",
            list(template_map.keys()),
            key="template_spec"
        )

        template_id = template_map[
            selected
        ]

        specification = run_query(
            """
            SELECT

                ptm.id,

                ptm.material_id,

                m.name
                    AS material_name,

                u.name
                    AS unit_name,

                ptm.quantity_per_unit,

                ptm.waste_coefficient

            FROM
                reklet.product_template_materials ptm

            JOIN reklet.materials m

                ON m.id = ptm.material_id

            LEFT JOIN reklet.units u

                ON u.id = m.unit_id

            WHERE
                ptm.product_template_id = %s

            ORDER BY
                m.name
            """,
            (template_id,),
            fetch=True
        )

        if not specification.empty:

            display = specification[
                [
                    "id",
                    "material_name",
                    "unit_name",
                    "quantity_per_unit",
                    "waste_coefficient"
                ]
            ].copy()

            st.dataframe(
                display,
                width="stretch",
                hide_index=True
            )

        else:

            st.info(
                "В спецификации этого изделия нет материалов."
            )


        st.markdown("---")

        st.subheader(
            "Добавить материал"
        )

        materials = get_materials()

        if materials.empty:

            st.warning(
                "Сначала создайте материалы на складе материалов."
            )

        else:

            material_map = {

                f"{row['name']} — "
                f"{row['unit_name'] or ''}":
                    int(row["id"])

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

                submit = st.form_submit_button(
                    "Добавить материал"
                )

                if submit:

                    material_id = material_map[
                        material_label
                    ]

                    run_query(
                        """
                        INSERT INTO
                        reklet.product_template_materials
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

                    st.success(
                        "Материал добавлен в спецификацию."
                    )

                    st.rerun()


    # ========================================================
    # DELETIONS — ALWAYS AT THE BOTTOM
    # ========================================================

    st.markdown("---")

    with st.expander("Удаление", expanded=False):

        st.warning(
            "Внимание: удаление необратимо. Перед удалением убедитесь, "
            "что выбран правильный объект."
        )

        if not templates.empty:
            st.markdown("**Удалить изделие**")

            delete_product_map = {
                f"{row['id']} — {row['name']}": int(row["id"])
                for _, row in templates.iterrows()
            }

            delete_product = st.selectbox(
                "Изделие",
                list(delete_product_map.keys()),
                key="delete_product"
            )

            confirm_product = st.checkbox(
                "Я понимаю, что удаление изделия необратимо.",
                key="confirm_delete_product"
            )

            if st.button(
                "Удалить изделие",
                key="delete_product_button",
                disabled=not confirm_product
            ):
                try:
                    run_query(
                        """
                        DELETE FROM
                            reklet.product_templates
                        WHERE id = %s
                        """,
                        (delete_product_map[delete_product],)
                    )
                    st.success("Изделие удалено.")
                    st.rerun()

                except Exception as e:
                    st.error(
                        "Изделие нельзя удалить. Возможно, оно уже используется в объекте."
                    )
                    st.code(str(e))

        if not specification.empty:
            st.markdown("---")
            st.markdown("**Удалить строку спецификации**")

            delete_map = {
                f"{row['id']} — {row['material_name']}": int(row["id"])
                for _, row in specification.iterrows()
            }

            delete_label = st.selectbox(
                "Строка спецификации",
                list(delete_map.keys()),
                key="delete_spec_row"
            )

            confirm_spec = st.checkbox(
                "Я понимаю, что удаление строки спецификации необратимо.",
                key="confirm_delete_spec_row"
            )

            if st.button(
                "Удалить строку спецификации",
                key="delete_spec_row_button",
                disabled=not confirm_spec
            ):
                run_query(
                    """
                    DELETE FROM
                        reklet.product_template_materials
                    WHERE id = %s
                    """,
                    (delete_map[delete_label],)
                )
                st.success("Строка спецификации удалена.")
                st.rerun()



# ============================================================
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

    nav_cols = st.columns(6)
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

        # Категории хранятся отдельно от материалов.
        # Материал только ссылается на выбранную категорию через category_id.
        cat_display = categories[["id", "name"]].copy() if not categories.empty else pd.DataFrame(columns=["id", "name"])

        if cat_display.empty:
            st.info("Категорий пока нет. Создайте первую категорию ниже.")
        else:
            st.dataframe(
                cat_display,
                width="stretch",
                hide_index=True
            )

            edit_cat_map = {
                f"{row['id']} — {row['name']}": int(row["id"])
                for _, row in categories.iterrows()
            }

            edit_cat_label = st.selectbox(
                "Категория для изменения",
                list(edit_cat_map.keys()),
                key="material_category_to_edit"
            )
            edit_cat_id = edit_cat_map[edit_cat_label]
            edit_cat_name = str(
                categories[categories["id"] == edit_cat_id].iloc[0]["name"]
            )

            with st.form("edit_material_category_form"):
                new_cat_name = st.text_input(
                    "Новое название категории",
                    value=edit_cat_name
                )
                save_cat = st.form_submit_button("Сохранить категорию")

                if save_cat:
                    if not new_cat_name.strip():
                        st.warning("Укажите название категории.")
                    else:
                        try:
                            run_query(
                                """
                                UPDATE reklet.material_categories
                                SET name = %s
                                WHERE id = %s
                                """,
                                (new_cat_name.strip(), edit_cat_id)
                            )
                            st.success("Категория сохранена.")
                            st.rerun()
                        except Exception:
                            st.error("Не удалось сохранить категорию. Возможно, такое название уже существует.")

        with st.form("add_material_category_form"):
            new_category = st.text_input(
                "Новая категория",
                placeholder="Например: Листовые материалы"
            )
            add_category = st.form_submit_button("Добавить категорию")

            if add_category:
                if not new_category.strip():
                    st.warning("Укажите название категории.")
                else:
                    try:
                        run_query(
                            """
                            INSERT INTO reklet.material_categories (name)
                            VALUES (%s)
                            """,
                            (new_category.strip(),)
                        )
                        st.success("Категория добавлена.")
                        st.rerun()
                    except Exception:
                        st.error("Такая категория уже существует или не может быть добавлена.")




    elif active_material_section == "receipt":

        # ========================================================
        # GOODS RECEIPT
        # ========================================================

        st.markdown("---")

        st.subheader(
            "Приход материалов"
        )

        if not materials.empty:

            material_map = {

                row["name"]:
                    int(row["id"])

                for _, row in materials.iterrows()
            }

            suppliers = get_suppliers()

            supplier_map = {}

            if not suppliers.empty:

                supplier_map = {

                    row["name"]:
                        int(row["id"])

                    for _, row in suppliers.iterrows()
                }

            with st.form(
                "goods_receipt"
            ):

                receipt_material = st.selectbox(
                    "Материал",
                    list(material_map.keys())
                )

                receipt_supplier = st.selectbox(
                    "Поставщик",
                    [""] + list(
                        supplier_map.keys()
                    )
                )

                receipt_quantity = st.number_input(
                    "Количество",
                    min_value=0.0001,
                    value=1.0,
                    format="%.4f"
                )

                receipt_price = st.number_input(
                    "Цена за единицу",
                    min_value=0.0,
                    value=0.0,
                    format="%.2f"
                )

                submit = st.form_submit_button(
                    "Оформить приход"
                )

                if submit:

                    material_id = material_map[
                        receipt_material
                    ]

                    supplier_id = (

                        supplier_map[
                            receipt_supplier
                        ]

                        if receipt_supplier

                        else None
                    )

                    run_query(
                        """
                        INSERT INTO
                        reklet.material_transactions
                        (
                            material_id,
                            supplier_id,
                            operation_type,
                            quantity,
                            unit_price,
                            transaction_type
                        )

                        VALUES
                        (
                            %s,%s,
                            'purchase',
                            %s,%s,
                            'IN'
                        )
                        """,
                        (
                            material_id,
                            supplier_id,
                            receipt_quantity,
                            receipt_price
                        )
                    )

                    run_query(
                        """
                        UPDATE reklet.materials

                        SET stock_quantity =
                            COALESCE(
                                stock_quantity,
                                0
                            )
                            + %s

                        WHERE id = %s
                        """,
                        (
                            receipt_quantity,
                            material_id
                        )
                    )

                    if supplier_id:

                        run_query(
                            """
                            INSERT INTO
                            reklet.material_suppliers
                            (
                                material_id,
                                supplier_id,
                                purchase_price
                            )

                            VALUES (%s,%s,%s)

                            ON CONFLICT
                            (
                                material_id,
                                supplier_id
                            )

                            DO UPDATE SET

                                purchase_price =
                                    EXCLUDED.purchase_price
                            """,
                            (
                                material_id,
                                supplier_id,
                                receipt_price
                            )
                        )

                    st.success(
                        "Приход материалов оформлен."
                    )

                    st.rerun()



    elif active_material_section == "issue":

        # ========================================================
        # MATERIAL ISSUE
        # ========================================================

        st.markdown("---")

        st.subheader(
            "Выдача материалов в производство"
        )

        objects = get_objects()

        if not materials.empty and not objects.empty:

            material_map = {

                row["name"]:
                    int(row["id"])

                for _, row in materials.iterrows()
            }

            object_map = {

                f"{row['id']} — {row['object_name']}":
                    int(row["id"])

                for _, row in objects.iterrows()
            }

            with st.form(
                "material_issue"
            ):

                issue_material = st.selectbox(
                    "Материал",
                    list(material_map.keys())
                )

                issue_object = st.selectbox(
                    "Объект",
                    list(object_map.keys())
                )

                issue_quantity = st.number_input(
                    "Количество",
                    min_value=0.0001,
                    value=1.0,
                    format="%.4f"
                )

                submit = st.form_submit_button(
                    "Выдать в производство"
                )

                if submit:

                    material_id = material_map[
                        issue_material
                    ]

                    object_id = object_map[
                        issue_object
                    ]

                    current_stock = run_query(
                        """
                        SELECT
                            stock_quantity

                        FROM reklet.materials

                        WHERE id = %s
                        """,
                        (material_id,),
                        fetch=True
                    )

                    stock = safe_float(
                        current_stock.iloc[0][
                            "stock_quantity"
                        ]
                    )

                    if issue_quantity > stock:

                        st.error(
                            f"Insufficient stock. "
                            f"Доступно: {stock}"
                        )

                    else:

                        run_query(
                            """
                            INSERT INTO
                            reklet.material_transactions
                            (
                                material_id,
                                object_id,
                                operation_type,
                                quantity,
                                transaction_type
                            )

                            VALUES
                            (
                                %s,%s,
                                'production_transfer',
                                %s,
                                'OUT'
                            )
                            """,
                            (
                                material_id,
                                object_id,
                                issue_quantity
                            )
                        )

                        run_query(
                            """
                            UPDATE reklet.materials

                            SET stock_quantity =
                                stock_quantity - %s

                            WHERE id = %s
                            """,
                            (
                                issue_quantity,
                                material_id
                            )
                        )

                        st.success(
                            "Материал выдан в производство."
                        )

                        st.rerun()



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

    st.header(
        "Поставщики"
    )

    suppliers = get_suppliers()

    with st.expander(
        "Создать поставщика",
        expanded=False
    ):

        with st.form(
            "create_supplier"
        ):

            name = st.text_input(
                "Название"
            )

            supplier_type = st.selectbox(
                "Тип поставщика",
                [
                    "material_supplier",
                    "subcontractor",
                    "both"
                ]
            )

            contact_person = st.text_input(
                "Контактное лицо"
            )

            phone = st.text_input(
                "Телефон"
            )

            email = st.text_input(
                "Email"
            )

            category = st.text_input(
                "Категория"
            )

            conditions = st.text_area(
                "Условия"
            )

            contact_info = st.text_area(
                "Контактная информация"
            )

            submit = st.form_submit_button(
                "Создать поставщика"
            )

            if submit:

                if not name.strip():

                    st.warning(
                        "Необходимо указать название."
                    )

                else:

                    run_query(
                        """
                        INSERT INTO reklet.suppliers
                        (
                            name,
                            type,
                            contact_info,
                            contact_person,
                            phone,
                            email,
                            category,
                            conditions
                        )

                        VALUES
                        (
                            %s,%s,%s,%s,
                            %s,%s,%s,%s
                        )
                        """,
                        (
                            name,
                            supplier_type,
                            contact_info,
                            contact_person,
                            phone,
                            email,
                            category,
                            conditions
                        )
                    )

                    st.success(
                        "Поставщик создан."
                    )

                    st.rerun()


    if not suppliers.empty:

        display = suppliers[
            [
                "id",
                "name",
                "type",
                "contact_person",
                "phone",
                "email",
                "category",
                "conditions"
            ]
        ].copy()

        edited = data_editor_ru(
            display,
            key="suppliers_editor",
            width="stretch"
        )

        if st.button(
            "Сохранить изменения поставщика"
        ):

            for _, row in edited.iterrows():

                run_query(
                    """
                    UPDATE reklet.suppliers

                    SET

                        name = %s,
                        type = %s,
                        contact_person = %s,
                        phone = %s,
                        email = %s,
                        category = %s,
                        conditions = %s

                    WHERE id = %s
                    """,
                    (
                        row["name"],
                        row["type"],
                        row["contact_person"],
                        row["phone"],
                        row["email"],
                        row["category"],
                        row["conditions"],
                        safe_int(row["id"])
                    )
                )

            st.success(
                "Сохранено."
            )

            st.rerun()


        st.markdown("---")
        st.subheader("Материалы поставщика")

        if not suppliers.empty:
            supplier_material_map = {
                f"{row['id']} — {row['name']}": int(row['id'])
                for _, row in suppliers.iterrows()
            }
            selected_supplier_label = st.selectbox(
                "Поставщик",
                list(supplier_material_map.keys()),
                key="supplier_material_supplier"
            )
            selected_supplier_id = supplier_material_map[selected_supplier_label]

            material_data = run_query(
                """
                SELECT ms.id, m.name AS material, ms.purchase_price,
                       ms.supplier_code, ms.conditions, ms.is_preferred
                FROM reklet.material_suppliers ms
                JOIN reklet.materials m ON m.id = ms.material_id
                WHERE ms.supplier_id = %s
                ORDER BY m.name
                """,
                (selected_supplier_id,),
                fetch=True
            )

            if not material_data.empty:
                st.dataframe(material_data, width="stretch", hide_index=True)
            else:
                st.info("Для этого поставщика материалы пока не привязаны.")

            all_materials = get_materials_with_categories()
            material_options = {
                f"{row['name']} — {row['category_name'] or 'Без категории'}": int(row['id'])
                for _, row in all_materials.iterrows()
            }

            if material_options:
                with st.form("supplier_material_link_form"):
                    selected_material_label = st.selectbox(
                        "Материал", list(material_options.keys())
                    )
                    purchase_price = st.number_input(
                        "Закупочная цена", min_value=0.0, value=0.0, format="%.2f"
                    )
                    supplier_code = st.text_input("Код поставщика")
                    material_conditions = st.text_area("Условия")
                    preferred = st.checkbox("Предпочтительный поставщик")
                    save_link = st.form_submit_button("Добавить / сохранить материал")

                    if save_link:
                        run_query(
                            """
                            INSERT INTO reklet.material_suppliers
                            (material_id, supplier_id, purchase_price, supplier_code, conditions, is_preferred)
                            VALUES (%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (material_id, supplier_id) DO UPDATE SET
                                purchase_price = EXCLUDED.purchase_price,
                                supplier_code = EXCLUDED.supplier_code,
                                conditions = EXCLUDED.conditions,
                                is_preferred = EXCLUDED.is_preferred
                            """,
                            (material_options[selected_material_label], selected_supplier_id,
                             purchase_price, supplier_code, material_conditions, preferred)
                        )
                        st.success("Материал поставщика сохранён.")
                        st.rerun()

        st.markdown("---")

        with st.expander("Удаление", expanded=False):
            st.warning(
                "Внимание: удаление поставщика необратимо. "
                "Если поставщик используется в материалах, удалить его может быть невозможно."
            )

            delete_map = {
                f"{row['id']} — {row['name']}": int(row["id"])
                for _, row in suppliers.iterrows()
            }

            delete_label = st.selectbox(
                "Поставщик",
                list(delete_map.keys()),
                key="delete_supplier"
            )

            confirm_supplier = st.checkbox(
                "Я понимаю, что удаление поставщика необратимо.",
                key="confirm_delete_supplier"
            )

            if st.button(
                "Удалить поставщика",
                key="delete_supplier_button",
                disabled=not confirm_supplier
            ):
                try:
                    run_query(
                        """
                        DELETE FROM
                            reklet.suppliers
                        WHERE id = %s
                        """,
                        (delete_map[delete_label],)
                    )
                    st.success("Поставщик удалён.")
                    st.rerun()

                except Exception as e:
                    st.error("Поставщика нельзя удалить.")
                    st.code(str(e))


# ============================================================
# PRODUCTION
# ============================================================

elif menu == "Производство":

    st.header("Производство")

    objects = get_objects()

    if objects.empty:
        st.info("Нет объектов.")
    else:
        # Отбор находится перед перечнем — сначала выбираем объект,
        # затем видим только изделия, которые еще нужно изготовить.
        object_filter = st.selectbox(
            "Отбор по объекту",
            ["Все объекты"]
            + [
                f"{row['id']} — {row['object_name']}"
                for _, row in objects.iterrows()
            ],
            key="production_object_filter"
        )

        query = """
        SELECT
            oi.id,
            oi.object_id,
            o.object_name,
            c.name AS client_name,
            oi.item_name,
            oi.quantity_needed,
            COALESCE(oi.qty_new, 0) AS qty_new,
            COALESCE(oi.qty_production, 0) AS qty_production,
            COALESCE(oi.qty_ready, 0) AS qty_ready,
            COALESCE(oi.qty_shipped, 0) AS qty_shipped,
            COALESCE(oi.qty_arrived, 0) AS qty_arrived,
            COALESCE(oi.qty_installing, 0) AS qty_installing,
            COALESCE(oi.qty_installed, 0) AS qty_installed,
            CASE
                WHEN COALESCE(oi.qty_new, 0) > 0
                    THEN COALESCE(oi.qty_new, 0)
                ELSE COALESCE(oi.qty_production, 0)
            END AS action_quantity
        FROM reklet.object_items oi
        JOIN reklet.objects o
            ON o.id = oi.object_id
        LEFT JOIN reklet.clients c
            ON c.id = o.client_id
        WHERE
            COALESCE(oi.qty_new, 0) > 0
            OR COALESCE(oi.qty_production, 0) > 0
        """

        params = []

        if object_filter != "Все объекты":
            object_id = int(object_filter.split(" — ")[0])
            query += " AND oi.object_id = %s"
            params.append(object_id)

        query += " ORDER BY o.object_name, oi.item_name"

        df = run_query(query, tuple(params), fetch=True)

        if df.empty:
            st.success("Все изделия по выбранному отбору уже изготовлены и переданы в готовую продукцию.")
        else:
            display = df[
                [
                    "id",
                    "object_name",
                    "client_name",
                    "item_name",
                    "quantity_needed",
                    "qty_new",
                    "qty_production",
                    "qty_ready",
                    "action_quantity"
                ]
            ].copy()

            display.columns = [
                "№",
                "Объект",
                "Заказчик",
                "Изделие",
                "Заказано",
                "Осталось запустить",
                "В производстве",
                "Передано в готовую продукцию",
                "Количество для следующего действия"
            ]

            st.subheader("Перечень")
            st.dataframe(
                display,
                width="stretch",
                hide_index=True
            )

            st.markdown("---")
            st.subheader("Действие производства")

            item_map = {
                f"{int(row['id'])} — {row['object_name']} — {row['item_name']}": int(row['id'])
                for _, row in df.iterrows()
            }

            selected_item = st.selectbox(
                "Изделие",
                list(item_map.keys()),
                key="production_item"
            )

            item_id = item_map[selected_item]
            item_row = df[df["id"] == item_id].iloc[0]

            action = st.radio(
                "Действие",
                [
                    "Запустить производство",
                    "Переместить в готовую продукцию"
                ],
                horizontal=True,
                key="production_action"
            )

            if action == "Запустить производство":
                max_qty = safe_int(item_row["qty_new"])
            else:
                max_qty = safe_int(item_row["qty_production"])

            if max_qty > 0:
                action_qty = st.number_input(
                    "Количество",
                    min_value=1,
                    max_value=max_qty,
                    value=min(1, max_qty),
                    step=1,
                    key="production_action_quantity"
                )

                if st.button(
                    "Исполнить",
                    key="execute_production_action"
                ):
                    if action == "Запустить производство":
                        run_query(
                            """
                            UPDATE reklet.object_items
                            SET
                                qty_new = COALESCE(qty_new, 0) - %s,
                                qty_production = COALESCE(qty_production, 0) + %s,
                                production_status = 'in_progress',
                                production_progress_pct =
                                    CASE
                                        WHEN quantity_needed > 0 THEN LEAST(
                                            100,
                                            ROUND(
                                                (
                                                    COALESCE(qty_production, 0) + %s
                                                )::numeric
                                                / quantity_needed * 100
                                            )
                                        )
                                        ELSE 0
                                    END
                            WHERE id = %s
                            """,
                            (action_qty, action_qty, action_qty, item_id)
                        )
                    else:
                        # Частичная передача разрешена. После передачи только
                        # фактически переданное количество уходит в готовую продукцию.
                        run_query(
                            """
                            UPDATE reklet.object_items
                            SET
                                qty_production = COALESCE(qty_production, 0) - %s,
                                qty_ready = COALESCE(qty_ready, 0) + %s,
                                production_status =
                                    CASE
                                        WHEN COALESCE(qty_production, 0) - %s <= 0
                                             AND COALESCE(qty_new, 0) <= 0
                                            THEN 'completed'
                                        ELSE 'in_progress'
                                    END,
                                production_progress_pct =
                                    CASE
                                        WHEN quantity_needed > 0 THEN LEAST(
                                            100,
                                            ROUND(
                                                (
                                                    quantity_needed
                                                    - COALESCE(qty_new, 0)
                                                    - (
                                                        COALESCE(qty_production, 0) - %s
                                                    )
                                                )::numeric
                                                / quantity_needed * 100
                                            )
                                        )
                                        ELSE 0
                                    END
                            WHERE id = %s
                            """,
                            (action_qty, action_qty, action_qty, action_qty, item_id)
                        )

                        # Отдельная запись движения: именно она формирует
                        # историю того, что реально поступило на склад готовой продукции.
                        run_query(
                            """
                            INSERT INTO reklet.finished_goods
                            (
                                object_item_id,
                                object_id,
                                quantity,
                                status
                            )
                            SELECT
                                id,
                                object_id,
                                %s,
                                'ready'
                            FROM reklet.object_items
                            WHERE id = %s
                            """,
                            (action_qty, item_id)
                        )

                        run_query(
                            """
                            INSERT INTO reklet.finished_goods_transactions
                            (
                                object_item_id,
                                object_id,
                                operation_type,
                                quantity
                            )
                            SELECT
                                id,
                                object_id,
                                'ready',
                                %s
                            FROM reklet.object_items
                            WHERE id = %s
                            """,
                            (action_qty, item_id)
                        )

                    st.success("Производство обновлено.")
                    st.rerun()
            else:
                st.info("Для выбранного действия сейчас нет доступного количества.")

        # ========================================================
        # PRODUCTION MOVEMENT HISTORY
        # ========================================================

        st.markdown("---")
        st.subheader("Движения по производству")

        movement_objects = run_query(
            """
            SELECT DISTINCT
                o.id,
                o.object_name
            FROM reklet.finished_goods_transactions fgt
            JOIN reklet.objects o
                ON o.id = fgt.object_id
            WHERE fgt.operation_type = 'ready'
            ORDER BY o.object_name
            """,
            fetch=True
        )

        movement_clients = run_query(
            """
            SELECT DISTINCT
                c.id,
                c.name
            FROM reklet.finished_goods_transactions fgt
            JOIN reklet.objects o
                ON o.id = fgt.object_id
            JOIN reklet.clients c
                ON c.id = o.client_id
            WHERE fgt.operation_type = 'ready'
            ORDER BY c.name
            """,
            fetch=True
        )

        col1, col2 = st.columns(2)

        with col1:
            movement_object_options = ["Все объекты"] + [
                f"{int(row['id'])} — {row['object_name']}"
                for _, row in movement_objects.iterrows()
            ]
            movement_object_filter = st.selectbox(
                "Отбор по объекту",
                movement_object_options,
                key="production_movement_object_filter"
            )

        with col2:
            movement_client_options = ["Все заказчики"] + [
                f"{int(row['id'])} — {row['name']}"
                for _, row in movement_clients.iterrows()
            ]
            movement_client_filter = st.selectbox(
                "Отбор по заказчику",
                movement_client_options,
                key="production_movement_client_filter"
            )

        movement_query = """
            SELECT
                fgt.id,
                o.object_name AS object_name,
                c.name AS client_name,
                oi.item_name AS product_name,
                fgt.quantity,
                fgt.created_at
            FROM reklet.finished_goods_transactions fgt
            JOIN reklet.object_items oi
                ON oi.id = fgt.object_item_id
            LEFT JOIN reklet.objects o
                ON o.id = fgt.object_id
            LEFT JOIN reklet.clients c
                ON c.id = o.client_id
            WHERE fgt.operation_type = 'ready'
        """

        movement_params = []

        if movement_object_filter != "Все объекты":
            movement_query += " AND fgt.object_id = %s"
            movement_params.append(
                int(movement_object_filter.split(" — ")[0])
            )

        if movement_client_filter != "Все заказчики":
            movement_query += " AND o.client_id = %s"
            movement_params.append(
                int(movement_client_filter.split(" — ")[0])
            )

        movement_query += " ORDER BY fgt.created_at DESC, fgt.id DESC"

        movements = run_query(
            movement_query,
            tuple(movement_params),
            fetch=True
        )

        if movements.empty:
            st.info("Движений на склад готовой продукции пока нет.")
        else:
            movements = movements.copy()
            movements.columns = [
                "№",
                "Объект",
                "Заказчик",
                "Изделие",
                "Количество",
                "Когда передано"
            ]
            st.dataframe(
                movements,
                width="stretch",
                hide_index=True
            )

# ============================================================
# FINISHED GOODS
# ============================================================

elif menu == "Готовая продукция":

    st.header(
        "Готовая продукция"
    )

    df = run_query(
        """
        SELECT

            fg.id,

            o.object_name,

            c.name AS client_name,

            oi.item_name,

            fg.quantity,

            fg.status,

            fg.created_at

        FROM
            reklet.finished_goods fg

        JOIN reklet.object_items oi
            ON oi.id = fg.object_item_id

        LEFT JOIN reklet.objects o
            ON o.id = fg.object_id

        LEFT JOIN reklet.clients c
            ON c.id = o.client_id

        ORDER BY
            o.object_name,
            fg.created_at
        """,
        fetch=True
    )

    if df.empty:

        st.info(
            "Нет готовой продукции."
        )

    else:

        finished_view = df.copy()
        st.dataframe(
            finished_view,
            width="stretch",
            hide_index=True
        )

        st.markdown("---")

        st.subheader(
            "Отгрузка / доставка"
        )

        fg_map = {

            f"{row['id']} — "
            f"{row['object_name']} — "
            f"{row['item_name']} — "
            f"{row['status']}":
                int(row["id"])

            for _, row in df.iterrows()

            if row["status"] != "arrived"
        }

        if fg_map:

            selected = st.selectbox(
                "Готовое изделие",
                list(fg_map.keys())
            )

            fg_id = fg_map[
                selected
            ]

            fg_row = df[
                df["id"] == fg_id
            ].iloc[0]

            current_qty = safe_int(
                fg_row["quantity"]
            )

            if fg_row["status"] == "ready":

                action = "ship"

                label = "Отгрузить"

            else:

                action = "arrive"

                label = "Отметить как доставленное"

            qty = st.number_input(
                "Количество",
                min_value=1,
                max_value=current_qty,
                value=1
            )

            if st.button(label):

                if action == "ship":

                    run_query(
                        """
                        UPDATE
                            reklet.finished_goods

                        SET

                            quantity =
                                quantity - %s,

                            status =

                                CASE

                                    WHEN
                                        quantity - %s <= 0

                                    THEN 'shipped'

                                    ELSE 'ready'

                                END

                        WHERE id = %s
                        """,
                        (
                            qty,
                            qty,
                            fg_id
                        )
                    )

                    run_query(
                        """
                        UPDATE
                            reklet.object_items oi

                        SET
                            qty_shipped =
                                qty_shipped + %s

                        FROM
                            reklet.finished_goods fg

                        WHERE

                            fg.id = %s

                            AND oi.id =
                                fg.object_item_id
                        """,
                        (
                            qty,
                            fg_id
                        )
                    )

                else:

                    run_query(
                        """
                        UPDATE
                            reklet.finished_goods

                        SET

                            quantity =
                                quantity - %s,

                            status =

                                CASE

                                    WHEN
                                        quantity - %s <= 0

                                    THEN 'arrived'

                                    ELSE 'shipped'

                                END

                        WHERE id = %s
                        """,
                        (
                            qty,
                            qty,
                            fg_id
                        )
                    )

                    run_query(
                        """
                        UPDATE
                            reklet.object_items oi

                        SET
                            qty_arrived =
                                qty_arrived + %s

                        FROM
                            reklet.finished_goods fg

                        WHERE

                            fg.id = %s

                            AND oi.id =
                                fg.object_item_id
                        """,
                        (
                            qty,
                            fg_id
                        )
                    )

                run_query(
                    """
                    INSERT INTO
                        reklet.finished_goods_transactions
                    (
                        finished_goods_id,
                        object_item_id,
                        object_id,
                        operation_type,
                        quantity
                    )

                    SELECT

                        fg.id,

                        fg.object_item_id,

                        fg.object_id,

                        %s,

                        %s

                    FROM
                        reklet.finished_goods fg

                    WHERE fg.id = %s
                    """,
                    (
                        action,
                        qty,
                        fg_id
                    )
                )

                st.success(
                    "Обновлено."
                )

                st.rerun()


# ============================================================
# TRANSPORT & LOGISTICS
# ============================================================

elif menu == "Транспорт и логистика":

    st.header(
        "Транспорт и логистика"
    )

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
            "Нет данных по логистике."
        )

    else:

        transport_view = df.copy()
        st.dataframe(
            transport_view,
            width="stretch",
            hide_index=True
        )

        st.markdown("---")

        st.subheader(
            "Данные отгрузки объекта"
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

        detail_view = detail.copy()
        st.dataframe(
            detail_view,
            width="stretch",
            hide_index=True
        )


# ============================================================
# INSTALLATION
# ============================================================

elif menu == "Монтаж":

    st.header(
        "Монтаж"
    )

    df = run_query(
        """
        SELECT

            o.id,

            o.object_name,

            c.name AS client_name,

            COALESCE(
                SUM(oi.quantity_needed),
                0
            ) AS required,

            COALESCE(
                SUM(oi.qty_arrived),
                0
            ) AS arrived,

            COALESCE(
                SUM(oi.qty_installing),
                0
            ) AS installing,

            COALESCE(
                SUM(oi.qty_installed),
                0
            ) AS installed,

            COALESCE(
                SUM(oi.quantity_needed)
                -
                SUM(oi.qty_installed),
                0
            ) AS remaining

        FROM reklet.objects o

        LEFT JOIN reklet.clients c
            ON c.id = o.client_id

        LEFT JOIN reklet.object_items oi
            ON oi.object_id = o.id

        GROUP BY

            o.id,
            o.object_name,
            c.name

        ORDER BY
            o.object_name
        """,
        fetch=True
    )

    if df.empty:

        st.info(
            "Нет данных по монтажу."
        )

    else:

        installation_view = df.copy()
        st.dataframe(
            installation_view,
            width="stretch",
            hide_index=True
        )

        st.markdown("---")

        st.subheader(
            "Действие монтажа"
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

        items = get_object_items(
            object_id
        )

        if not items.empty:

            item_map = {

                f"{row['id']} — "
                f"{row['item_name']}":
                    int(row["id"])

                for _, row in items.iterrows()
            }

            item_label = st.selectbox(
                "Изделие",
                list(item_map.keys())
            )

            item_id = item_map[
                item_label
            ]

            item_row = items[
                items["id"] == item_id
            ].iloc[0]

            st.write(
                f"Доставлено: "
                f"{safe_int(item_row['qty_arrived'])}"
            )

            st.write(
                f"В монтаже: "
                f"{safe_int(item_row['qty_installing'])}"
            )

            st.write(
                f"Смонтировано: "
                f"{safe_int(item_row['qty_installed'])}"
            )

            action = st.radio(
                "Действие",
                [
                    "Начать монтаж",
                    "Завершить монтаж"
                ],
                horizontal=True
            )

            if action == "Начать монтаж":

                available = safe_int(
                    item_row["qty_arrived"]
                )

            else:

                available = safe_int(
                    item_row["qty_installing"]
                )

            qty = st.number_input(
                "Количество",
                min_value=1,
                max_value=(
                    available
                    if available > 0
                    else 1
                ),
                value=1
            )

            if st.button(
                "Выполнить действие монтажа"
            ):

                if action == "Начать монтаж":

                    run_query(
                        """
                        UPDATE
                            reklet.object_items

                        SET

                            qty_arrived =
                                qty_arrived - %s,

                            qty_installing =
                                qty_installing + %s,

                            installation_status =
                                'in_progress'

                        WHERE id = %s
                        """,
                        (
                            qty,
                            qty,
                            item_id
                        )
                    )

                else:

                    run_query(
                        """
                        UPDATE
                            reklet.object_items

                        SET

                            qty_installing =
                                qty_installing - %s,

                            qty_installed =
                                qty_installed + %s,

                            installation_status =

                                CASE

                                    WHEN

                                        qty_installing - %s <= 0

                                        AND

                                        qty_arrived <= 0

                                    THEN 'completed'

                                    ELSE 'in_progress'

                                END,

                            installation_progress_pct =

                                CASE

                                    WHEN quantity_needed > 0

                                    THEN LEAST(
                                        100,
                                        ROUND(
                                            (
                                                qty_installed
                                                + %s
                                            )::numeric
                                            /
                                            quantity_needed
                                            * 100
                                        )
                                    )

                                    ELSE 0

                                END

                        WHERE id = %s
                        """,
                        (
                            qty,
                            qty,
                            qty,
                            qty,
                            item_id
                        )
                    )

                st.success(
                    "Монтаж обновлён."
                )

                st.rerun()


# ============================================================
# PAYROLL
# ============================================================

elif menu == "Зарплата":

    st.header(
        "Зарплата"
    )

    df = run_query(
        """
        SELECT

            pr.id,

            o.object_name,

            oi.item_name,

            pr.department,

            pr.base_material_cost,

            pr.calculated_amount,

            pr.manual_override_amount,

            pr.is_manual,

            pr.updated_at

        FROM
            reklet.payroll_records pr

        LEFT JOIN reklet.object_items oi
            ON oi.id = pr.object_item_id

        LEFT JOIN reklet.objects o
            ON o.id = oi.object_id

        ORDER BY
            pr.updated_at DESC
        """,
        fetch=True
    )

    if df.empty:

        st.info(
            "Нет записей по зарплате."
        )

    else:

        st.dataframe(
            df,
            width="stretch",
            hide_index=True
        )


# ============================================================
# REPORTS
# ============================================================

elif menu == "Отчёты":

    st.header(
        "Отчёты"
    )


    # ========================================================
    # KPI
    # ========================================================

    clients_count = run_query(
        """
        SELECT COUNT(*)
        FROM reklet.clients
        """,
        fetch=True
    ).iloc[0, 0]

    objects_count = run_query(
        """
        SELECT COUNT(*)
        FROM reklet.objects
        """,
        fetch=True
    ).iloc[0, 0]

    products_count = run_query(
        """
        SELECT COUNT(*)
        FROM reklet.product_templates
        """,
        fetch=True
    ).iloc[0, 0]

    materials_count = run_query(
        """
        SELECT COUNT(*)
        FROM reklet.materials
        """,
        fetch=True
    ).iloc[0, 0]


    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Клиенты",
        clients_count
    )

    c2.metric(
        "Объекты",
        objects_count
    )

    c3.metric(
        "Изделия",
        products_count
    )

    c4.metric(
        "Материалы",
        materials_count
    )


    st.markdown("---")


    # ========================================================
    # PRODUCTION REPORT
    # ========================================================

    st.subheader(
        "Производство по объектам"
    )

    production_report = run_query(
        """
        SELECT

            o.object_name,

            c.name AS client_name,

            SUM(
                oi.quantity_needed
            ) AS ordered,

            SUM(
                oi.qty_new
            ) AS new,

            SUM(
                oi.qty_production
            ) AS in_production,

            SUM(
                oi.qty_ready
            ) AS ready,

            SUM(
                oi.qty_shipped
            ) AS shipped,

            SUM(
                oi.qty_arrived
            ) AS arrived,

            SUM(
                oi.qty_installing
            ) AS installing,

            SUM(
                oi.qty_installed
            ) AS installed

        FROM
            reklet.object_items oi

        JOIN reklet.objects o
            ON o.id = oi.object_id

        LEFT JOIN reklet.clients c
            ON c.id = o.client_id

        GROUP BY

            o.object_name,
            c.name

        ORDER BY
            o.object_name
        """,
        fetch=True
    )

    if not production_report.empty:

        production_report_view = production_report.copy()
        st.dataframe(
            production_report_view,
            width="stretch",
            hide_index=True
        )


    # ========================================================
    # STOCK REPORT
    # ========================================================

    st.markdown("---")

    st.subheader(
        "Остатки на складе"
    )

    stock_report = run_query(
        """
        SELECT

            m.name AS material,

            u.name AS unit,

            m.stock_quantity,

            m.cost_per_unit,

            (
                m.stock_quantity
                *
                m.cost_per_unit
            ) AS stock_value

        FROM
            reklet.materials m

        LEFT JOIN reklet.units u
            ON u.id = m.unit_id

        ORDER BY
            m.name
        """,
        fetch=True
    )

    if not stock_report.empty:

        stock_report_view = stock_report.copy()
        st.dataframe(
            stock_report_view,
            width="stretch",
            hide_index=True
        )
