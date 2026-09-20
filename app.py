import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="Reklet — Production Management",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# DATABASE CONNECTION
# ============================================================

DB_HOST = "aws-0-us-west-2.pooler.supabase.com"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "postgres.lnkaohubtchmsiniepoc"
DB_PASSWORD = "4$#J9aXBHumnr$u"


@st.cache_resource
def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
    )


def run_query(query, params=None, fetch=False):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(query, params)

        if fetch:
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return pd.DataFrame(rows, columns=columns)

        conn.commit()
        return None

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()


# ============================================================
# HELPERS
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


def get_clients():
    return run_query(
        """
        SELECT id, name, contact_info, created_at
        FROM reklet.clients
        ORDER BY id
        """,
        fetch=True,
    )


def get_objects():
    return run_query(
        """
        SELECT
            o.id,
            o.client_id,
            c.name AS client_name,
            o.object_name,
            o.address,
            o.phone,
            o.contact_person,
            o.notes,
            o.transport_distance_km,
            o.delivery_cost,
            o.contract_date,
            o.production_start_date,
            o.production_end_date,
            o.installation_date,
            o.installation_end_date,
            o.created_at
        FROM reklet.objects o
        LEFT JOIN reklet.clients c ON c.id = o.client_id
        ORDER BY o.id
        """,
        fetch=True,
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
        ORDER BY id
        """,
        fetch=True,
    )


def get_materials():
    return run_query(
        """
        SELECT
            m.id,
            m.name,
            m.supplier_id,
            s.name AS supplier_name,
            m.unit_id,
            u.name AS unit_name,
            m.default_waste_coefficient,
            m.cost_per_unit,
            m.stock_quantity
        FROM reklet.materials m
        LEFT JOIN reklet.suppliers s ON s.id = m.supplier_id
        LEFT JOIN reklet.units u ON u.id = m.unit_id
        ORDER BY m.id
        """,
        fetch=True,
    )


def get_suppliers():
    return run_query(
        """
        SELECT
            id,
            name,
            type,
            contact_person,
            phone,
            email,
            category,
            conditions,
            contact_info,
            created_at
        FROM reklet.suppliers
        ORDER BY id
        """,
        fetch=True,
    )


# ============================================================
# AUTHENTICATION
# ============================================================

if "authentication_status" not in st.session_state:
    st.session_state.authentication_status = None

if not st.session_state.authentication_status:

    st.title("Reklet")
    st.subheader("Production Management")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        login = st.form_submit_button(
            "Login",
            use_container_width=True,
        )

        if login:
            if username == "admin" and password == "qwert12345":
                st.session_state.authentication_status = True
                st.session_state.username = "admin"
                st.session_state.name = "Administrator"
                st.rerun()
            else:
                st.session_state.authentication_status = False
                st.error("Неверное имя пользователя или пароль")

    st.stop()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("REKLET")

st.sidebar.write(
    f"Пользователь: **{st.session_state.get('name', 'Administrator')}**"
)

if st.sidebar.button("Выйти", use_container_width=True):
    st.session_state.authentication_status = None
    st.session_state.username = None
    st.session_state.name = None
    st.rerun()


# ============================================================
# MAIN MENU
# ============================================================

menu = st.radio(
    "Navigation",
    [
        "Clients",
        "Objects",
        "Product Templates",
        "Materials Warehouse",
        "Suppliers",
        "Production",
        "Transport",
        "Installation",
        "Payroll Calculation",
        "Reports",
    ],
    horizontal=True,
    label_visibility="collapsed",
)

st.markdown("---")


# ============================================================
# 1. CLIENTS
# ============================================================

if menu == "Clients":

    st.header("Clients")

    try:
        df = get_clients()

        if not df.empty:

            display_df = df.copy()

            display_df["created_at"] = pd.to_datetime(
                display_df["created_at"]
            ).dt.strftime("%Y-%m-%d %H:%M")

            edited = st.data_editor(
                display_df[
                    ["id", "name", "contact_info"]
                ],
                use_container_width=True,
                hide_index=True,
                disabled=["id"],
                num_rows="fixed",
                key="clients_editor",
            )

            if st.button(
                "Save Client Changes",
                key="save_clients",
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
                            safe_int(row["id"]),
                        ),
                    )

                st.success("Clients updated.")
                st.rerun()

        else:
            st.info("Clients table is empty.")

    except Exception as e:
        st.error(f"Ошибка загрузки клиентов: {e}")

    st.markdown("---")
    st.subheader("Add Client")

    with st.form("add_client_form"):

        client_name = st.text_input("Company / Client Name")

        client_contact = st.text_area(
            "Contact information"
        )

        submit = st.form_submit_button(
            "Add Client",
            use_container_width=True,
        )

        if submit:

            if not client_name.strip():
                st.warning("Введите название клиента.")

            else:

                try:
                    run_query(
                        """
                        INSERT INTO reklet.clients
                        (name, contact_info)
                        VALUES (%s, %s)
                        """,
                        (
                            client_name.strip(),
                            client_contact,
                        ),
                    )

                    st.success("Client added.")
                    st.rerun()

                except Exception as e:
                    st.error(f"Ошибка: {e}")


# ============================================================
# 2. OBJECTS
# ============================================================

elif menu == "Objects":

    st.header("Objects")

    tabs = st.tabs(
        [
            "Objects List",
            "Object Content",
            "Material Requirements",
        ]
    )

    # --------------------------------------------------------
    # OBJECT LIST
    # --------------------------------------------------------

    with tabs[0]:

        try:

            clients = get_clients()
            objects = get_objects()

            if not objects.empty:

                editable = objects[
                    [
                        "id",
                        "client_name",
                        "object_name",
                        "address",
                        "phone",
                        "contact_person",
                        "notes",
                        "transport_distance_km",
                        "delivery_cost",
                        "contract_date",
                        "production_start_date",
                        "production_end_date",
                        "installation_date",
                        "installation_end_date",
                    ]
                ].copy()

                edited_objects = st.data_editor(
                    editable,
                    use_container_width=True,
                    hide_index=True,
                    disabled=[
                        "id",
                        "client_name",
                    ],
                    num_rows="fixed",
                    key="objects_editor",
                )

                if st.button(
                    "Save Object Changes",
                    key="save_objects",
                ):

                    for _, row in edited_objects.iterrows():

                        run_query(
                            """
                            UPDATE reklet.objects
                            SET
                                object_name = %s,
                                address = %s,
                                phone = %s,
                                contact_person = %s,
                                notes = %s,
                                transport_distance_km = %s,
                                delivery_cost = %s,
                                contract_date = %s,
                                production_start_date = %s,
                                production_end_date = %s,
                                installation_date = %s,
                                installation_end_date = %s
                            WHERE id = %s
                            """,
                            (
                                row["object_name"],
                                row["address"],
                                row["phone"],
                                row["contact_person"],
                                row["notes"],
                                row["transport_distance_km"],
                                row["delivery_cost"],
                                row["contract_date"]
                                if pd.notna(row["contract_date"])
                                else None,
                                row["production_start_date"]
                                if pd.notna(row["production_start_date"])
                                else None,
                                row["production_end_date"]
                                if pd.notna(row["production_end_date"])
                                else None,
                                row["installation_date"]
                                if pd.notna(row["installation_date"])
                                else None,
                                row["installation_end_date"]
                                if pd.notna(row["installation_end_date"])
                                else None,
                                safe_int(row["id"]),
                            ),
                        )

                    st.success("Objects updated.")
                    st.rerun()

            else:
                st.info("No objects yet.")

        except Exception as e:
            st.error(f"Ошибка загрузки объектов: {e}")

        st.markdown("---")
        st.subheader("Create New Object")

        try:
            clients = get_clients()
        except Exception as e:
            clients = pd.DataFrame()
            st.error(f"Ошибка загрузки клиентов: {e}")

        if clients.empty:

            st.warning(
                "Сначала создайте хотя бы одного клиента."
            )

        else:

            client_options = {
                f"{row['id']} — {row['name']}":
                int(row["id"])
                for _, row in clients.iterrows()
            }

            with st.form("create_object_form"):

                selected_client = st.selectbox(
                    "Client",
                    list(client_options.keys()),
                )

                client_id = client_options[selected_client]

                object_name = st.text_input(
                    "Object Name"
                )

                address = st.text_input(
                    "Address"
                )

                col1, col2 = st.columns(2)

                with col1:

                    phone = st.text_input(
                        "Phone"
                    )

                    contact_person = st.text_input(
                        "Contact Person"
                    )

                    distance = st.number_input(
                        "Transport Distance, km",
                        min_value=0.0,
                        value=0.0,
                    )

                with col2:

                    delivery_cost = st.number_input(
                        "Delivery Cost",
                        min_value=0.0,
                        value=0.0,
                    )

                    notes = st.text_area(
                        "Notes"
                    )

                st.markdown("#### Project Dates")

                d1, d2 = st.columns(2)

                with d1:

                    contract_date = st.date_input(
                        "Contract Date",
                        value=None,
                    )

                    production_start = st.date_input(
                        "Production Start",
                        value=None,
                    )

                    production_end = st.date_input(
                        "Production End",
                        value=None,
                    )

                with d2:

                    installation_date = st.date_input(
                        "Installation Date",
                        value=None,
                    )

                    installation_end = st.date_input(
                        "Installation End",
                        value=None,
                    )

                create = st.form_submit_button(
                    "Create Object",
                    use_container_width=True,
                )

                if create:

                    if not object_name.strip():

                        st.warning(
                            "Введите название объекта."
                        )

                    else:

                        try:

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
                                    %s,%s,%s,%s,%s,%s,%s,
                                    %s,%s,%s,%s,%s,%s
                                )
                                """,
                                (
                                    client_id,
                                    object_name.strip(),
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
                                    installation_end,
                                ),
                            )

                            st.success(
                                "Object created."
                            )

                            st.rerun()

                        except Exception as e:
                            st.error(
                                f"Ошибка создания объекта: {e}"
                            )

    # --------------------------------------------------------
    # OBJECT CONTENT
    # --------------------------------------------------------

    with tabs[1]:

        st.subheader("Object Content")

        try:
            objects = get_objects()
        except Exception as e:
            objects = pd.DataFrame()
            st.error(f"Ошибка: {e}")

        if objects.empty:

            st.info(
                "Сначала создайте объект."
            )

        else:

            object_options = {
                f"#{row['id']} — {row['object_name']} "
                f"({row['client_name'] or 'No client'})":
                int(row["id"])
                for _, row in objects.iterrows()
            }

            selected_object_label = st.selectbox(
                "Select Object",
                list(object_options.keys()),
                key="content_object_select",
            )

            object_id = object_options[
                selected_object_label
            ]

            selected_object = objects[
                objects["id"] == object_id
            ].iloc[0]

            st.markdown(
                f"### {selected_object['object_name']}"
            )

            st.write(
                f"**Client:** "
                f"{selected_object['client_name'] or '-'}"
            )

            st.write(
                f"**Address:** "
                f"{selected_object['address'] or '-'}"
            )

            # ------------------------------------------------
            # ITEMS
            # ------------------------------------------------

            st.markdown("---")
            st.subheader("Items")

            try:

                items = run_query(
                    """
                    SELECT
                        id,
                        item_name,
                        quantity,
                        quantity_needed,
                        qty_new,
                        qty_production,
                        qty_ready,
                        qty_shipped,
                        qty_arrived,
                        qty_installing,
                        qty_installed,
                        production_status,
                        production_progress_pct,
                        installation_status,
                        installation_progress_pct,
                        template_id
                    FROM reklet.object_items
                    WHERE object_id = %s
                    ORDER BY id
                    """,
                    (object_id,),
                    fetch=True,
                )

                if not items.empty:

                    editable_items = items[
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
                            "qty_installed",
                            "production_status",
                            "production_progress_pct",
                            "installation_status",
                            "installation_progress_pct",
                        ]
                    ].copy()

                    edited_items = st.data_editor(
                        editable_items,
                        use_container_width=True,
                        hide_index=True,
                        disabled=[
                            "id",
                            "item_name",
                            "quantity",
                        ],
                        key=f"items_editor_{object_id}",
                    )

                    if st.button(
                        "Save Item Progress",
                        key=f"save_items_{object_id}",
                    ):

                        for _, row in edited_items.iterrows():

                            total = (
                                safe_int(row["qty_new"])
                                + safe_int(row["qty_production"])
                                + safe_int(row["qty_ready"])
                                + safe_int(row["qty_shipped"])
                                + safe_int(row["qty_arrived"])
                                + safe_int(row["qty_installing"])
                                + safe_int(row["qty_installed"])
                            )

                            run_query(
                                """
                                UPDATE reklet.object_items
                                SET
                                    qty_new = %s,
                                    qty_production = %s,
                                    qty_ready = %s,
                                    qty_shipped = %s,
                                    qty_arrived = %s,
                                    qty_installing = %s,
                                    qty_installed = %s,
                                    production_status = %s,
                                    production_progress_pct = %s,
                                    installation_status = %s,
                                    installation_progress_pct = %s,
                                    quantity = %s,
                                    quantity_needed = %s
                                WHERE id = %s
                                """,
                                (
                                    safe_int(row["qty_new"]),
                                    safe_int(row["qty_production"]),
                                    safe_int(row["qty_ready"]),
                                    safe_int(row["qty_shipped"]),
                                    safe_int(row["qty_arrived"]),
                                    safe_int(row["qty_installing"]),
                                    safe_int(row["qty_installed"]),
                                    row["production_status"],
                                    safe_int(
                                        row["production_progress_pct"]
                                    ),
                                    row["installation_status"],
                                    safe_int(
                                        row["installation_progress_pct"]
                                    ),
                                    total,
                                    total,
                                    safe_int(row["id"]),
                                ),
                            )

                        st.success(
                            "Item progress saved."
                        )

                        st.rerun()

                else:

                    st.info(
                        "В этом объекте пока нет изделий."
                    )

            except Exception as e:
                st.error(
                    f"Ошибка загрузки изделий: {e}"
                )

            # ------------------------------------------------
            # ADD ITEM
            # ------------------------------------------------

            st.markdown("---")
            st.subheader("Add Product")

            try:

                templates = get_templates()

                if templates.empty:

                    st.warning(
                        "Нет Product Templates."
                    )

                else:

                    current_client = selected_object[
                        "client_name"
                    ]

                    filtered = templates[
                        (templates["client_name"].isna())
                        | (templates["client_name"] == "")
                        | (
                            templates["client_name"]
                            == current_client
                        )
                    ]

                    if filtered.empty:
                        filtered = templates

                    template_options = {
                        f"{row['id']} — {row['name']}":
                        int(row["id"])
                        for _, row in filtered.iterrows()
                    }

                    with st.form(
                        f"add_item_{object_id}"
                    ):

                        selected_template = st.selectbox(
                            "Product Template",
                            list(template_options.keys()),
                        )

                        selected_template_id = (
                            template_options[
                                selected_template
                            ]
                        )

                        quantity = st.number_input(
                            "Quantity",
                            min_value=1,
                            value=1,
                            step=1,
                        )

                        add_item = st.form_submit_button(
                            "Add Product to Object",
                            use_container_width=True,
                        )

                        if add_item:

                            template_row = templates[
                                templates["id"]
                                == selected_template_id
                            ].iloc[0]

                            try:

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
                                        status,
                                        qty_new
                                    )
                                    VALUES
                                    (%s,%s,%s,%s,%s,%s,%s,%s)
                                    """,
                                    (
                                        object_id,
                                        selected_template_id,
                                        selected_template_id,
                                        quantity,
                                        template_row["name"],
                                        quantity,
                                        "New",
                                        quantity,
                                    ),
                                )

                                st.success(
                                    "Product added."
                                )

                                st.rerun()

                            except Exception as e:
                                st.error(
                                    f"Ошибка добавления изделия: {e}"
                                )

            except Exception as e:
                st.error(
                    f"Ошибка загрузки шаблонов: {e}"
                )

            # ------------------------------------------------
            # DELETE ITEM
            # ------------------------------------------------

            st.markdown("---")
            st.subheader("Delete Product")

            try:

                delete_items = run_query(
                    """
                    SELECT id, item_name
                    FROM reklet.object_items
                    WHERE object_id = %s
                    ORDER BY id
                    """,
                    (object_id,),
                    fetch=True,
                )

                if not delete_items.empty:

                    delete_options = {
                        f"{row['id']} — {row['item_name']}":
                        int(row["id"])
                        for _, row in delete_items.iterrows()
                    }

                    item_to_delete = st.selectbox(
                        "Product",
                        list(delete_options.keys()),
                        key=f"delete_select_{object_id}",
                    )

                    if st.button(
                        "Delete Selected Product",
                        key=f"delete_button_{object_id}",
                    ):

                        delete_id = delete_options[
                            item_to_delete
                        ]

                        run_query(
                            """
                            DELETE FROM reklet.object_items
                            WHERE id = %s
                            """,
                            (delete_id,),
                        )

                        st.success(
                            "Product deleted."
                        )

                        st.rerun()

            except Exception as e:
                st.error(
                    f"Ошибка удаления: {e}"
                )

            # ------------------------------------------------
            # PRINT
            # ------------------------------------------------

            st.markdown("---")
            st.subheader("Specification")

            try:

                print_items = run_query(
                    """
                    SELECT
                        item_name,
                        quantity
                    FROM reklet.object_items
                    WHERE object_id = %s
                    ORDER BY id
                    """,
                    (object_id,),
                    fetch=True,
                )

                html_rows = ""

                if not print_items.empty:

                    for index, row in print_items.iterrows():

                        html_rows += f"""
                        <tr>
                            <td>{index + 1}</td>
                            <td>{row['item_name']}</td>
                            <td>{row['quantity']}</td>
                        </tr>
                        """

                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">

                    <title>
                        Specification
                    </title>

                    <style>

                    body {{
                        font-family: Arial;
                        margin: 40px;
                    }}

                    h1 {{
                        margin-bottom: 5px;
                    }}

                    table {{
                        width: 100%;
                        border-collapse: collapse;
                        margin-top: 25px;
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

                    <h1>
                        Спецификация заказа
                    </h1>

                    <p>
                        <b>Заказчик:</b>
                        {selected_object['client_name'] or '-'}
                    </p>

                    <p>
                        <b>Объект:</b>
                        {selected_object['object_name']}
                    </p>

                    <p>
                        <b>Адрес:</b>
                        {selected_object['address'] or '-'}
                    </p>

                    <table>

                        <thead>
                            <tr>
                                <th>№</th>
                                <th>Изделие</th>
                                <th>Количество</th>
                            </tr>
                        </thead>

                        <tbody>

                            {html_rows}

                        </tbody>

                    </table>

                    <script>
                        window.onload = function() {{
                            window.print();
                        }};
                    </script>

                </body>
                </html>
                """

                st.download_button(
                    "📥 Скачать спецификацию HTML",
                    data=html,
                    file_name=(
                        f"specification_"
                        f"{selected_object['object_name']}.html"
                    ),
                    mime="text/html",
                    key=f"download_{object_id}",
                )

            except Exception as e:
                st.error(
                    f"Ошибка подготовки спецификации: {e}"
                )

    # --------------------------------------------------------
    # MATERIAL REQUIREMENTS
    # --------------------------------------------------------

    with tabs[2]:

        st.subheader(
            "Material Requirements Calculation"
        )

        st.info(
            "Здесь рассчитываются материалы на основании "
            "состава Product Template."
        )

        try:

            objects = get_objects()

            if objects.empty:

                st.info("Нет объектов.")

            else:

                object_options = {
                    f"{row['id']} — {row['object_name']}":
                    int(row["id"])
                    for _, row in objects.iterrows()
                }

                selected_object = st.selectbox(
                    "Object",
                    list(object_options.keys()),
                    key="material_object",
                )

                selected_object_id = object_options[
                    selected_object
                ]

                items = run_query(
                    """
                    SELECT
                        oi.id,
                        oi.item_name,
                        oi.quantity,
                        COALESCE(
                            oi.product_template_id,
                            oi.template_id
                        ) AS template_id,
                        pt.name AS template_name
                    FROM reklet.object_items oi
                    LEFT JOIN reklet.product_templates pt
                        ON pt.id = COALESCE(
                            oi.product_template_id,
                            oi.template_id
                        )
                    WHERE oi.object_id = %s
                    ORDER BY oi.id
                    """,
                    (selected_object_id,),
                    fetch=True,
                )

                if items.empty:

                    st.info(
                        "В объекте нет изделий."
                    )

                else:

                    result_rows = []

                    for _, item in items.iterrows():

                        template_id = item["template_id"]

                        if pd.isna(template_id):
                            continue

                        materials = run_query(
                            """
                            SELECT
                                m.name AS material_name,
                                u.name AS unit_name,
                                ptm.quantity_per_unit,
                                ptm.waste_coefficient,
                                m.cost_per_unit
                            FROM reklet.product_template_materials ptm
                            JOIN reklet.materials m
                                ON m.id = ptm.material_id
                            LEFT JOIN reklet.units u
                                ON u.id = m.unit_id
                            WHERE ptm.product_template_id = %s
                            ORDER BY m.name
                            """,
                            (int(template_id),),
                            fetch=True,
                        )

                        for _, material in materials.iterrows():

                            qty_per_unit = safe_float(
                                material[
                                    "quantity_per_unit"
                                ]
                            )

                            waste = safe_float(
                                material[
                                    "waste_coefficient"
                                ],
                                1.0,
                            )

                            if waste <= 0:
                                waste = 1.0

                            product_qty = safe_int(
                                item["quantity"]
                            )

                            required = (
                                qty_per_unit
                                * product_qty
                                * waste
                            )

                            cost = (
                                required
                                * safe_float(
                                    material[
                                        "cost_per_unit"
                                    ]
                                )
                            )

                            result_rows.append(
                                {
                                    "Product":
                                        item["item_name"],
                                    "Material":
                                        material[
                                            "material_name"
                                        ],
                                    "Unit":
                                        material[
                                            "unit_name"
                                        ],
                                    "Product Qty":
                                        product_qty,
                                    "Qty / Product":
                                        qty_per_unit,
                                    "Waste Coefficient":
                                        waste,
                                    "Required Qty":
                                        required,
                                    "Unit Cost":
                                        safe_float(
                                            material[
                                                "cost_per_unit"
                                            ]
                                        ),
                                    "Estimated Cost":
                                        cost,
                                }
                            )

                    if result_rows:

                        result_df = pd.DataFrame(
                            result_rows
                        )

                        st.dataframe(
                            result_df,
                            use_container_width=True,
                            hide_index=True,
                        )

                        st.metric(
                            "Total Material Cost",
                            f"{result_df['Estimated Cost'].sum():,.2f}",
                        )

                    else:

                        st.info(
                            "Для изделий этого объекта "
                            "не задан состав материалов."
                        )

        except Exception as e:
            st.error(
                f"Ошибка расчёта материалов: {e}"
            )


# ============================================================
# 3. PRODUCT TEMPLATES
# ============================================================

elif menu == "Product Templates":

    st.header("Product Templates")

    try:

        templates = get_templates()

        if not templates.empty:

            edited = st.data_editor(
                templates,
                use_container_width=True,
                hide_index=True,
                disabled=["id"],
                key="templates_editor",
            )

            if st.button(
                "Save Template Changes"
            ):

                for _, row in edited.iterrows():

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
                            row["name"],
                            row["type"],
                            row["client_name"],
                            row["category"],
                            safe_int(row["id"]),
                        ),
                    )

                st.success(
                    "Templates updated."
                )

                st.rerun()

        else:

            st.info(
                "Product Templates table is empty."
            )

    except Exception as e:
        st.error(
            f"Ошибка: {e}"
        )


# ============================================================
# 4. MATERIALS
# ============================================================

elif menu == "Materials Warehouse":

    st.header("Materials Warehouse")

    try:

        materials = get_materials()

        if materials.empty:

            st.info(
                "Materials table is empty."
            )

        else:

            st.dataframe(
                materials,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error(
            f"Ошибка загрузки материалов: {e}"
        )


# ============================================================
# 5. SUPPLIERS
# ============================================================

elif menu == "Suppliers":

    st.header("Suppliers")

    try:

        suppliers = get_suppliers()

        if suppliers.empty:

            st.info(
                "Suppliers table is empty."
            )

        else:

            st.dataframe(
                suppliers,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error(
            f"Ошибка загрузки поставщиков: {e}"
        )


# ============================================================
# 6. PRODUCTION
# ============================================================

elif menu == "Production":

    st.header("Production")

    try:

        production = run_query(
            """
            SELECT
                oi.id,
                oi.item_name,
                o.object_name,
                c.name AS client_name,
                oi.quantity,
                oi.qty_new,
                oi.qty_production,
                oi.qty_ready,
                oi.production_status,
                oi.production_progress_pct
            FROM reklet.object_items oi
            JOIN reklet.objects o
                ON o.id = oi.object_id
            LEFT JOIN reklet.clients c
                ON c.id = o.client_id
            ORDER BY oi.id
            """,
            fetch=True,
        )

        if production.empty:

            st.info(
                "Нет изделий в производстве."
            )

        else:

            st.dataframe(
                production,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error(
            f"Ошибка Production: {e}"
        )


# ============================================================
# 7. TRANSPORT
# ============================================================

elif menu == "Transport":

    st.header("Transport & Logistics")

    try:

        transport = run_query(
            """
            SELECT
                o.id,
                o.object_name,
                c.name AS client_name,
                o.address,
                o.transport_distance_km,
                o.delivery_cost
            FROM reklet.objects o
            LEFT JOIN reklet.clients c
                ON c.id = o.client_id
            ORDER BY o.id
            """,
            fetch=True,
        )

        if transport.empty:

            st.info(
                "Нет транспортных данных."
            )

        else:

            st.dataframe(
                transport,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error(
            f"Ошибка Transport: {e}"
        )


# ============================================================
# 8. INSTALLATION
# ============================================================

elif menu == "Installation":

    st.header("Installation")

    try:

        installation = run_query(
            """
            SELECT
                o.id,
                o.object_name,
                c.name AS client_name,
                o.address,
                o.installation_date,
                o.installation_end_date
            FROM reklet.objects o
            LEFT JOIN reklet.clients c
                ON c.id = o.client_id
            ORDER BY o.installation_date NULLS LAST, o.id
            """,
            fetch=True,
        )

        if installation.empty:

            st.info(
                "Нет данных по монтажу."
            )

        else:

            st.dataframe(
                installation,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error(
            f"Ошибка Installation: {e}"
        )


# ============================================================
# 9. PAYROLL
# ============================================================

elif menu == "Payroll Calculation":

    st.header("Payroll Calculation")

    try:

        payroll = run_query(
            """
            SELECT
                pr.id,
                pr.object_item_id,
                oi.item_name,
                o.object_name,
                pr.department,
                pr.base_material_cost,
                pr.calculated_amount,
                pr.manual_override_amount,
                pr.is_manual,
                pr.updated_at
            FROM reklet.payroll_records pr
            LEFT JOIN reklet.object_items oi
                ON oi.id = pr.object_item_id
            LEFT JOIN reklet.objects o
                ON o.id = oi.object_id
            ORDER BY pr.id
            """,
            fetch=True,
        )

        if payroll.empty:

            st.info(
                "Payroll records пока отсутствуют."
            )

        else:

            st.dataframe(
                payroll,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error(
            f"Ошибка Payroll: {e}"
        )

    st.markdown("---")

    st.info(
        "Автоматический расчёт зарплаты будет "
        "добавлен следующим этапом."
    )


# ============================================================
# 10. REPORTS
# ============================================================

elif menu == "Reports":

    st.header("Reports & Analytics")

    try:

        clients_count = run_query(
            """
            SELECT COUNT(*)
            FROM reklet.clients
            """,
            fetch=True,
        ).iloc[0, 0]

        objects_count = run_query(
            """
            SELECT COUNT(*)
            FROM reklet.objects
            """,
            fetch=True,
        ).iloc[0, 0]

        templates_count = run_query(
            """
            SELECT COUNT(*)
            FROM reklet.product_templates
            """,
            fetch=True,
        ).iloc[0, 0]

        materials_count = run_query(
            """
            SELECT COUNT(*)
            FROM reklet.materials
            """,
            fetch=True,
        ).iloc[0, 0]

        items_count = run_query(
            """
            SELECT COUNT(*)
            FROM reklet.object_items
            """,
            fetch=True,
        ).iloc[0, 0]

        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric(
                "Clients",
                int(clients_count),
            )

        with col2:
            st.metric(
                "Objects",
                int(objects_count),
            )

        with col3:
            st.metric(
                "Templates",
                int(templates_count),
            )

        with col4:
            st.metric(
                "Materials",
                int(materials_count),
            )

        with col5:
            st.metric(
                "Object Items",
                int(items_count),
            )

        st.markdown("---")

        st.subheader(
            "Object Production Status"
        )

        status_report = run_query(
            """
            SELECT
                production_status,
                COUNT(*) AS items_count
            FROM reklet.object_items
            GROUP BY production_status
            ORDER BY production_status
            """,
            fetch=True,
        )

        if not status_report.empty:

            st.dataframe(
                status_report,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error(
            f"Ошибка формирования отчёта: {e}"
        )
