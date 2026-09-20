import streamlit as st
import pandas as pd
import psycopg2
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

try:
    DB_HOST = st.secrets["DB_HOST"]
    DB_PORT = int(st.secrets["DB_PORT"])
    DB_NAME = st.secrets["DB_NAME"]
    DB_USER = st.secrets["DB_USER"]
    DB_PASSWORD = st.secrets["DB_PASSWORD"]

except Exception as e:

    st.error("Database secrets are not configured.")

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
        "Add these values in Streamlit Cloud → Settings → Secrets."
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


if not st.session_state["authentication_status"]:

    st.title(
        "Reklet — Production Management"
    )

    st.subheader("Login")

    with st.form("login_form"):

        username_input = st.text_input(
            "Username"
        )

        password_input = st.text_input(
            "Password",
            type="password"
        )

        submit_login = st.form_submit_button(
            "Login"
        )

        if submit_login:

            if (
                username_input == "admin"
                and password_input == "qwert12345"
            ):

                st.session_state[
                    "authentication_status"
                ] = True

                st.session_state[
                    "username"
                ] = "admin"

                st.session_state[
                    "name"
                ] = "Administrator"

                st.rerun()

            else:

                st.session_state[
                    "authentication_status"
                ] = False

                st.error(
                    "Invalid username or password"
                )

    st.stop()


# ============================================================
# LOGOUT
# ============================================================

if st.sidebar.button("Logout"):

    st.session_state[
        "authentication_status"
    ] = None

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

        ORDER BY o.id
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
            m.default_waste_coefficient

        FROM reklet.materials m

        LEFT JOIN reklet.units u
            ON u.id = m.unit_id

        ORDER BY m.name
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

    "Clients",
    "Objects",
    "Product Templates",
    "Materials Warehouse",
    "Suppliers",
    "Production",
    "Finished Goods",
    "Transport & Logistics",
    "Installation",
    "Payroll",
    "Reports"

]


menu = st.radio(
    "Navigation",
    menu_options,
    horizontal=True,
    label_visibility="collapsed"
)


st.markdown("---")


# ============================================================
# CLIENTS
# ============================================================

if menu == "Clients":

    st.header("Clients")

    df = get_clients()

    if not df.empty:

        edited = st.data_editor(
            df,
            key="clients_editor",
            use_container_width=True,
            num_rows="fixed"
        )

        if st.button(
            "Save Changes",
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

            st.success("Saved.")

            st.rerun()

    else:

        st.info("No clients.")

    st.markdown("---")

    st.subheader("Add Client")

    with st.form("add_client"):

        name = st.text_input("Name")

        contact = st.text_area(
            "Contact"
        )

        submit = st.form_submit_button(
            "Add"
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


# ============================================================
# OBJECTS
# ============================================================

elif menu == "Objects":

    st.header("Objects")

    sub = st.radio(
        "Objects",
        [
            "Object List",
            "Object Content",
            "Material Requirements"
        ],
        horizontal=True
    )

    st.markdown("---")


    # ========================================================
    # OBJECT LIST
    # ========================================================

    if sub == "Object List":

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

            edited = st.data_editor(
                display,
                key="objects_editor",
                use_container_width=True
            )

            if st.button(
                "Save Changes",
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

                st.success("Saved.")

                st.rerun()


        st.markdown("---")

        st.subheader("Create Object")

        client_map = {}

        if not clients.empty:

            client_map = {
                str(row["name"]): int(row["id"])
                for _, row in clients.iterrows()
            }


        with st.form("create_object"):

            client_name = st.selectbox(
                "Client",
                list(client_map.keys())
                if client_map
                else []
            )

            object_name = st.text_input(
                "Object Name"
            )

            address = st.text_input(
                "Address"
            )

            phone = st.text_input(
                "Phone"
            )

            contact_person = st.text_input(
                "Contact Person"
            )

            notes = st.text_area(
                "Notes"
            )

            c1, c2 = st.columns(2)

            with c1:

                distance = st.number_input(
                    "Transport Distance (km)",
                    min_value=0.0,
                    value=0.0
                )

                delivery_cost = st.number_input(
                    "Delivery Cost",
                    min_value=0.0,
                    value=0.0
                )

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

            with c2:

                installation_date = st.date_input(
                    "Installation Date",
                    value=None
                )

                installation_end = st.date_input(
                    "Installation End",
                    value=None
                )

            submit = st.form_submit_button(
                "Create Object"
            )

            if submit:

                if (
                    not client_name
                    or not object_name.strip()
                ):

                    st.warning(
                        "Client and Object Name are required."
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
                        "Object created."
                    )

                    st.rerun()


    # ========================================================
    # OBJECT CONTENT
    # ========================================================

    elif sub == "Object Content":

        objects = get_objects()

        if objects.empty:

            st.info(
                "No objects."
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
                "Object",
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

                edited = st.data_editor(
                    display,
                    key=f"object_items_{object_id}",
                    use_container_width=True
                )

                if st.button(
                    "Save Item Quantities",
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

                    st.success("Saved.")

                    st.rerun()

            else:

                st.info(
                    "No products in this object."
                )


            st.markdown("---")

            st.subheader(
                "Add Product"
            )

            templates = get_templates()

            if not templates.empty:

                template_map = {
                    f"{row['name']} — "
                    f"{row['client_name'] or 'General'}":
                        int(row["id"])

                    for _, row in templates.iterrows()
                }

                with st.form(
                    f"add_item_{object_id}"
                ):

                    template_label = st.selectbox(
                        "Product Template",
                        list(template_map.keys())
                    )

                    quantity = st.number_input(
                        "Quantity",
                        min_value=1,
                        value=1,
                        step=1
                    )

                    submit = st.form_submit_button(
                        "Add Product"
                    )

                    if submit:

                        template_id = template_map[
                            template_label
                        ]

                        template_row = templates[
                            templates["id"] == template_id
                        ].iloc[0]

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
                            "Product added."
                        )

                        st.rerun()


            st.markdown("---")

            st.subheader(
                "Specification"
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
                    <b>Client:</b>
                    {escape(
                        str(
                            object_row["client_name"]
                            or ""
                        )
                    )}
                </p>

                <p>
                    <b>Object:</b>
                    {escape(
                        str(
                            object_row["object_name"]
                            or ""
                        )
                    )}
                </p>

                <p>
                    <b>Address:</b>
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
                        <th>Product</th>
                        <th>Quantity</th>
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
                "Download Specification HTML",
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
            "Material Requirements"
        )

        objects = get_objects()

        if objects.empty:

            st.info(
                "No objects."
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
                "Object",
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

                        "Product",
                        "Product Qty",
                        "Material",
                        "Unit",
                        "Qty / Product",
                        "Waste Coef.",
                        "Required",
                        "Unit Cost",
                        "Material Cost"

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

                        "Material",
                        "Unit",
                        "Required",
                        "Stock",
                        "Shortage",
                        "Unit Cost",
                        "Total Cost"

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
                        "Estimated Material Cost",
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
                            <b>Client:</b>
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
                            <b>Object:</b>
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
                            <b>Address:</b>
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
                        "Download Material Requirements HTML",
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

elif menu == "Product Templates":

    st.header(
        "Product Templates"
    )

    templates = get_templates()


    # ========================================================
    # CREATE
    # ========================================================

    with st.expander(
        "Create Product Template",
        expanded=False
    ):

        with st.form(
            "create_template"
        ):

            name = st.text_input(
                "Product Name"
            )

            type_value = st.selectbox(
                "Type",
                [
                    "recurrent",
                    "custom"
                ]
            )

            client_name = st.text_input(
                "Client"
            )

            category = st.text_input(
                "Category"
            )

            submit = st.form_submit_button(
                "Create Product"
            )

            if submit:

                if not name.strip():

                    st.warning(
                        "Product name is required."
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
                        "Product created."
                    )

                    st.rerun()


    # ========================================================
    # EDIT
    # ========================================================

    if not templates.empty:

        st.subheader(
            "Products"
        )

        edited = st.data_editor(
            templates,
            key="templates_editor",
            use_container_width=True,
            num_rows="fixed"
        )

        if st.button(
            "Save Product Changes",
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
                "Saved."
            )

            st.rerun()


    st.markdown("---")

    st.subheader(
        "Product Material Specification"
    )

    if templates.empty:

        st.info(
            "Create a product first."
        )

    else:

        template_map = {

            f"{row['id']} — "
            f"{row['name']} — "
            f"{row['client_name'] or 'General'}":
                int(row["id"])

            for _, row in templates.iterrows()
        }

        selected = st.selectbox(
            "Product",
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

            display.columns = [

                "ID",
                "Material",
                "Unit",
                "Qty / Product",
                "Waste Coef."

            ]

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True
            )

            st.markdown(
                "### Delete Specification Row"
            )

            delete_map = {

                f"{row['id']} — "
                f"{row['material_name']}":
                    int(row["id"])

                for _, row in specification.iterrows()
            }

            delete_label = st.selectbox(
                "Specification Row",
                list(delete_map.keys()),
                key="delete_spec_row"
            )

            if st.button(
                "Delete Specification Row"
            ):

                run_query(
                    """
                    DELETE FROM
                        reklet.product_template_materials

                    WHERE id = %s
                    """,
                    (
                        delete_map[
                            delete_label
                        ],
                    )
                )

                st.success(
                    "Deleted."
                )

                st.rerun()

        else:

            st.info(
                "No materials in this product specification."
            )


        st.markdown("---")

        st.subheader(
            "Add Material"
        )

        materials = get_materials()

        if materials.empty:

            st.warning(
                "Create materials in Materials Warehouse first."
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
                    "Material",
                    list(material_map.keys())
                )

                quantity_per_unit = st.number_input(
                    "Quantity per Product",
                    min_value=0.0001,
                    value=1.0,
                    format="%.4f"
                )

                waste = st.number_input(
                    "Waste Coefficient",
                    min_value=0.0,
                    value=1.20,
                    format="%.2f"
                )

                submit = st.form_submit_button(
                    "Add Material"
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
                        "Material added to specification."
                    )

                    st.rerun()


    # ========================================================
    # DELETE PRODUCT
    # ========================================================

    st.markdown("---")

    st.subheader(
        "Delete Product"
    )

    if not templates.empty:

        delete_product_map = {

            f"{row['id']} — {row['name']}":
                int(row["id"])

            for _, row in templates.iterrows()
        }

        delete_product = st.selectbox(
            "Product",
            list(delete_product_map.keys()),
            key="delete_product"
        )

        if st.button(
            "Delete Product",
            key="delete_product_button"
        ):

            try:

                run_query(
                    """
                    DELETE FROM
                        reklet.product_templates

                    WHERE id = %s
                    """,
                    (
                        delete_product_map[
                            delete_product
                        ],
                    )
                )

                st.success(
                    "Product deleted."
                )

                st.rerun()

            except Exception as e:

                st.error(
                    "Product cannot be deleted. "
                    "It may already be used in an object."
                )

                st.code(
                    str(e)
                )


# ============================================================
# MATERIALS WAREHOUSE
# ============================================================

elif menu == "Materials Warehouse":

    st.header(
        "Materials Warehouse"
    )

    materials = get_materials()


    # ========================================================
    # CREATE MATERIAL
    # ========================================================

    with st.expander(
        "Create Material",
        expanded=False
    ):

        suppliers = get_suppliers()

        units = run_query(
            """
            SELECT
                id,
                name

            FROM reklet.units

            ORDER BY name
            """,
            fetch=True
        )

        supplier_map = {}

        if not suppliers.empty:

            supplier_map = {

                row["name"]:
                    int(row["id"])

                for _, row in suppliers.iterrows()
            }

        unit_map = {}

        if not units.empty:

            unit_map = {

                row["name"]:
                    int(row["id"])

                for _, row in units.iterrows()
            }

        with st.form(
            "create_material"
        ):

            material_name = st.text_input(
                "Material Name"
            )

            if unit_map:

                unit_name = st.selectbox(
                    "Unit",
                    list(unit_map.keys())
                )

            else:

                unit_name = None

                st.warning(
                    "Create units first."
                )

            cost = st.number_input(
                "Default Cost",
                min_value=0.0,
                value=0.0,
                format="%.2f"
            )

            stock = st.number_input(
                "Opening Stock",
                min_value=0.0,
                value=0.0,
                format="%.4f"
            )

            waste = st.number_input(
                "Default Waste Coefficient",
                min_value=0.0,
                value=1.20,
                format="%.2f"
            )

            submit = st.form_submit_button(
                "Create Material"
            )

            if submit:

                if not material_name.strip():

                    st.warning(
                        "Material name is required."
                    )

                elif not unit_map:

                    st.warning(
                        "Create at least one unit."
                    )

                else:

                    run_query(
                        """
                        INSERT INTO reklet.materials
                        (
                            name,
                            unit_id,
                            cost_per_unit,
                            stock_quantity,
                            default_waste_coefficient
                        )

                        VALUES (%s,%s,%s,%s,%s)
                        """,
                        (
                            material_name,
                            unit_map[unit_name],
                            cost,
                            stock,
                            waste
                        )
                    )

                    st.success(
                        "Material created."
                    )

                    st.rerun()


    # ========================================================
    # MATERIAL LIST
    # ========================================================

    if not materials.empty:

        st.subheader(
            "Materials"
        )

        display = materials[
            [
                "id",
                "name",
                "unit_name",
                "cost_per_unit",
                "stock_quantity",
                "default_waste_coefficient"
            ]
        ].copy()

        edited = st.data_editor(
            display,
            key="materials_editor",
            use_container_width=True
        )

        if st.button(
            "Save Material Changes"
        ):

            for _, row in edited.iterrows():

                run_query(
                    """
                    UPDATE reklet.materials

                    SET

                        name = %s,

                        cost_per_unit = %s,

                        stock_quantity = %s,

                        default_waste_coefficient = %s

                    WHERE id = %s
                    """,
                    (
                        row["name"],
                        safe_float(
                            row["cost_per_unit"]
                        ),
                        safe_float(
                            row["stock_quantity"]
                        ),
                        safe_float(
                            row[
                                "default_waste_coefficient"
                            ],
                            1.20
                        ),
                        safe_int(
                            row["id"]
                        )
                    )
                )

            st.success(
                "Saved."
            )

            st.rerun()

    else:

        st.info(
            "No materials."
        )


    # ========================================================
    # SUPPLIERS PER MATERIAL
    # ========================================================

    st.markdown("---")

    st.subheader(
        "Material Suppliers"
    )

    if not materials.empty:

        material_map = {

            row["name"]:
                int(row["id"])

            for _, row in materials.iterrows()
        }

        material_label = st.selectbox(
            "Material",
            list(material_map.keys()),
            key="material_supplier_material"
        )

        material_id = material_map[
            material_label
        ]

        supplier_data = run_query(
            """
            SELECT

                ms.id,

                s.name AS supplier,

                ms.purchase_price,

                ms.supplier_code,

                ms.conditions,

                ms.is_preferred

            FROM
                reklet.material_suppliers ms

            JOIN reklet.suppliers s

                ON s.id = ms.supplier_id

            WHERE
                ms.material_id = %s

            ORDER BY
                s.name
            """,
            (material_id,),
            fetch=True
        )

        if not supplier_data.empty:

            st.dataframe(
                supplier_data,
                use_container_width=True,
                hide_index=True
            )

        suppliers = get_suppliers()

        if not suppliers.empty:

            supplier_map = {

                row["name"]:
                    int(row["id"])

                for _, row in suppliers.iterrows()
            }

            with st.form(
                f"add_supplier_material_{material_id}"
            ):

                supplier_name = st.selectbox(
                    "Supplier",
                    list(supplier_map.keys())
                )

                purchase_price = st.number_input(
                    "Purchase Price",
                    min_value=0.0,
                    value=0.0,
                    format="%.2f"
                )

                supplier_code = st.text_input(
                    "Supplier Code"
                )

                conditions = st.text_area(
                    "Conditions"
                )

                preferred = st.checkbox(
                    "Preferred Supplier"
                )

                submit = st.form_submit_button(
                    "Add Supplier"
                )

                if submit:

                    run_query(
                        """
                        INSERT INTO
                        reklet.material_suppliers
                        (
                            material_id,
                            supplier_id,
                            purchase_price,
                            supplier_code,
                            conditions,
                            is_preferred
                        )

                        VALUES
                        (%s,%s,%s,%s,%s,%s)

                        ON CONFLICT
                        (
                            material_id,
                            supplier_id
                        )

                        DO UPDATE SET

                            purchase_price =
                                EXCLUDED.purchase_price,

                            supplier_code =
                                EXCLUDED.supplier_code,

                            conditions =
                                EXCLUDED.conditions,

                            is_preferred =
                                EXCLUDED.is_preferred
                        """,
                        (
                            material_id,
                            supplier_map[
                                supplier_name
                            ],
                            purchase_price,
                            supplier_code,
                            conditions,
                            preferred
                        )
                    )

                    st.success(
                        "Supplier linked to material."
                    )

                    st.rerun()


    # ========================================================
    # GOODS RECEIPT
    # ========================================================

    st.markdown("---")

    st.subheader(
        "Goods Receipt"
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
                "Material",
                list(material_map.keys())
            )

            receipt_supplier = st.selectbox(
                "Supplier",
                [""] + list(
                    supplier_map.keys()
                )
            )

            receipt_quantity = st.number_input(
                "Quantity",
                min_value=0.0001,
                value=1.0,
                format="%.4f"
            )

            receipt_price = st.number_input(
                "Unit Price",
                min_value=0.0,
                value=0.0,
                format="%.2f"
            )

            submit = st.form_submit_button(
                "Post Receipt"
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
                    "Goods receipt posted."
                )

                st.rerun()


    # ========================================================
    # MATERIAL ISSUE
    # ========================================================

    st.markdown("---")

    st.subheader(
        "Material Issue to Production"
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
                "Material",
                list(material_map.keys())
            )

            issue_object = st.selectbox(
                "Object",
                list(object_map.keys())
            )

            issue_quantity = st.number_input(
                "Quantity",
                min_value=0.0001,
                value=1.0,
                format="%.4f"
            )

            submit = st.form_submit_button(
                "Issue to Production"
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
                        f"Available: {stock}"
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
                        "Material issued to production."
                    )

                    st.rerun()


    # ========================================================
    # MOVEMENT HISTORY
    # ========================================================

    st.markdown("---")

    st.subheader(
        "Material Movement"
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

        st.dataframe(
            movements,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# SUPPLIERS
# ============================================================

elif menu == "Suppliers":

    st.header(
        "Suppliers"
    )

    suppliers = get_suppliers()

    with st.expander(
        "Create Supplier",
        expanded=False
    ):

        with st.form(
            "create_supplier"
        ):

            name = st.text_input(
                "Name"
            )

            supplier_type = st.selectbox(
                "Type",
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
                "Contact Info"
            )

            submit = st.form_submit_button(
                "Create Supplier"
            )

            if submit:

                if not name.strip():

                    st.warning(
                        "Name is required."
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
                        "Supplier created."
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

        edited = st.data_editor(
            display,
            key="suppliers_editor",
            use_container_width=True
        )

        if st.button(
            "Save Supplier Changes"
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
                "Saved."
            )

            st.rerun()


        st.markdown("---")

        st.subheader(
            "Delete Supplier"
        )

        delete_map = {

            f"{row['id']} — {row['name']}":
                int(row["id"])

            for _, row in suppliers.iterrows()
        }

        delete_label = st.selectbox(
            "Supplier",
            list(delete_map.keys()),
            key="delete_supplier"
        )

        if st.button(
            "Delete Supplier"
        ):

            try:

                run_query(
                    """
                    DELETE FROM
                        reklet.suppliers

                    WHERE id = %s
                    """,
                    (
                        delete_map[
                            delete_label
                        ],
                    )
                )

                st.success(
                    "Supplier deleted."
                )

                st.rerun()

            except Exception as e:

                st.error(
                    "Supplier cannot be deleted."
                )

                st.code(
                    str(e)
                )


# ============================================================
# PRODUCTION
# ============================================================

elif menu == "Production":

    st.header(
        "Production"
    )

    objects = get_objects()

    if objects.empty:

        st.info(
            "No objects."
        )

    else:

        object_filter = st.selectbox(
            "Object",
            ["All Objects"]
            + [
                f"{row['id']} — "
                f"{row['object_name']}"

                for _, row in objects.iterrows()
            ]
        )

        query = """
        SELECT

            oi.id,

            o.object_name,

            c.name AS client_name,

            oi.item_name,

            oi.quantity_needed,

            oi.qty_new,

            oi.qty_production,

            oi.qty_ready,

            oi.qty_shipped,

            oi.qty_arrived,

            oi.qty_installing,

            oi.qty_installed,

            (
                oi.quantity_needed
                -
                oi.qty_installed
            ) AS remaining

        FROM reklet.object_items oi

        JOIN reklet.objects o
            ON o.id = oi.object_id

        LEFT JOIN reklet.clients c
            ON c.id = o.client_id

        WHERE
            (
                oi.qty_new > 0
                OR oi.qty_production > 0
            )
        """

        params = []

        if object_filter != "All Objects":

            object_id = int(
                object_filter.split(
                    " — "
                )[0]
            )

            query += """
                AND oi.object_id = %s
            """

            params.append(
                object_id
            )

        query += """
        ORDER BY
            o.object_name,
            oi.item_name
        """

        df = run_query(
            query,
            tuple(params),
            fetch=True
        )

        if df.empty:

            st.success(
                "No products waiting for production."
            )

        else:

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )

            st.markdown("---")

            st.subheader(
                "Production Action"
            )

            item_map = {

                f"{row['id']} — "
                f"{row['object_name']} — "
                f"{row['item_name']}":
                    int(row["id"])

                for _, row in df.iterrows()
            }

            selected_item = st.selectbox(
                "Product",
                list(item_map.keys())
            )

            item_id = item_map[
                selected_item
            ]

            item_row = df[
                df["id"] == item_id
            ].iloc[0]

            action = st.radio(
                "Action",
                [
                    "Start Production",
                    "Move to Ready"
                ],
                horizontal=True
            )

            max_qty = (

                safe_int(
                    item_row["qty_new"]
                )

                if action == "Start Production"

                else

                safe_int(
                    item_row["qty_production"]
                )
            )

            action_qty = st.number_input(
                "Quantity",
                min_value=1,
                max_value=(
                    max_qty
                    if max_qty > 0
                    else 1
                ),
                value=1
            )

            if st.button(
                "Apply Production Action"
            ):

                if action == "Start Production":

                    run_query(
                        """
                        UPDATE
                            reklet.object_items

                        SET

                            qty_new =
                                qty_new - %s,

                            qty_production =
                                qty_production + %s,

                            production_status =
                                'in_progress',

                            production_progress_pct =

                                CASE

                                    WHEN quantity_needed > 0

                                    THEN LEAST(
                                        100,
                                        ROUND(
                                            (
                                                qty_production
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
                            action_qty,
                            action_qty,
                            action_qty,
                            item_id
                        )
                    )

                else:

                    run_query(
                        """
                        UPDATE
                            reklet.object_items

                        SET

                            qty_production =
                                qty_production - %s,

                            qty_ready =
                                qty_ready + %s,

                            production_status =

                                CASE

                                    WHEN
                                        qty_production - %s <= 0

                                    THEN 'completed'

                                    ELSE 'in_progress'

                                END,

                            production_progress_pct =

                                CASE

                                    WHEN quantity_needed > 0

                                    THEN LEAST(
                                        100,
                                        ROUND(
                                            (
                                                quantity_needed
                                                -
                                                qty_new
                                                -
                                                (
                                                    qty_production
                                                    - %s
                                                )
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
                            action_qty,
                            action_qty,
                            action_qty,
                            action_qty,
                            item_id
                        )
                    )

                    run_query(
                        """
                        INSERT INTO
                            reklet.finished_goods
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

                        FROM
                            reklet.object_items

                        WHERE id = %s
                        """,
                        (
                            action_qty,
                            item_id
                        )
                    )

                st.success(
                    "Production updated."
                )

                st.rerun()


# ============================================================
# FINISHED GOODS
# ============================================================

elif menu == "Finished Goods":

    st.header(
        "Finished Goods"
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
            "No finished products."
        )

    else:

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        st.subheader(
            "Shipment / Delivery"
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
                "Finished Product",
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

                label = "Ship"

            else:

                action = "arrive"

                label = "Mark Arrived"

            qty = st.number_input(
                "Quantity",
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
                    "Updated."
                )

                st.rerun()


# ============================================================
# TRANSPORT & LOGISTICS
# ============================================================

elif menu == "Transport & Logistics":

    st.header(
        "Transport & Logistics"
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
            "No logistics data."
        )

    else:

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        st.subheader(
            "Object Shipment Details"
        )

        object_map = {

            f"{row['id']} — "
            f"{row['object_name']}":
                int(row["id"])

            for _, row in df.iterrows()
        }

        selected = st.selectbox(
            "Object",
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

        st.dataframe(
            detail,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# INSTALLATION
# ============================================================

elif menu == "Installation":

    st.header(
        "Installation"
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
            "No installation data."
        )

    else:

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        st.subheader(
            "Installation Action"
        )

        object_map = {

            f"{row['id']} — "
            f"{row['object_name']}":
                int(row["id"])

            for _, row in df.iterrows()
        }

        selected = st.selectbox(
            "Object",
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
                "Product",
                list(item_map.keys())
            )

            item_id = item_map[
                item_label
            ]

            item_row = items[
                items["id"] == item_id
            ].iloc[0]

            st.write(
                f"Arrived: "
                f"{safe_int(item_row['qty_arrived'])}"
            )

            st.write(
                f"Installing: "
                f"{safe_int(item_row['qty_installing'])}"
            )

            st.write(
                f"Installed: "
                f"{safe_int(item_row['qty_installed'])}"
            )

            action = st.radio(
                "Action",
                [
                    "Start Installation",
                    "Complete Installation"
                ],
                horizontal=True
            )

            if action == "Start Installation":

                available = safe_int(
                    item_row["qty_arrived"]
                )

            else:

                available = safe_int(
                    item_row["qty_installing"]
                )

            qty = st.number_input(
                "Quantity",
                min_value=1,
                max_value=(
                    available
                    if available > 0
                    else 1
                ),
                value=1
            )

            if st.button(
                "Apply Installation Action"
            ):

                if action == "Start Installation":

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
                    "Installation updated."
                )

                st.rerun()


# ============================================================
# PAYROLL
# ============================================================

elif menu == "Payroll":

    st.header(
        "Payroll"
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
            "No payroll records."
        )

    else:

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# REPORTS
# ============================================================

elif menu == "Reports":

    st.header(
        "Reports"
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
        "Clients",
        clients_count
    )

    c2.metric(
        "Objects",
        objects_count
    )

    c3.metric(
        "Products",
        products_count
    )

    c4.metric(
        "Materials",
        materials_count
    )


    st.markdown("---")


    # ========================================================
    # PRODUCTION REPORT
    # ========================================================

    st.subheader(
        "Production by Object"
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

        st.dataframe(
            production_report,
            use_container_width=True,
            hide_index=True
        )


    # ========================================================
    # STOCK REPORT
    # ========================================================

    st.markdown("---")

    st.subheader(
        "Warehouse Stock"
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

        st.dataframe(
            stock_report,
            use_container_width=True,
            hide_index=True
        )
