import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, date
from html import escape

# ============================================================
# REKLET — PRODUCTION MANAGEMENT
# Version: 2.0
# Works with current existing database structure
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
            if cursor.description is None:
                return pd.DataFrame()

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


def nullable_date(value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    return value


def money(value):
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "0.00"


def page_error(title, error):
    st.error(f"{title}: {error}")


# ============================================================
# AUTHENTICATION
# ============================================================

if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None


if not st.session_state["authentication_status"]:

    st.title("Reklet")
    st.subheader("Production Management")

    st.markdown("---")

    with st.form("login_form"):

        username_input = st.text_input("Username")

        password_input = st.text_input(
            "Password",
            type="password"
        )

        submit_login = st.form_submit_button(
            "Login",
            use_container_width=True
        )

        if submit_login:

            if (
                username_input == "admin"
                and password_input == "qwert12345"
            ):
                st.session_state["authentication_status"] = True
                st.session_state["username"] = "admin"
                st.session_state["name"] = "Administrator"

                st.rerun()

            else:

                st.session_state["authentication_status"] = False
                st.error("Неверное имя пользователя или пароль")

    st.stop()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("REKLET")

st.sidebar.caption(
    f"User: {st.session_state.get('name', 'Administrator')}"
)

if st.sidebar.button(
    "Выйти",
    use_container_width=True
):
    st.session_state["authentication_status"] = None
    st.rerun()


# ============================================================
# NAVIGATION
# ============================================================

menu_options = [
    "Clients",
    "Objects",
    "Product Templates",
    "Materials Warehouse",
    "Production",
    "Transport",
    "Installation",
    "Payroll Calculation",
    "Reports",
]

menu = st.sidebar.radio(
    "Navigation",
    menu_options
)

st.markdown(
    """
    <style>
    .main-title {
        font-size: 30px;
        font-weight: 700;
        margin-bottom: 5px;
    }

    .metric-card {
        background: #f7f7f7;
        border-radius: 10px;
        padding: 15px;
        border: 1px solid #e5e5e5;
    }

    .stage-box {
        border-radius: 8px;
        padding: 10px;
        background: #f7f7f7;
        border: 1px solid #ddd;
        text-align: center;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# CLIENTS
# ============================================================

if menu == "Clients":

    st.markdown(
        '<div class="main-title">Clients Management</div>',
        unsafe_allow_html=True
    )

    st.markdown("---")

    try:

        df_clients = run_query(
            """
            SELECT
                id,
                name,
                contact_info,
                created_at
            FROM reklet.clients
            ORDER BY id
            """,
            fetch=True
        )

        if not df_clients.empty:

            st.subheader("Clients")

            edited = st.data_editor(
                df_clients,
                use_container_width=True,
                hide_index=True,
                disabled=["id", "created_at"],
                num_rows="fixed",
                key="clients_editor"
            )

            if st.button(
                "Save Client Changes",
                key="save_clients",
                type="primary"
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

                st.success("Clients updated.")
                st.rerun()

        else:

            st.info("No clients found.")

    except Exception as e:

        page_error("Ошибка загрузки клиентов", e)

    st.markdown("---")

    st.subheader("Add New Client")

    with st.form("add_client_form"):

        c_name = st.text_input("Company / Client Name")

        c_contact = st.text_area(
            "Contact Information",
            placeholder="Phone, email, address..."
        )

        submit = st.form_submit_button(
            "Create Client",
            type="primary"
        )

        if submit:

            if not c_name.strip():

                st.warning("Введите имя клиента.")

            else:

                try:

                    run_query(
                        """
                        INSERT INTO reklet.clients
                        (name, contact_info)
                        VALUES (%s, %s)
                        """,
                        (
                            c_name.strip(),
                            c_contact.strip()
                        )
                    )

                    st.success("Client created.")
                    st.rerun()

                except Exception as e:

                    page_error("Ошибка создания клиента", e)


# ============================================================
# OBJECTS
# ============================================================

elif menu == "Objects":

    st.markdown(
        '<div class="main-title">Objects Management</div>',
        unsafe_allow_html=True
    )

    tabs = st.tabs([
        "Objects",
        "Object Items",
        "Material Requirements",
        "Specification"
    ])

    # --------------------------------------------------------
    # OBJECT LIST
    # --------------------------------------------------------

    with tabs[0]:

        try:

            df_objects = run_query(
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
                    o.installation_end_date
                FROM reklet.objects o
                LEFT JOIN reklet.clients c
                    ON c.id = o.client_id
                ORDER BY o.id
                """,
                fetch=True
            )

            if not df_objects.empty:

                display = df_objects.copy()

                st.subheader("Objects")

                st.dataframe(
                    display,
                    use_container_width=True,
                    hide_index=True
                )

            else:

                st.info("No objects found.")

        except Exception as e:

            page_error("Ошибка загрузки объектов", e)

        st.markdown("---")

        st.subheader("Create Object")

        try:

            clients_df = run_query(
                """
                SELECT id, name
                FROM reklet.clients
                ORDER BY name
                """,
                fetch=True
            )

        except Exception:

            clients_df = pd.DataFrame()

        if clients_df.empty:

            st.warning(
                "Сначала создайте хотя бы одного клиента."
            )

        else:

            client_options = {
                f"{row['name']} (ID {row['id']})":
                int(row["id"])
                for _, row in clients_df.iterrows()
            }

            with st.form("create_object_form"):

                selected_client_label = st.selectbox(
                    "Client",
                    list(client_options.keys())
                )

                selected_client_id = client_options[
                    selected_client_label
                ]

                object_name = st.text_input(
                    "Object Name"
                )

                address = st.text_input(
                    "Address"
                )

                col1, col2 = st.columns(2)

                with col1:

                    phone = st.text_input("Phone")

                    contact_person = st.text_input(
                        "Contact Person"
                    )

                    distance = st.number_input(
                        "Transport Distance (km)",
                        min_value=0.0,
                        value=0.0,
                        step=1.0
                    )

                with col2:

                    delivery_cost = st.number_input(
                        "Delivery Cost",
                        min_value=0.0,
                        value=0.0,
                        step=100.0
                    )

                    notes = st.text_area(
                        "Notes"
                    )

                st.markdown("### Schedule")

                d1, d2 = st.columns(2)

                with d1:

                    contract_date = st.date_input(
                        "Contract Date",
                        value=None
                    )

                    production_start = st.date_input(
                        "Production Start",
                        value=None
                    )

                    production_end = st.date_input(
                        "Production End",
                        value=None
                    )

                with d2:

                    installation_start = st.date_input(
                        "Installation Date",
                        value=None
                    )

                    installation_end = st.date_input(
                        "Installation End",
                        value=None
                    )

                submit_object = st.form_submit_button(
                    "Create Object",
                    type="primary"
                )

                if submit_object:

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
                                    transport_distance_km,
                                    delivery_cost,
                                    phone,
                                    contact_person,
                                    notes,
                                    contract_date,
                                    production_start_date,
                                    production_end_date,
                                    installation_date,
                                    installation_end_date
                                )
                                VALUES
                                (
                                    %s,%s,%s,%s,%s,%s,%s,%s,
                                    %s,%s,%s,%s,%s
                                )
                                """,
                                (
                                    selected_client_id,
                                    object_name.strip(),
                                    address.strip(),
                                    distance,
                                    delivery_cost,
                                    phone.strip(),
                                    contact_person.strip(),
                                    notes.strip(),
                                    nullable_date(contract_date),
                                    nullable_date(production_start),
                                    nullable_date(production_end),
                                    nullable_date(installation_start),
                                    nullable_date(installation_end)
                                )
                            )

                            st.success(
                                "Object created successfully."
                            )

                            st.rerun()

                        except Exception as e:

                            page_error(
                                "Ошибка создания объекта",
                                e
                            )

    # --------------------------------------------------------
    # OBJECT ITEMS
    # --------------------------------------------------------

    with tabs[1]:

        try:

            objects_df = run_query(
                """
                SELECT
                    o.id,
                    o.object_name,
                    c.name AS client_name
                FROM reklet.objects o
                LEFT JOIN reklet.clients c
                    ON c.id = o.client_id
                ORDER BY o.id
                """,
                fetch=True
            )

        except Exception:

            objects_df = pd.DataFrame()

        if objects_df.empty:

            st.info("Сначала создайте объект.")

        else:

            object_map = {
                f"{row['object_name']} — "
                f"{row['client_name'] or 'No client'} "
                f"(ID {row['id']})":
                int(row["id"])
                for _, row in objects_df.iterrows()
            }

            selected_object_label = st.selectbox(
                "Select Object",
                list(object_map.keys()),
                key="object_items_object"
            )

            object_id = object_map[
                selected_object_label
            ]

            st.markdown("---")

            # Existing items

            try:

                items_df = run_query(
                    """
                    SELECT
                        id,
                        item_name,
                        quantity,
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
                        installation_progress_pct
                    FROM reklet.object_items
                    WHERE object_id = %s
                    ORDER BY id
                    """,
                    (object_id,),
                    fetch=True
                )

            except Exception as e:

                items_df = pd.DataFrame()
                page_error(
                    "Ошибка загрузки изделий",
                    e
                )

            if not items_df.empty:

                st.subheader("Items")

                edited_items = st.data_editor(
                    items_df,
                    use_container_width=True,
                    hide_index=True,
                    disabled=[
                        "id",
                        "production_status",
                        "production_progress_pct",
                        "installation_status",
                        "installation_progress_pct"
                    ],
                    num_rows="fixed",
                    key=f"items_editor_{object_id}"
                )

                if st.button(
                    "Save Item Quantities",
                    type="primary",
                    key=f"save_items_{object_id}"
                ):

                    for _, row in edited_items.iterrows():

                        values = [
                            safe_int(row["qty_new"]),
                            safe_int(row["qty_production"]),
                            safe_int(row["qty_ready"]),
                            safe_int(row["qty_shipped"]),
                            safe_int(row["qty_arrived"]),
                            safe_int(row["qty_installing"]),
                            safe_int(row["qty_installed"]),
                        ]

                        total = sum(values)

                        quantity = safe_int(
                            row["quantity"],
                            total
                        )

                        if total > quantity:
                            st.error(
                                f"Item ID {row['id']}: "
                                f"stage quantities ({total}) "
                                f"exceed total quantity ({quantity})."
                            )
                            continue

                        production_done = (
                            values[0]
                            + values[1]
                            + values[2]
                            + values[3]
                            + values[4]
                            + values[5]
                            + values[6]
                        )

                        production_pct = 0

                        if quantity > 0:

                            production_pct = round(
                                (
                                    values[2]
                                    + values[3]
                                    + values[4]
                                    + values[5]
                                    + values[6]
                                )
                                / quantity
                                * 100
                            )

                        if values[6] >= quantity and quantity > 0:

                            installation_status = "completed"

                        elif values[5] > 0:

                            installation_status = "in_progress"

                        else:

                            installation_status = "not_started"

                        if values[2] + values[3] + values[4] + values[5] + values[6] >= quantity and quantity > 0:

                            production_status = "completed"

                        elif values[1] > 0:

                            production_status = "in_progress"

                        else:

                            production_status = "not_started"

                        installation_pct = (
                            round(
                                values[6]
                                / quantity
                                * 100
                            )
                            if quantity > 0
                            else 0
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
                                qty_installed = %s,
                                production_status = %s,
                                production_progress_pct = %s,
                                installation_status = %s,
                                installation_progress_pct = %s
                            WHERE id = %s
                            """,
                            (
                                row["item_name"],
                                quantity,
                                quantity,
                                values[0],
                                values[1],
                                values[2],
                                values[3],
                                values[4],
                                values[5],
                                values[6],
                                production_status,
                                min(production_pct, 100),
                                installation_status,
                                min(installation_pct, 100),
                                safe_int(row["id"])
                            )
                        )

                    st.success(
                        "Item quantities updated."
                    )

                    st.rerun()

            else:

                st.info(
                    "No items have been added to this object."
                )

            # Add item

            st.markdown("---")

            st.subheader("Add Product to Object")

            try:

                templates_df = run_query(
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

            except Exception:

                templates_df = pd.DataFrame()

            if templates_df.empty:

                st.warning(
                    "Нет Product Templates."
                )

            else:

                template_options = {
                    f"{row['name']} "
                    f"[{row['type']}] "
                    f"(ID {row['id']})":
                    int(row["id"])
                    for _, row in templates_df.iterrows()
                }

                with st.form(
                    f"add_item_form_{object_id}"
                ):

                    template_label = st.selectbox(
                        "Product Template",
                        list(template_options.keys())
                    )

                    template_id = template_options[
                        template_label
                    ]

                    quantity = st.number_input(
                        "Quantity",
                        min_value=1,
                        value=1,
                        step=1
                    )

                    custom_name = st.text_input(
                        "Item Name",
                        value=template_label.split(" [")[0]
                    )

                    submit_item = st.form_submit_button(
                        "Add Item",
                        type="primary"
                    )

                    if submit_item:

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
                                    qty_new,
                                    qty_production,
                                    qty_ready,
                                    qty_shipped,
                                    qty_arrived,
                                    qty_installing,
                                    qty_installed
                                )
                                VALUES
                                (
                                    %s,%s,%s,%s,%s,%s,'New',
                                    %s,0,0,0,0,0,0
                                )
                                """,
                                (
                                    object_id,
                                    template_id,
                                    template_id,
                                    quantity,
                                    custom_name.strip(),
                                    quantity,
                                    quantity
                                )
                            )

                            st.success(
                                "Item added to object."
                            )

                            st.rerun()

                        except Exception as e:

                            page_error(
                                "Ошибка добавления изделия",
                                e
                            )

            # Delete item

            if not items_df.empty:

                st.markdown("---")

                st.subheader("Delete Item")

                delete_options = {
                    f"ID {row['id']} — "
                    f"{row['item_name']}":
                    int(row["id"])
                    for _, row in items_df.iterrows()
                }

                item_to_delete = st.selectbox(
                    "Select Item",
                    list(delete_options.keys()),
                    key=f"delete_item_{object_id}"
                )

                if st.button(
                    "Delete Selected Item",
                    key=f"delete_item_btn_{object_id}"
                ):

                    try:

                        run_query(
                            """
                            DELETE FROM reklet.object_items
                            WHERE id = %s
                            """,
                            (
                                delete_options[
                                    item_to_delete
                                ],
                            )
                        )

                        st.success(
                            "Item deleted."
                        )

                        st.rerun()

                    except Exception as e:

                        page_error(
                            "Ошибка удаления изделия",
                            e
                        )

    # --------------------------------------------------------
    # MATERIAL REQUIREMENTS
    # --------------------------------------------------------

    with tabs[2]:

        st.subheader(
            "Material Requirements Calculation"
        )

        try:

            requirements_df = run_query(
                """
                SELECT
                    oi.object_id,
                    o.object_name,
                    oi.id AS object_item_id,
                    oi.item_name,
                    oi.quantity,
                    pt.id AS product_template_id,
                    pt.name AS product_name,
                    ptm.material_id,
                    m.name AS material_name,
                    u.name AS unit_name,
                    ptm.quantity_per_unit,
                    COALESCE(
                        ptm.waste_coefficient,
                        m.default_waste_coefficient,
                        1
                    ) AS waste_coefficient,
                    m.stock_quantity,
                    m.cost_per_unit
                FROM reklet.object_items oi

                JOIN reklet.product_templates pt
                    ON pt.id = oi.product_template_id

                JOIN reklet.product_template_materials ptm
                    ON ptm.product_template_id = pt.id

                JOIN reklet.materials m
                    ON m.id = ptm.material_id

                LEFT JOIN reklet.units u
                    ON u.id = m.unit_id

                LEFT JOIN reklet.objects o
                    ON o.id = oi.object_id

                ORDER BY
                    o.object_name,
                    oi.id,
                    m.name
                """,
                fetch=True
            )

            if requirements_df.empty:

                st.info(
                    "Нет данных для расчёта. "
                    "Добавьте материалы в Product Templates."
                )

            else:

                requirements_df[
                    "required_quantity"
                ] = (
                    requirements_df["quantity"]
                    * requirements_df["quantity_per_unit"]
                    * requirements_df["waste_coefficient"]
                )

                requirements_df[
                    "shortage_quantity"
                ] = (
                    requirements_df["required_quantity"]
                    - requirements_df["stock_quantity"]
                ).clip(lower=0)

                requirements_df[
                    "estimated_cost"
                ] = (
                    requirements_df["required_quantity"]
                    * requirements_df["cost_per_unit"]
                )

                show_columns = [
                    "object_name",
                    "item_name",
                    "material_name",
                    "unit_name",
                    "quantity",
                    "quantity_per_unit",
                    "waste_coefficient",
                    "required_quantity",
                    "stock_quantity",
                    "shortage_quantity",
                    "estimated_cost",
                ]

                st.dataframe(
                    requirements_df[show_columns],
                    use_container_width=True,
                    hide_index=True
                )

                total_cost = requirements_df[
                    "estimated_cost"
                ].sum()

                total_shortage = requirements_df[
                    "shortage_quantity"
                ].sum()

                c1, c2 = st.columns(2)

                c1.metric(
                    "Estimated Material Cost",
                    money(total_cost)
                )

                c2.metric(
                    "Total Shortage",
                    f"{total_shortage:,.2f}"
                )

    # --------------------------------------------------------
    # SPECIFICATION
    # --------------------------------------------------------

    with tabs[3]:

        st.subheader(
            "Object Specification"
        )

        try:

            objects_spec = run_query(
                """
                SELECT
                    o.id,
                    o.object_name,
                    o.address,
                    c.name AS client_name
                FROM reklet.objects o
                LEFT JOIN reklet.clients c
                    ON c.id = o.client_id
                ORDER BY o.id
                """,
                fetch=True
            )

        except Exception:

            objects_spec = pd.DataFrame()

        if not objects_spec.empty:

            spec_map = {
                f"{row['object_name']} — "
                f"{row['client_name'] or 'No client'}":
                int(row["id"])
                for _, row in objects_spec.iterrows()
            }

            spec_label = st.selectbox(
                "Object",
                list(spec_map.keys()),
                key="spec_object"
            )

            spec_object_id = spec_map[spec_label]

            object_row = objects_spec[
                objects_spec["id"] == spec_object_id
            ].iloc[0]

            items_spec = run_query(
                """
                SELECT
                    item_name,
                    quantity
                FROM reklet.object_items
                WHERE object_id = %s
                ORDER BY id
                """,
                (spec_object_id,),
                fetch=True
            )

            rows_html = ""

            if not items_spec.empty:

                for index, row in items_spec.iterrows():

                    rows_html += f"""
                    <tr>
                        <td>{index + 1}</td>
                        <td>{escape(str(row['item_name']))}</td>
                        <td>{row['quantity']}</td>
                    </tr>
                    """

            else:

                rows_html = """
                <tr>
                    <td colspan="3">
                        No items
                    </td>
                </tr>
                """

            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">

                <title>
                    Specification -
                    {escape(str(object_row['object_name']))}
                </title>

                <style>

                    body {{
                        font-family: Arial, sans-serif;
                        margin: 40px;
                        color: #222;
                    }}

                    h1 {{
                        border-bottom: 2px solid #333;
                        padding-bottom: 10px;
                    }}

                    table {{
                        width: 100%;
                        border-collapse: collapse;
                        margin-top: 25px;
                    }}

                    th,
                    td {{
                        border: 1px solid #ccc;
                        padding: 10px;
                    }}

                    th {{
                        background: #f4f4f4;
                        text-align: left;
                    }}

                </style>

            </head>

            <body>

                <h1>REKLET — Object Specification</h1>

                <p>
                    <strong>Client:</strong>
                    {escape(str(object_row['client_name'] or ''))}
                </p>

                <p>
                    <strong>Object:</strong>
                    {escape(str(object_row['object_name']))}
                </p>

                <p>
                    <strong>Address:</strong>
                    {escape(str(object_row['address'] or ''))}
                </p>

                <table>

                    <thead>

                        <tr>
                            <th>No.</th>
                            <th>Product</th>
                            <th>Quantity</th>
                        </tr>

                    </thead>

                    <tbody>

                        {rows_html}

                    </tbody>

                </table>

                <script>
                    window.print();
                </script>

            </body>
            </html>
            """

            safe_name = (
                str(object_row["object_name"])
                .replace(" ", "_")
                .replace("/", "_")
            )

            st.download_button(
                "Download HTML Specification",
                data=html_content,
                file_name=f"specification_{safe_name}.html",
                mime="text/html"
            )


# ============================================================
# PRODUCT TEMPLATES
# ============================================================

elif menu == "Product Templates":

    st.markdown(
        '<div class="main-title">Product Templates</div>',
        unsafe_allow_html=True
    )

    tabs = st.tabs([
        "Products",
        "Create Product",
        "Product Materials"
    ])

    # --------------------------------------------------------
    # PRODUCT LIST
    # --------------------------------------------------------

    with tabs[0]:

        try:

            templates_df = run_query(
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
                fetch=True
            )

            if not templates_df.empty:

                st.dataframe(
                    templates_df,
                    use_container_width=True,
                    hide_index=True
                )

            else:

                st.info("No product templates.")

        except Exception as e:

            page_error(
                "Ошибка загрузки Product Templates",
                e
            )

    # --------------------------------------------------------
    # CREATE PRODUCT
    # --------------------------------------------------------

    with tabs[1]:

        st.subheader("Create Product Template")

        with st.form("create_template_form"):

            template_name = st.text_input(
                "Product Name"
            )

            template_type = st.selectbox(
                "Type",
                [
                    "recurrent",
                    "custom"
                ]
            )

            client_name = st.text_input(
                "Client Name"
            )

            category = st.text_input(
                "Category"
            )

            submit_template = st.form_submit_button(
                "Create Product",
                type="primary"
            )

            if submit_template:

                if not template_name.strip():

                    st.warning(
                        "Введите название изделия."
                    )

                else:

                    try:

                        run_query(
                            """
                            INSERT INTO reklet.product_templates
                            (
                                name,
                                type,
                                client_name,
                                category
                            )
                            VALUES
                            (%s,%s,%s,%s)
                            """,
                            (
                                template_name.strip(),
                                template_type,
                                client_name.strip() or None,
                                category.strip() or None
                            )
                        )

                        st.success(
                            "Product template created."
                        )

                        st.rerun()

                    except Exception as e:

                        page_error(
                            "Ошибка создания Product Template",
                            e
                        )

    # --------------------------------------------------------
    # PRODUCT MATERIALS
    # --------------------------------------------------------

    with tabs[2]:

        st.subheader(
            "Materials for Product Template"
        )

        try:

            templates_df = run_query(
                """
                SELECT id, name
                FROM reklet.product_templates
                ORDER BY name
                """,
                fetch=True
            )

            materials_df = run_query(
                """
                SELECT
                    id,
                    name,
                    cost_per_unit,
                    stock_quantity
                FROM reklet.materials
                ORDER BY name
                """,
                fetch=True
            )

        except Exception as e:

            templates_df = pd.DataFrame()
            materials_df = pd.DataFrame()

            page_error(
                "Ошибка загрузки материалов",
                e
            )

        if templates_df.empty:

            st.warning(
                "Сначала создайте Product Template."
            )

        elif materials_df.empty:

            st.warning(
                "Сначала создайте Material."
            )

        else:

            template_map = {
                f"{row['name']} (ID {row['id']})":
                int(row["id"])
                for _, row in templates_df.iterrows()
            }

            selected_template = st.selectbox(
                "Product Template",
                list(template_map.keys()),
                key="material_template_selector"
            )

            selected_template_id = template_map[
                selected_template
            ]

            try:

                current_materials = run_query(
                    """
                    SELECT
                        ptm.id,
                        m.name AS material_name,
                        ptm.quantity_per_unit,
                        ptm.waste_coefficient,
                        u.name AS unit_name
                    FROM reklet.product_template_materials ptm
                    JOIN reklet.materials m
                        ON m.id = ptm.material_id
                    LEFT JOIN reklet.units u
                        ON u.id = m.unit_id
                    WHERE ptm.product_template_id = %s
                    ORDER BY m.name
                    """,
                    (selected_template_id,),
                    fetch=True
                )

                if not current_materials.empty:

                    st.dataframe(
                        current_materials,
                        use_container_width=True,
                        hide_index=True
                    )

                else:

                    st.info(
                        "No materials assigned."
                    )

            except Exception as e:

                page_error(
                    "Ошибка загрузки материалов шаблона",
                    e
                )

            st.markdown("---")

            st.subheader(
                "Add Material"
            )

            material_map = {
                f"{row['name']} "
                f"(stock: {row['stock_quantity']})":
                int(row["id"])
                for _, row in materials_df.iterrows()
            }

            with st.form(
                "add_template_material_form"
            ):

                material_label = st.selectbox(
                    "Material",
                    list(material_map.keys())
                )

                material_id = material_map[
                    material_label
                ]

                quantity_per_unit = st.number_input(
                    "Quantity per Product Unit",
                    min_value=0.0001,
                    value=1.0,
                    step=0.1,
                    format="%.4f"
                )

                waste_coefficient = st.number_input(
                    "Waste Coefficient",
                    min_value=0.0,
                    value=1.20,
                    step=0.05,
                    format="%.2f"
                )

                submit_material = st.form_submit_button(
                    "Add Material",
                    type="primary"
                )

                if submit_material:

                    try:

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
                            VALUES
                            (%s,%s,%s,%s)
                            """,
                            (
                                selected_template_id,
                                material_id,
                                quantity_per_unit,
                                waste_coefficient
                            )
                        )

                        st.success(
                            "Material assigned."
                        )

                        st.rerun()

                    except Exception as e:

                        page_error(
                            "Ошибка добавления материала",
                            e
                        )

            if not current_materials.empty:

                st.markdown("---")

                st.subheader(
                    "Delete Material Assignment"
                )

                delete_material_map = {
                    f"ID {row['id']} — "
                    f"{row['material_name']}":
                    int(row["id"])
                    for _, row in current_materials.iterrows()
                }

                selected_delete = st.selectbox(
                    "Material Assignment",
                    list(delete_material_map.keys())
                )

                if st.button(
                    "Delete Assignment"
                ):

                    try:

                        run_query(
                            """
                            DELETE FROM
                            reklet.product_template_materials
                            WHERE id = %s
                            """,
                            (
                                delete_material_map[
                                    selected_delete
                                ],
                            )
                        )

                        st.success(
                            "Assignment deleted."
                        )

                        st.rerun()

                    except Exception as e:

                        page_error(
                            "Ошибка удаления",
                            e
                        )


# ============================================================
# MATERIALS WAREHOUSE
# ============================================================

elif menu == "Materials Warehouse":

    st.markdown(
        '<div class="main-title">Materials Warehouse</div>',
        unsafe_allow_html=True
    )

    tabs = st.tabs([
        "Materials",
        "Add Material",
        "Suppliers",
        "Units",
        "Transactions"
    ])

    # --------------------------------------------------------
    # MATERIALS
    # --------------------------------------------------------

    with tabs[0]:

        try:

            materials_df = run_query(
                """
                SELECT
                    m.id,
                    m.name,
                    s.name AS supplier,
                    u.name AS unit,
                    m.default_waste_coefficient,
                    m.cost_per_unit,
                    m.stock_quantity
                FROM reklet.materials m
                LEFT JOIN reklet.suppliers s
                    ON s.id = m.supplier_id
                LEFT JOIN reklet.units u
                    ON u.id = m.unit_id
                ORDER BY m.id
                """,
                fetch=True
            )

            if not materials_df.empty:

                st.dataframe(
                    materials_df,
                    use_container_width=True,
                    hide_index=True
                )

            else:

                st.info(
                    "No materials in warehouse."
                )

        except Exception as e:

            page_error(
                "Ошибка склада",
                e
            )

    # --------------------------------------------------------
    # ADD MATERIAL
    # --------------------------------------------------------

    with tabs[1]:

        st.subheader(
            "Add Material"
        )

        try:

            suppliers_df = run_query(
                """
                SELECT id, name
                FROM reklet.suppliers
                ORDER BY name
                """,
                fetch=True
            )

            units_df = run_query(
                """
                SELECT id, name
                FROM reklet.units
                ORDER BY name
                """,
                fetch=True
            )

        except Exception:

            suppliers_df = pd.DataFrame()
            units_df = pd.DataFrame()

        supplier_map = {
            "No supplier": None
        }

        for _, row in suppliers_df.iterrows():

            supplier_map[
                f"{row['name']} (ID {row['id']})"
            ] = int(row["id"])

        unit_map = {
            f"{row['name']} (ID {row['id']})":
            int(row["id"])
            for _, row in units_df.iterrows()
        }

        with st.form("add_material_form"):

            material_name = st.text_input(
                "Material Name"
            )

            supplier_label = st.selectbox(
                "Supplier",
                list(supplier_map.keys())
            )

            if unit_map:

                unit_label = st.selectbox(
                    "Unit",
                    list(unit_map.keys())
                )

                selected_unit = unit_map[
                    unit_label
                ]

            else:

                selected_unit = None

                st.warning(
                    "Создайте Unit сначала."
                )

            col1, col2, col3 = st.columns(3)

            with col1:

                waste = st.number_input(
                    "Default Waste Coefficient",
                    min_value=0.0,
                    value=1.20,
                    step=0.05
                )

            with col2:

                cost = st.number_input(
                    "Cost per Unit",
                    min_value=0.0,
                    value=0.0,
                    step=0.01
                )

            with col3:

                stock = st.number_input(
                    "Initial Stock",
                    min_value=0.0,
                    value=0.0,
                    step=1.0
                )

            submit_material = st.form_submit_button(
                "Create Material",
                type="primary"
            )

            if submit_material:

                if not material_name.strip():

                    st.warning(
                        "Введите название материала."
                    )

                elif selected_unit is None:

                    st.warning(
                        "Создайте единицу измерения."
                    )

                else:

                    try:

                        run_query(
                            """
                            INSERT INTO reklet.materials
                            (
                                supplier_id,
                                name,
                                default_waste_coefficient,
                                cost_per_unit,
                                stock_quantity,
                                unit_id
                            )
                            VALUES
                            (%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                supplier_map[
                                    supplier_label
                                ],
                                material_name.strip(),
                                waste,
                                cost,
                                stock,
                                selected_unit
                            )
                        )

                        st.success(
                            "Material created."
                        )

                        st.rerun()

                    except Exception as e:

                        page_error(
                            "Ошибка создания материала",
                            e
                        )

    # --------------------------------------------------------
    # SUPPLIERS
    # --------------------------------------------------------

    with tabs[2]:

        st.subheader(
            "Suppliers"
        )

        try:

            suppliers_df = run_query(
                """
                SELECT *
                FROM reklet.suppliers
                ORDER BY id
                """,
                fetch=True
            )

            if not suppliers_df.empty:

                st.dataframe(
                    suppliers_df,
                    use_container_width=True,
                    hide_index=True
                )

        except Exception as e:

            page_error(
                "Ошибка загрузки поставщиков",
                e
            )

        st.markdown("---")

        with st.form("supplier_form"):

            supplier_name = st.text_input(
                "Supplier Name"
            )

            supplier_type = st.selectbox(
                "Supplier Type",
                [
                    "material_supplier",
                    "subcontractor",
                    "both"
                ]
            )

            contact_person = st.text_input(
                "Contact Person"
            )

            phone = st.text_input(
                "Phone"
            )

            email = st.text_input(
                "Email"
            )

            category = st.text_input(
                "Category"
            )

            conditions = st.text_area(
                "Conditions"
            )

            contact_info = st.text_area(
                "Additional Contact Info"
            )

            submit_supplier = st.form_submit_button(
                "Create Supplier",
                type="primary"
            )

            if submit_supplier:

                if not supplier_name.strip():

                    st.warning(
                        "Введите название поставщика."
                    )

                else:

                    try:

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
                            (%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                supplier_name.strip(),
                                supplier_type,
                                contact_info.strip(),
                                contact_person.strip(),
                                phone.strip(),
                                email.strip(),
                                category.strip(),
                                conditions.strip()
                            )
                        )

                        st.success(
                            "Supplier created."
                        )

                        st.rerun()

                    except Exception as e:

                        page_error(
                            "Ошибка создания поставщика",
                            e
                        )

    # --------------------------------------------------------
    # UNITS
    # --------------------------------------------------------

    with tabs[3]:

        st.subheader(
            "Units"
        )

        try:

            units_df = run_query(
                """
                SELECT *
                FROM reklet.units
                ORDER BY id
                """,
                fetch=True
            )

            if not units_df.empty:

                st.dataframe(
                    units_df,
                    use_container_width=True,
                    hide_index=True
                )

        except Exception as e:

            page_error(
                "Ошибка загрузки единиц",
                e
            )

        with st.form("unit_form"):

            unit_name = st.text_input(
                "Unit Name",
                placeholder="pcs, m, kg..."
            )

            submit_unit = st.form_submit_button(
                "Create Unit",
                type="primary"
            )

            if submit_unit:

                if not unit_name.strip():

                    st.warning(
                        "Введите единицу."
                    )

                else:

                    try:

                        run_query(
                            """
                            INSERT INTO reklet.units
                            (name)
                            VALUES (%s)
                            """,
                            (
                                unit_name.strip(),
                            )
                        )

                        st.success(
                            "Unit created."
                        )

                        st.rerun()

                    except Exception as e:

                        page_error(
                            "Ошибка создания единицы",
                            e
                        )

    # --------------------------------------------------------
    # TRANSACTIONS
    # --------------------------------------------------------

    with tabs[4]:

        st.subheader(
            "Material Transactions"
        )

        try:

            transactions_df = run_query(
                """
                SELECT
                    mt.id,
                    mt.created_at,
                    m.name AS material,
                    s.name AS supplier,
                    o.object_name,
                    mt.operation_type,
                    mt.quantity,
                    mt.unit_price,
                    mt.waste_coefficient,
                    mt.transaction_type
                FROM reklet.material_transactions mt
                LEFT JOIN reklet.materials m
                    ON m.id = mt.material_id
                LEFT JOIN reklet.suppliers s
                    ON s.id = mt.supplier_id
                LEFT JOIN reklet.objects o
                    ON o.id = mt.object_id
                ORDER BY mt.created_at DESC
                """,
                fetch=True
            )

            if not transactions_df.empty:

                st.dataframe(
                    transactions_df,
                    use_container_width=True,
                    hide_index=True
                )

            else:

                st.info(
                    "No material transactions."
                )

        except Exception as e:

            page_error(
                "Ошибка транзакций",
                e
            )


# ============================================================
# PRODUCTION
# ============================================================

elif menu == "Production":

    st.markdown(
        '<div class="main-title">Production Control</div>',
        unsafe_allow_html=True
    )

    try:

        production_df = run_query(
            """
            SELECT
                oi.id,
                o.object_name,
                oi.item_name,
                oi.quantity,
                oi.qty_new,
                oi.qty_production,
                oi.qty_ready,
                oi.production_status,
                oi.production_progress_pct
            FROM reklet.object_items oi
            LEFT JOIN reklet.objects o
                ON o.id = oi.object_id
            WHERE
                oi.qty_new > 0
                OR oi.qty_production > 0
                OR oi.qty_ready > 0
            ORDER BY
                o.object_name,
                oi.id
            """,
            fetch=True
        )

        if production_df.empty:

            st.info(
                "No active production items."
            )

        else:

            st.dataframe(
                production_df,
                use_container_width=True,
                hide_index=True
            )

    except Exception as e:

        page_error(
            "Ошибка Production",
            e
        )

    st.markdown("---")

    st.subheader(
        "Production Quantity Update"
    )

    try:

        active_items = run_query(
            """
            SELECT
                oi.id,
                oi.item_name,
                oi.quantity,
                o.object_name
            FROM reklet.object_items oi
            LEFT JOIN reklet.objects o
                ON o.id = oi.object_id
            WHERE oi.quantity > 0
            ORDER BY o.object_name, oi.item_name
            """,
            fetch=True
        )

    except Exception:

        active_items = pd.DataFrame()

    if not active_items.empty:

        production_item_map = {
            f"{row['object_name']} — "
            f"{row['item_name']} "
            f"(Qty {row['quantity']}, ID {row['id']})":
            int(row["id"])
            for _, row in active_items.iterrows()
        }

        selected_item_label = st.selectbox(
            "Item",
            list(production_item_map.keys()),
            key="production_item_selector"
        )

        selected_item_id = production_item_map[
            selected_item_label
        ]

        item_current = run_query(
            """
            SELECT
                quantity,
                qty_new,
                qty_production,
                qty_ready
            FROM reklet.object_items
            WHERE id = %s
            """,
            (selected_item_id,),
            fetch=True
        )

        if not item_current.empty:

            current = item_current.iloc[0]

            st.write(
                f"Total quantity: **{current['quantity']}**"
            )

            p1, p2, p3 = st.columns(3)

            with p1:

                new_qty = st.number_input(
                    "New",
                    min_value=0,
                    value=safe_int(current["qty_new"]),
                    key="production_new"
                )

            with p2:

                production_qty = st.number_input(
                    "Production",
                    min_value=0,
                    value=safe_int(current["qty_production"]),
                    key="production_process"
                )

            with p3:

                ready_qty = st.number_input(
                    "Ready",
                    min_value=0,
                    value=safe_int(current["qty_ready"]),
                    key="production_ready"
                )

            if st.button(
                "Save Production Status",
                type="primary"
            ):

                total = (
                    new_qty
                    + production_qty
                    + ready_qty
                )

                quantity = safe_int(
                    current["quantity"]
                )

                if total > quantity:

                    st.error(
                        "Количество по этапам "
                        "не может превышать общее количество."
                    )

                else:

                    if ready_qty >= quantity:

                        status = "completed"
                        pct = 100

                    elif production_qty > 0:

                        status = "in_progress"

                        pct = round(
                            (
                                ready_qty
                                / quantity
                            ) * 100
                        )

                    else:

                        status = "not_started"
                        pct = 0

                    run_query(
                        """
                        UPDATE reklet.object_items
                        SET
                            qty_new = %s,
                            qty_production = %s,
                            qty_ready = %s,
                            production_status = %s,
                            production_progress_pct = %s
                        WHERE id = %s
                        """,
                        (
                            new_qty,
                            production_qty,
                            ready_qty,
                            status,
                            min(pct, 100),
                            selected_item_id
                        )
                    )

                    st.success(
                        "Production status updated."
                    )

                    st.rerun()


# ============================================================
# TRANSPORT
# ============================================================

elif menu == "Transport":

    st.markdown(
        '<div class="main-title">Transport & Logistics</div>',
        unsafe_allow_html=True
    )

    try:

        transport_df = run_query(
            """
            SELECT
                o.id,
                o.object_name,
                c.name AS client,
                o.address,
                o.transport_distance_km,
                o.delivery_cost,
                o.production_end_date,
                o.installation_date
            FROM reklet.objects o
            LEFT JOIN reklet.clients c
                ON c.id = o.client_id
            ORDER BY
                o.installation_date NULLS LAST,
                o.id
            """,
            fetch=True
        )

        if not transport_df.empty:

            st.dataframe(
                transport_df,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "No transport data."
            )

    except Exception as e:

        page_error(
            "Ошибка Transport",
            e
        )


# ============================================================
# INSTALLATION
# ============================================================

elif menu == "Installation":

    st.markdown(
        '<div class="main-title">Installation Management</div>',
        unsafe_allow_html=True
    )

    try:

        installation_df = run_query(
            """
            SELECT
                oi.id,
                o.object_name,
                oi.item_name,
                oi.quantity,
                oi.qty_arrived,
                oi.qty_installing,
                oi.qty_installed,
                oi.installation_status,
                oi.installation_progress_pct
            FROM reklet.object_items oi
            LEFT JOIN reklet.objects o
                ON o.id = oi.object_id
            ORDER BY
                o.object_name,
                oi.id
            """,
            fetch=True
        )

        if not installation_df.empty:

            st.dataframe(
                installation_df,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "No installation items."
            )

    except Exception as e:

        page_error(
            "Ошибка Installation",
            e
        )

    st.markdown("---")

    st.subheader(
        "Installation Quantity Update"
    )

    try:

        installation_items = run_query(
            """
            SELECT
                oi.id,
                oi.item_name,
                oi.quantity,
                o.object_name
            FROM reklet.object_items oi
            LEFT JOIN reklet.objects o
                ON o.id = oi.object_id
            WHERE oi.quantity > 0
            ORDER BY o.object_name, oi.item_name
            """,
            fetch=True
        )

    except Exception:

        installation_items = pd.DataFrame()

    if not installation_items.empty:

        installation_map = {
            f"{row['object_name']} — "
            f"{row['item_name']} "
            f"(Qty {row['quantity']}, ID {row['id']})":
            int(row["id"])
            for _, row in installation_items.iterrows()
        }

        installation_label = st.selectbox(
            "Item",
            list(installation_map.keys()),
            key="installation_selector"
        )

        installation_id = installation_map[
            installation_label
        ]

        current_installation = run_query(
            """
            SELECT
                quantity,
                qty_shipped,
                qty_arrived,
                qty_installing,
                qty_installed
            FROM reklet.object_items
            WHERE id = %s
            """,
            (installation_id,),
            fetch=True
        )

        if not current_installation.empty:

            current = current_installation.iloc[0]

            total_qty = safe_int(
                current["quantity"]
            )

            c1, c2, c3, c4 = st.columns(4)

            with c1:

                shipped = st.number_input(
                    "Shipped",
                    min_value=0,
                    value=safe_int(
                        current["qty_shipped"]
                    ),
                    key="install_shipped"
                )

            with c2:

                arrived = st.number_input(
                    "Arrived",
                    min_value=0,
                    value=safe_int(
                        current["qty_arrived"]
                    ),
                    key="install_arrived"
                )

            with c3:

                installing = st.number_input(
                    "Installing",
                    min_value=0,
                    value=safe_int(
                        current["qty_installing"]
                    ),
                    key="install_installing"
                )

            with c4:

                installed = st.number_input(
                    "Installed",
                    min_value=0,
                    value=safe_int(
                        current["qty_installed"]
                    ),
                    key="install_installed"
                )

            if st.button(
                "Save Installation Status",
                type="primary"
            ):

                if (
                    shipped > total_qty
                    or arrived > total_qty
                    or installing > total_qty
                    or installed > total_qty
                ):

                    st.error(
                        "Количество не может превышать "
                        "общее количество."
                    )

                else:

                    if installed >= total_qty:

                        status = "completed"
                        pct = 100

                    elif installing > 0:

                        status = "in_progress"

                        pct = round(
                            installed
                            / total_qty
                            * 100
                        )

                    else:

                        status = "not_started"
                        pct = 0

                    run_query(
                        """
                        UPDATE reklet.object_items
                        SET
                            qty_shipped = %s,
                            qty_arrived = %s,
                            qty_installing = %s,
                            qty_installed = %s,
                            installation_status = %s,
                            installation_progress_pct = %s
                        WHERE id = %s
                        """,
                        (
                            shipped,
                            arrived,
                            installing,
                            installed,
                            status,
                            min(pct, 100),
                            installation_id
                        )
                    )

                    st.success(
                        "Installation status updated."
                    )

                    st.rerun()


# ============================================================
# PAYROLL
# ============================================================

elif menu == "Payroll Calculation":

    st.markdown(
        '<div class="main-title">Payroll Calculation</div>',
        unsafe_allow_html=True
    )

    st.info(
        "Payroll is calculated from material cost "
        "and production / installation departments."
    )

    try:

        payroll_df = run_query(
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
            ORDER BY pr.updated_at DESC
            """,
            fetch=True
        )

        if not payroll_df.empty:

            st.dataframe(
                payroll_df,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "No payroll records."
            )

    except Exception as e:

        page_error(
            "Ошибка Payroll",
            e
        )

    st.markdown("---")

    st.subheader(
        "Create / Update Payroll Record"
    )

    try:

        items_for_payroll = run_query(
            """
            SELECT
                oi.id,
                oi.item_name,
                o.object_name
            FROM reklet.object_items oi
            LEFT JOIN reklet.objects o
                ON o.id = oi.object_id
            ORDER BY o.object_name, oi.item_name
            """,
            fetch=True
        )

    except Exception:

        items_for_payroll = pd.DataFrame()

    if not items_for_payroll.empty:

        payroll_item_map = {
            f"{row['object_name']} — "
            f"{row['item_name']} "
            f"(ID {row['id']})":
            int(row["id"])
            for _, row in items_for_payroll.iterrows()
        }

        payroll_item_label = st.selectbox(
            "Object Item",
            list(payroll_item_map.keys())
        )

        payroll_item_id = payroll_item_map[
            payroll_item_label
        ]

        department = st.selectbox(
            "Department",
            [
                "production",
                "installation"
            ]
        )

        base_cost = st.number_input(
            "Base Material Cost",
            min_value=0.0,
            value=0.0,
            step=0.01
        )

        calculated_amount = st.number_input(
            "Calculated Amount",
            min_value=0.0,
            value=0.0,
            step=0.01
        )

        manual_amount = st.number_input(
            "Manual Override Amount",
            min_value=0.0,
            value=0.0,
            step=0.01
        )

        is_manual = st.checkbox(
            "Manual Override"
        )

        if st.button(
            "Save Payroll Record",
            type="primary"
        ):

            try:

                existing = run_query(
                    """
                    SELECT id
                    FROM reklet.payroll_records
                    WHERE
                        object_item_id = %s
                        AND department = %s
                    LIMIT 1
                    """,
                    (
                        payroll_item_id,
                        department
                    ),
                    fetch=True
                )

                if existing.empty:

                    run_query(
                        """
                        INSERT INTO
                        reklet.payroll_records
                        (
                            object_item_id,
                            department,
                            base_material_cost,
                            calculated_amount,
                            manual_override_amount,
                            is_manual,
                            updated_at
                        )
                        VALUES
                        (%s,%s,%s,%s,%s,%s,
                         timezone('utc'::text, now()))
                        """,
                        (
                            payroll_item_id,
                            department,
                            base_cost,
                            calculated_amount,
                            manual_amount
                            if is_manual
                            else None,
                            is_manual
                        )
                    )

                else:

                    record_id = safe_int(
                        existing.iloc[0]["id"]
                    )

                    run_query(
                        """
                        UPDATE reklet.payroll_records
                        SET
                            base_material_cost = %s,
                            calculated_amount = %s,
                            manual_override_amount = %s,
                            is_manual = %s,
                            updated_at =
                                timezone(
                                    'utc'::text,
                                    now()
                                )
                        WHERE id = %s
                        """,
                        (
                            base_cost,
                            calculated_amount,
                            manual_amount
                            if is_manual
                            else None,
                            is_manual,
                            record_id
                        )
                    )

                st.success(
                    "Payroll record saved."
                )

                st.rerun()

            except Exception as e:

                page_error(
                    "Ошибка сохранения Payroll",
                    e
                )


# ============================================================
# REPORTS
# ============================================================

elif menu == "Reports":

    st.markdown(
        '<div class="main-title">Reports & Analytics</div>',
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # KPI
    # --------------------------------------------------------

    try:

        clients_count = run_query(
            """
            SELECT COUNT(*) AS count
            FROM reklet.clients
            """,
            fetch=True
        ).iloc[0]["count"]

        objects_count = run_query(
            """
            SELECT COUNT(*) AS count
            FROM reklet.objects
            """,
            fetch=True
        ).iloc[0]["count"]

        products_count = run_query(
            """
            SELECT COUNT(*) AS count
            FROM reklet.product_templates
            """,
            fetch=True
        ).iloc[0]["count"]

        materials_count = run_query(
            """
            SELECT COUNT(*) AS count
            FROM reklet.materials
            """,
            fetch=True
        ).iloc[0]["count"]

        k1, k2, k3, k4 = st.columns(4)

        k1.metric(
            "Clients",
            clients_count
        )

        k2.metric(
            "Objects",
            objects_count
        )

        k3.metric(
            "Products",
            products_count
        )

        k4.metric(
            "Materials",
            materials_count
        )

    except Exception as e:

        page_error(
            "Ошибка KPI",
            e
        )

    st.markdown("---")

    # --------------------------------------------------------
    # OBJECT STATUS
    # --------------------------------------------------------

    st.subheader(
        "Object Items Status"
    )

    try:

        report_df = run_query(
            """
            SELECT
                o.object_name,
                oi.item_name,
                oi.quantity,
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
            LEFT JOIN reklet.objects o
                ON o.id = oi.object_id
            ORDER BY
                o.object_name,
                oi.id
            """,
            fetch=True
        )

        if not report_df.empty:

            st.dataframe(
                report_df,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "No object items."
            )

    except Exception as e:

        page_error(
            "Ошибка отчёта",
            e
        )

    st.markdown("---")

    # --------------------------------------------------------
    # MATERIAL STOCK
    # --------------------------------------------------------

    st.subheader(
        "Warehouse Stock"
    )

    try:

        stock_df = run_query(
            """
            SELECT
                m.name AS material,
                u.name AS unit,
                m.stock_quantity,
                m.cost_per_unit,
                (
                    m.stock_quantity
                    * m.cost_per_unit
                ) AS stock_value
            FROM reklet.materials m
            LEFT JOIN reklet.units u
                ON u.id = m.unit_id
            ORDER BY m.name
            """,
            fetch=True
        )

        if not stock_df.empty:

            st.dataframe(
                stock_df,
                use_container_width=True,
                hide_index=True
            )

            total_stock_value = stock_df[
                "stock_value"
            ].fillna(0).sum()

            st.metric(
                "Total Warehouse Value",
                money(total_stock_value)
            )

        else:

            st.info(
                "No warehouse data."
            )

    except Exception as e:

        page_error(
            "Ошибка отчёта склада",
            e
        )
