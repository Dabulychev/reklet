import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
import psycopg2
from datetime import date

# Set wide layout so the horizontal menu looks clean and neat
st.set_page_config(page_title="Reklet — Production Management", layout="wide")

# --- НАСТРОЙКА АВТОРИЗАЦИИ (Логин и Пароль) ---
# Логин: admin, Пароль: secret123
# Логин: operator, Пароль: secret123
config = {
    'credentials': {
        'usernames': {
            'admin': {
                'email': 'admin@reklet.com',
                'name': 'Administrator',
                'password': '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW'
            },
            'operator': {
                'email': 'operator@reklet.com',
                'name': 'Production Operator',
                'password': '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW'
            }
        }
    },
    'cookie': {
        'expiry_days': 30,
        'key': 'some_signature_key_reklet',
        'name': 'reklet_auth_cookie'
    }
}

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    cookie_expiry_days=config['cookie']['expiry_days']
)

name, authentication_status, username = authenticator.login('Login', 'sidebar')

if authentication_status == False:
    st.error('Incorrect username or password')
elif authentication_status == None:
    st.warning('Please enter your username and password to access the system')
    st.stop()
elif authentication_status == True:
    authenticator.logout('Logout', 'sidebar')
    st.sidebar.write(f'Welcome, *{name}*!')

# PostgreSQL connection settings in Supabase
DB_HOST = "db.lnkaohubtchmsiniepoc.supabase.co"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = "4$#J9aXBHumnr$u"

@st.cache_resource
def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def run_query(query, params=None, fetch=False):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if fetch:
            result = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return pd.DataFrame(result, columns=columns)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

# Database setup and schema migration
try:
    run_query("""
        CREATE TABLE IF NOT EXISTS reklet.material_transactions (
            id serial4 NOT NULL,
            material_id int4 NULL,
            supplier_id int4 NULL,
            object_id int4 NULL,
            operation_type text NOT NULL,
            quantity numeric NOT NULL,
            created_at timestamptz DEFAULT timezone('utc'::text, now()) NOT NULL,
            unit_price numeric(12, 2) NULL,
            waste_coefficient numeric(5, 2) DEFAULT 20.00 NULL,
            transaction_type varchar(10) NULL,
            CONSTRAINT material_transactions_pkey PRIMARY KEY (id)
        )
    """)
    
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS template_id INTEGER;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS item_name TEXT;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'New';")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS quantity_needed INTEGER DEFAULT 0;")
    
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS qty_new INTEGER DEFAULT 0;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS qty_production INTEGER DEFAULT 0;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS qty_ready INTEGER DEFAULT 0;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS qty_shipped INTEGER DEFAULT 0;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS qty_arrived INTEGER DEFAULT 0;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS qty_installing INTEGER DEFAULT 0;")
    run_query("ALTER TABLE reklet.object_items ADD COLUMN IF NOT EXISTS qty_installed INTEGER DEFAULT 0;")
    
    run_query("ALTER TABLE reklet.objects ADD COLUMN IF NOT EXISTS contract_date DATE;")
    run_query("ALTER TABLE reklet.objects ADD COLUMN IF NOT EXISTS production_start_date DATE;")
    run_query("ALTER TABLE reklet.objects ADD COLUMN IF NOT EXISTS production_end_date DATE;")
    run_query("ALTER TABLE reklet.objects ADD COLUMN IF NOT EXISTS installation_date DATE;")
    run_query("ALTER TABLE reklet.objects ADD COLUMN IF NOT EXISTS installation_end_date DATE;")
    
    run_query("ALTER TABLE reklet.suppliers ADD COLUMN IF NOT EXISTS contact_person TEXT;")
    run_query("ALTER TABLE reklet.suppliers ADD COLUMN IF NOT EXISTS phone TEXT;")
    run_query("ALTER TABLE reklet.suppliers ADD COLUMN IF NOT EXISTS email TEXT;")
    run_query("ALTER TABLE reklet.suppliers ADD COLUMN IF NOT EXISTS category TEXT;")
    run_query("ALTER TABLE reklet.suppliers ADD COLUMN IF NOT EXISTS conditions TEXT;")
except Exception:
    pass

st.title("Production & Logistics Management (Reklet)")
st.markdown("---")

# TOP HORIZONTAL MENU
menu_options = [
    "Clients",
    "Objects",
    "Product Templates",
    "Materials Warehouse",
    "Production",
    "Transport",
    "Installation",
    "Payroll Calculation",
    "Reports"
]

menu = st.radio("Navigation", menu_options, horizontal=True, label_visibility="collapsed")
st.markdown("---")

# 1. CLIENTS
if menu == "Clients":
    st.header("Clients Management")
    st.subheader("Clients Database (Editable)")
    try:
        df_clients = run_query("SELECT * FROM reklet.clients ORDER BY id", fetch=True)
        edited_clients = st.data_editor(df_clients, key="clients_editor", use_container_width=True, num_rows="fixed")
        
        if st.button("Save Changes to Database", key="save_clients"):
            for _, row in edited_clients.iterrows():
                run_query("UPDATE reklet.clients SET name = %s, contact_info = %s WHERE id = %s",
                          (row['name'], row['contact_info'], int(row['id'])))
            st.success("Changes successfully saved!")
            st.rerun()
    except Exception as e:
        st.info("No client data found or error: " + str(e))
        
    st.markdown("---")
    st.subheader("Add New Client")
    with st.form("form_add_client"):
        c_name = st.text_input("Company Name / Client")
        c_contact = st.text_area("Contact Info (Phone, Email, Address)")
        submitted_client = st.form_submit_button("Save Client")
        
        if submitted_client:
            if c_name:
                try:
                    run_query("INSERT INTO reklet.clients (name, contact_info) VALUES (%s, %s)", 
                              (c_name, c_contact))
                    st.success(f"Client '{c_name}' successfully added!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.warning("Please enter the company name.")

# 2. OBJECTS
elif menu == "Objects":
    st.header("Objects Management")
    
    obj_sub_tab = st.radio("Objects Sub-menu", ["Objects List & Create", "Object Content & Printing", "Material Requirements Calculation"], horizontal=True)
    st.markdown("---")
    
    try:
        clients_df = run_query("SELECT id, name FROM reklet.clients", fetch=True)
        client_dict = {row['name']: int(row['id']) for _, row in clients_df.iterrows()} if not clients_df.empty else {}
    except:
        client_dict = {}

    if obj_sub_tab == "Objects List & Create":
        st.subheader("Objects Database (Editable)")
        try:
            df_objects = run_query("SELECT * FROM reklet.objects ORDER BY id", fetch=True)
            edited_objects = st.data_editor(df_objects, key="objects_editor", use_container_width=True)
            
            if st.button("Save Changes to Database", key="save_objects"):
                for _, row in edited_objects.iterrows():
                    run_query("""UPDATE reklet.objects SET 
                                object_name = %s, address = %s, phone = %s, contact_person = %s, 
                                notes = %s, transport_distance_km = %s, delivery_cost = %s,
                                contract_date = %s, production_start_date = %s, production_end_date = %s,
                                installation_date = %s, installation_end_date = %s
                                WHERE id = %s""",
                              (row['object_name'], row['address'], row['phone'], row['contact_person'],
                               row['notes'], row['transport_distance_km'], row['delivery_cost'],
                               row['contract_date'] if pd.notna(row['contract_date']) else None,
                               row['production_start_date'] if pd.notna(row['production_start_date']) else None,
                               row['production_end_date'] if pd.notna(row['production_end_date']) else None,
                               row['installation_date'] if pd.notna(row['installation_date']) else None,
                               row['installation_end_date'] if pd.notna(row['installation_end_date']) else None,
                               int(row['id'])))
                st.success("Changes successfully saved!")
                st.rerun()
        except Exception as e:
            st.info("No objects found or error: " + str(e))

        st.markdown("---")
        st.subheader("Create New Object")
        
        if not client_dict:
            st.warning("Please add at least one client first in the 'Clients' tab.")
        
        with st.form("form_create_object"):
            selected_client = st.selectbox("Select Client", list(client_dict.keys()) if client_dict else [])
            client_id = client_dict.get(selected_client)
            
            obj_name = st.text_input("Object Name")
            obj_address = st.text_input("Exact Address")
            
            col1, col2 = st.columns(2)
            with col1:
                obj_phone = st.text_input("Phone")
                obj_dist = st.number_input("Transport Distance (km)", min_value=0.0, value=0.0)
            with col2:
                obj_contact = st.text_input("Contact Person")
                obj_delivery_cost = st.number_input("Delivery Cost", min_value=0.0, value=0.0)
            
            obj_notes = st.text_area("Notes")
            
            st.markdown("#### Project Schedule & Dates")
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                obj_contract_date = st.date_input("Contract Signing Date", value=None)
                obj_prod_start = st.date_input("Production Start Date", value=None)
                obj_prod_end = st.date_input("Production End Date", value=None)
            with d_col2:
                obj_install_date = st.date_input("Installation Date", value=None)
                obj_install_end = st.date_input("Installation End Date", value=None)
            
            submitted_object = st.form_submit_button("Create Object")
            
            if submitted_object:
                if client_id and obj_name:
                    try:
                        run_query(
                            """INSERT INTO reklet.objects 
                            (client_id, object_name, address, phone, contact_person, notes, transport_distance_km, delivery_cost,
                             contract_date, production_start_date, production_end_date, installation_date, installation_end_date) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (int(client_id), obj_name, obj_address, obj_phone, obj_contact, obj_notes, obj_dist, obj_delivery_cost,
                             obj_contract_date, obj_prod_start, obj_prod_end, obj_install_date, obj_install_end)
                        )
                        st.success(f"Object '{obj_name}' successfully created!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error creating object: {e}")
                else:
                    st.warning("Please fill in the object name and select a client.")

    elif obj_sub_tab == "Object Content & Printing":
        st.subheader("Object Content & Printing Document")
        
        try:
            objects_full_df = run_query("""
                SELECT o.id, o.object_name, o.address, c.name as client_name,
                       o.contract_date, o.production_start_date, o.production_end_date, o.installation_date, o.installation_end_date
                FROM reklet.objects o 
                LEFT JOIN reklet.clients c ON o.client_id = c.id 
                ORDER BY o.id
            """, fetch=True)
        except:
            objects_full_df = pd.DataFrame()

        if not objects_full_df.empty:
            obj_selection_dict = {f"ID {row['id']} — {row['object_name']} (Client: {row['client_name']})": int(row['id']) for _, row in objects_full_df.iterrows()}
            selected_obj_label = st.selectbox("Select object for content and printing", list(obj_selection_dict.keys()), key="select_obj_content")
            current_obj_id = obj_selection_dict[selected_obj_label]
            
            selected_obj_row = objects_full_df[objects_full_df['id'] == current_obj_id].iloc[0]
            current_client_name = selected_obj_row['client_name']
            
            st.markdown("---")
            st.markdown(f"### Items list for object: **{selected_obj_row['object_name']}**")
            
            try:
                df_obj_items = run_query("SELECT id, item_name, quantity, qty_new, qty_production, qty_ready, qty_shipped, qty_arrived, qty_installing, qty_installed, template_id FROM reklet.object_items WHERE object_id = %s ORDER BY id", (int(current_obj_id),), fetch=True)
                if not df_obj_items.empty:
                    df_display = df_obj_items.copy()
                    df_display.insert(0, "No.", range(1, len(df_display) + 1))
                    df_display_editable = df_display.drop(columns=['id', 'template_id'])
                    
                    edited_display = st.data_editor(df_display_editable, key=f"obj_items_editor_{current_obj_id}", use_container_width=True)
                    
                    if st.button("Save Changes in Items", key=f"save_obj_items_{current_obj_id}"):
                        for idx, row in edited_display.iterrows():
                            real_id = int(df_obj_items.iloc[idx]['id'])
                            total_q = int(row['qty_new']) + int(row['qty_production']) + int(row['qty_ready']) + int(row['qty_shipped']) + int(row['qty_arrived']) + int(row['qty_installing']) + int(row['qty_installed'])
                            run_query("""UPDATE reklet.object_items SET 
                                        item_name = %s, quantity = %s, 
                                        qty_new = %s, qty_production = %s, qty_ready = %s, qty_shipped = %s, qty_arrived = %s, qty_installing = %s, qty_installed = %s 
                                        WHERE id = %s""",
                                      (row['item_name'], total_q, int(row['qty_new']), int(row['qty_production']), int(row['qty_ready']), int(row['qty_shipped']), int(row['qty_arrived']), int(row['qty_installing']), int(row['qty_installed']), real_id))
                        st.success("Changes successfully saved!")
                        st.rerun()
                        
                    col_del1, col_del2 = st.columns([2, 1])
                    with col_del1:
                        item_to_del = st.selectbox("Delete Item", df_display['No.'].astype(str) + " — " + df_obj_items['item_name'], key=f"del_item_sel_{current_obj_id}")
                    with col_del2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("Delete Selected Item", key=f"btn_del_item_{current_obj_id}"):
                            selected_index = int(item_to_del.split(" — ")[0]) - 1
                            item_id_to_del = int(df_obj_items.iloc[selected_index]['id'])
                            run_query("DELETE FROM reklet.object_items WHERE id = %s", (item_id_to_del,))
                            st.success("Item successfully deleted!")
                            st.rerun()
                else:
                    st.info("No items added to this object yet.")
            except Exception as e:
                st.info("Error loading items: " + str(e))

            st.markdown("---")
            st.markdown("### Add Item from Templates")
            
            filter_by_client = st.checkbox("Filter by object client", value=True, key=f"filter_client_{current_obj_id}")
            
            try:
                if filter_by_client and current_client_name:
                    templates_df = run_query(
                        "SELECT id, name, client_name FROM reklet.product_templates WHERE client_name = %s OR client_name IS NULL OR client_name = '' ORDER BY id", 
                        (current_client_name,), fetch=True
                    )
                else:
                    templates_df = run_query("SELECT id, name, client_name FROM reklet.product_templates ORDER BY id", fetch=True)
                    
                templates_dict = {}
                if not templates_df.empty:
                    for _, row in templates_df.iterrows():
                        c_name = row['client_name'] if pd.notna(row['client_name']) and row['client_name'] != "" else "No Client"
                        templates_dict[f"{c_name} — {row['name']}"] = int(row['id'])
            except:
                templates_dict = {}

            if templates_dict:
                with st.form("form_add_item_to_obj"):
                    selected_template_label = st.selectbox("Product Template", list(templates_dict.keys()), key="target_template_add")
                    template_id = templates_dict[selected_template_label]
                    item_custom_name = selected_template_label.split(" — ", 1)[1]
                    
                    item_qty = st.number_input("Total Quantity", min_value=1, value=1, key="input_item_qty")
                    
                    submitted_add_item = st.form_submit_button("Add Item to Object")
                    
                    if submitted_add_item:
                        try:
                            run_query(
                                "INSERT INTO reklet.object_items (object_id, template_id, item_name, quantity, quantity_needed, qty_new, qty_production, qty_ready, qty_shipped, qty_arrived, qty_installing, qty_installed, status) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 0, 0, 0, 'New')",
                                (int(current_obj_id), int(template_id), item_custom_name, int(item_qty), int(item_qty), int(item_qty))
                            )
                            st.success("Item successfully added!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
            else:
                st.warning("No templates available for the selected filter. Check Product Templates section.")

            st.markdown("---")
            st.subheader("Printable Order / Specification Form")
            
            try:
                print_items_df = run_query("SELECT item_name, quantity, status FROM reklet.object_items WHERE object_id = %s ORDER BY id", (int(current_obj_id),), fetch=True)
            except:
                print_items_df = pd.DataFrame()
            
            rows_html = ""
            if not print_items_df.empty:
                for idx, row in print_items_df.iterrows():
                    rows_html += f"""
                    <tr>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{idx + 1}</td>
                        <td style="border: 1px solid #ddd; padding: 8px;">{row['item_name']}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{row['quantity']}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">{row['status']}</td>
                    </tr>
                    """
            else:
                rows_html = "<tr><td colspan='4' style='text-align: center; padding: 10px;'>Items list is empty</td></tr>"

            print_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Item Specification — {selected_obj_row['object_name']}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; color: #000; }}
                    h2 {{ text-align: center; }}
                    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                    th {{ background-color: #f2f2f2; border: 1px solid #ddd; padding: 10px; text-align: center; }}
                </style>
            </head>
            <body>
                <h2>OBJECT ITEM SPECIFICATION</h2>
                <hr style="margin-bottom: 20px;">
                <p><b>Client:</b> {selected_obj_row['client_name']}</p>
                <p><b>Object:</b> {selected_obj_row['object_name']}</p>
                <p><b>Address:</b> {selected_obj_row['address']}</p>
                <p><b>Contract Date:</b> {selected_obj_row['contract_date'] if pd.notna(selected_obj_row['contract_date']) else '—'}</p>
                <p><b>Production:</b> from {selected_obj_row['production_start_date'] if pd.notna(selected_obj_row['production_start_date']) else '—'} to {selected_obj_row['production_end_date'] if pd.notna(selected_obj_row['production_end_date']) else '—'}</p>
                <p><b>Installation:</b> from {selected_obj_row['installation_date'] if pd.notna(selected_obj_row['installation_date']) else '—'} to {selected_obj_row['installation_end_date'] if pd.notna(selected_obj_row['installation_end_date']) else '—'}</p>
                <br>
                <h3>Items List:</h3>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 60px;">No.</th>
                            <th>Item Name</th>
                            <th style="width: 100px;">Quantity</th>
                            <th style="width: 120px;">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
                <br><br><br>
                <table style="width: 100%; border: none; margin-top: 40px;">
                  <tr>
                    <td><b>Handed over by:</b> ____________________</td>
                    <td style="text-align: right;"><b>Received by:</b> ____________________</td>
                  </tr>
                </table>
            </body>
            </html>
            """
            
            st.download_button(
                label="Download Specification for Printing (HTML)",
                data=print_html,
                file_name=f"Specification_{selected_obj_row['object_name']}.html",
                mime="text/html"
            )
        else:
            st.info("Please add objects in the Objects Database first.")

    else: # Material Requirements Calculation
        st.subheader("Material Requirements Calculation per Object")
        
        try:
            objects_full_df = run_query("""
                SELECT o.id, o.object_name, c.name as client_name
                FROM reklet.objects o 
                LEFT JOIN reklet.clients c ON o.client_id = c.id 
                ORDER BY o.id
            """, fetch=True)
        except:
            objects_full_df = pd.DataFrame()

        if not objects_full_df.empty:
            obj_selection_dict = {f"ID {row['id']} — {row['object_name']} (Client: {row['client_name']})": int(row['id']) for _, row in objects_full_df.iterrows()}
            selected_obj_label = st.selectbox("Select object for calculation", list(obj_selection_dict.keys()), key="select_obj_req")
            current_obj_id = obj_selection_dict[selected_obj_label]
            
            st.markdown("---")
            try:
                materials_req_query = """
                    SELECT 
                        m.name AS "Material",
                        u.name AS "Unit",
                        SUM(oi.quantity * tm.quantity * tm.waste_coefficient) AS "Total Required",
                        m.stock_quantity AS "In Stock"
                    FROM reklet.object_items oi
                    JOIN reklet.template_materials tm ON oi.template_id = tm.template_id
                    JOIN reklet.materials m ON tm.material_id = m.id
                    LEFT JOIN reklet.units u ON m.unit_id = u.id
                    WHERE oi.object_id = %s
                    GROUP BY m.id, m.name, u.name, m.stock_quantity
                    ORDER BY m.name
                """
                req_df = run_query(materials_req_query, (int(current_obj_id),), fetch=True)
                if not req_df.empty:
                    req_df["Deficit / Balance"] = req_df["In Stock"] - req_df["Total Required"]
                    st.dataframe(req_df, use_container_width=True)
                else:
                    st.info("To calculate, add items to the object in 'Object Content & Printing' and set up their specification in 'Product Templates'.")
            except Exception as e:
                st.info("Requirements calculation temporarily unavailable: " + str(e))
        else:
            st.info("Please add objects in the Objects Database first.")

# 3. PRODUCT TEMPLATES & SPECIFICATIONS
elif menu == "Product Templates":
    st.header("Product Templates & Specifications Directory")
    
    try:
        clients_df = run_query("SELECT name FROM reklet.clients", fetch=True)
        client_names = clients_df['name'].tolist() if not clients_df.empty else []
    except:
        client_names = []

    template_tab = st.radio("Operation Mode", ["Templates List", "Add Template", "Edit / Delete", "Item Composition (Materials)"], horizontal=True)
    st.markdown("---")

    if template_tab == "Templates List":
        st.subheader("Current Product Templates Database")
        try:
            df_templates = run_query("SELECT * FROM reklet.product_templates ORDER BY id", fetch=True)
            if not df_templates.empty:
                st.dataframe(df_templates, use_container_width=True)
            else:
                st.info("Templates list is empty.")
        except Exception as e:
            st.info("Templates list is empty or error: " + str(e))

    elif template_tab == "Add Template":
        st.subheader("Add New Product Template")
        with st.form("form_add_template"):
            t_name = st.text_input("Product Name (e.g., Cash Desk Sign 400x600 mm)")
            t_type = st.selectbox("Product Type", ["recurrent", "custom"])
            
            if client_names:
                t_client = st.selectbox("Client Name", ["— No Client —"] + client_names)
            else:
                t_client = st.text_input("Client Name")
                
            category_options = ["Interior Signage", "Exterior Signage", "Other..."]
            selected_category_option = st.selectbox("Category / Group", category_options)
            
            if selected_category_option == "Other...":
                t_category = st.text_input("Enter Custom Category")
            else:
                t_category = selected_category_option
            
            submitted_template = st.form_submit_button("Save Product Template")
            
            if submitted_template:
                if t_name:
                    final_client = None if (t_client == "— No Client —" or not t_client) else t_client
                    try:
                        run_query(
                            """INSERT INTO reklet.product_templates (name, type, client_name, category) 
                            VALUES (%s, %s, %s, %s)""",
                            (t_name, t_type, final_client, t_category)
                        )
                        st.success(f"Product template '{t_name}' successfully added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.warning("Please enter the product name.")

    elif template_tab == "Edit / Delete":
        st.subheader("Edit or Delete Product Template")
        try:
            df_templates = run_query("SELECT * FROM reklet.product_templates ORDER BY id", fetch=True)
            if not df_templates.empty:
                template_options = {}
                for _, row in df_templates.iterrows():
                    c_name = row['client_name'] if pd.notna(row['client_name']) and row['client_name'] != "" else "No Client"
                    label = f"{c_name} — {row['name']} (ID {row['id']})"
                    template_options[label] = int(row['id'])

                selected_t_label = st.selectbox("Select template to modify:", list(template_options.keys()))
                selected_t_id = template_options[selected_t_label]
                
                t_row = df_templates[df_templates['id'] == selected_t_id].iloc[0]

                with st.form("form_edit_template"):
                    e_t_name = st.text_input("Product Name", value=t_row['name'])
                    
                    cur_type = t_row['type'] if pd.notna(t_row['type']) else "recurrent"
                    type_opts = ["recurrent", "custom"]
                    e_t_type = st.selectbox("Product Type", type_opts, index=type_opts.index(cur_type) if cur_type in type_opts else 0)
                    
                    cur_client = t_row['client_name'] if pd.notna(t_row['client_name']) else ""
                    client_list_opts = ["— No Client —"] + client_names
                    c_idx = client_list_opts.index(cur_client) if cur_client in client_list_opts else 0
                    e_t_client = st.selectbox("Client Name", client_list_opts, index=c_idx)
                    
                    e_t_category = st.text_input("Category / Group", value=str(t_row['category']) if pd.notna(t_row['category']) else "")
                    
                    col_upd, col_del = st.columns(2)
                    with col_upd:
                        update_btn = st.form_submit_button("Save Changes")
                    with col_del:
                        delete_btn = st.form_submit_button("Delete Template", type="primary")

                    if update_btn:
                        fin_client = None if (e_t_client == "— No Client —" or not e_t_client) else e_t_client
                        try:
                            run_query("""UPDATE reklet.product_templates SET 
                                        name = %s, type = %s, client_name = %s, category = %s 
                                        WHERE id = %s""",
                                      (e_t_name, e_t_type, fin_client, e_t_category, selected_t_id))
                            st.success("Template successfully updated!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                    if delete_btn:
                        try:
                            run_query("DELETE FROM reklet.template_materials WHERE template_id = %s", (selected_t_id,))
                            run_query("DELETE FROM reklet.product_templates WHERE id = %s", (selected_t_id,))
                            st.success("Template successfully deleted!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
            else:
                st.info("No templates available for editing.")
        except Exception as e:
            st.info("Error loading templates: " + str(e))

    else: # Item Composition (Materials)
        st.subheader("Material Specification for Product Template")
        st.markdown("Specify which materials make up the selected product template (e.g., plastic, film, screw).")
        
        try:
            templates_df = run_query("SELECT id, name, client_name FROM reklet.product_templates ORDER BY id", fetch=True)
            templates_dict = {}
            if not templates_df.empty:
                for _, row in templates_df.iterrows():
                    c_name = row['client_name'] if pd.notna(row['client_name']) and row['client_name'] != "" else "No Client"
                    label = f"{c_name} — {row['name']}"
                    templates_dict[label] = int(row['id'])
        except:
            templates_dict = {}

        try:
            materials_df = run_query("SELECT id, name FROM reklet.materials ORDER BY id", fetch=True)
            materials_dict = {row['name']: int(row['id']) for _, row in materials_df.iterrows()} if not materials_df.empty else {}
            material_id_to_name = {int(row['id']): row['name'] for _, row in materials_df.iterrows()} if not materials_df.empty else {}
        except:
            materials_dict = {}
            material_id_to_name = {}

        if templates_dict:
            selected_t_label = st.selectbox("Select Product Template", list(templates_dict.keys()), key="spec_template_select")
            current_t_id = templates_dict[selected_t_label]
            
            st.markdown("---")
            st.markdown("#### Current Materials List in Product:")
            
            try:
                spec_df = run_query("SELECT id, material_id, quantity, waste_coefficient FROM reklet.template_materials WHERE template_id = %s ORDER BY id", (int(current_t_id),), fetch=True)
                if not spec_df.empty:
                    spec_display = spec_df.copy()
                    spec_display['material_name'] = spec_display['material_id'].map(material_id_to_name)
                    spec_display.insert(0, "No.", range(1, len(spec_display) + 1))
                    
                    display_spec_cols = ['No.', 'material_name', 'quantity', 'waste_coefficient']
                    edited_spec = st.data_editor(
                        spec_display[display_spec_cols],
                        key=f"spec_editor_{current_t_id}",
                        use_container_width=True,
                        column_config={
                            "material_name": st.column_config.SelectboxColumn("Material", options=list(materials_dict.keys()), required=True),
                            "quantity": st.column_config.NumberColumn("Quantity (per 1 pc)", format="%.4f"),
                            "waste_coefficient": st.column_config.NumberColumn("Waste Coeff.", format="%.2f")
                        }
                    )
                    
                    if st.button("Save Changes in Composition", key=f"save_spec_{current_t_id}"):
                        for idx, row in edited_spec.iterrows():
                            real_id = int(spec_df.iloc[idx]['id'])
                            new_mat_id = materials_dict.get(row['material_name'])
                            run_query("UPDATE reklet.template_materials SET material_id = %s, quantity = %s, waste_coefficient = %s WHERE id = %s",
                                      (int(new_mat_id), float(row['quantity']), float(row['waste_coefficient']), real_id))
                        st.success("Product composition successfully updated!")
                        st.rerun()
                        
                    col_s_del1, col_s_del2 = st.columns([2, 1])
                    with col_s_del1:
                        mat_to_del_sel = st.selectbox("Remove Material from Product", spec_display['No.'].astype(str) + " — " + spec_display['material_name'], key=f"del_mat_spec_{current_t_id}")
                    with col_s_del2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("Remove Selected Material", key=f"btn_del_mat_spec_{current_t_id}"):
                            sel_idx = int(mat_to_del_sel.split(" — ")[0]) - 1
                            del_row_id = int(spec_df.iloc[sel_idx]['id'])
                            run_query("DELETE FROM reklet.template_materials WHERE id = %s", (del_row_id,))
                            st.success("Material removed from product composition!")
                            st.rerun()
                else:
                    st.info("No materials added to this product's specification yet.")
            except Exception as e:
                st.info("Error loading specification: " + str(e))

            st.markdown("---")
            st.markdown("#### Add Material to Product")
            if materials_dict:
                with st.form(f"form_add_mat_to_spec_{current_t_id}"):
                    chosen_mat_name = st.selectbox("Select Material", list(materials_dict.keys()))
                    chosen_mat_id = materials_dict[chosen_mat_name]
                    
                    col_q1, col_q2 = st.columns(2)
                    with col_q1:
                        add_qty = st.number_input("Quantity per 1 Item", min_value=0.0001, value=1.0000, format="%.4f")
                    with col_q2:
                        add_waste = st.number_input("Waste Coefficient", min_value=1.00, value=1.20, step=0.05)
                        
                    submitted_add_spec = st.form_submit_button("Add Material to Product")
                    
                    if submitted_add_spec:
                        try:
                            run_query(
                                "INSERT INTO reklet.template_materials (template_id, material_id, quantity, waste_coefficient) VALUES (%s, %s, %s, %s)",
                                (int(current_t_id), int(chosen_mat_id), float(add_qty), float(add_waste))
                            )
                            st.success(f"Material '{chosen_mat_name}' successfully added to product composition!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
            else:
                st.warning("Please add materials in 'Materials Warehouse' first.")
        else:
            st.warning("Please add product templates in 'Add Template' or 'Templates List' first.")

# 4. MATERIALS WAREHOUSE
elif menu == "Materials Warehouse":
    st.header("Materials & Inventory Management")
    
    mat_sub_tab = st.radio(
        "Select Sub-section:", 
        ["Stock Balance", "Incoming Invoices", "Suppliers"], 
        horizontal=True
    )
    st.markdown("---")

    if mat_sub_tab == "Stock Balance":
        try:
            suppliers_df = run_query("SELECT id, name FROM reklet.suppliers", fetch=True)
            supplier_dict = {row['name']: int(row['id']) for _, row in suppliers_df.iterrows()} if not suppliers_df.empty else {}
            supplier_id_to_name = {int(row['id']): row['name'] for _, row in suppliers_df.iterrows()} if not suppliers_df.empty else {}
        except:
            supplier_dict = {}
            supplier_id_to_name = {}

        try:
            units_df = run_query("SELECT id, name FROM reklet.units", fetch=True)
            unit_dict = {row['name']: int(row['id']) for _, row in units_df.iterrows()} if not units_df.empty else {}
            unit_id_to_name = {int(row['id']): row['name'] for _, row in units_df.iterrows()} if not units_df.empty else {}
        except:
            unit_dict = {}
            unit_id_to_name = {}

        mat_action = st.radio("Warehouse Action:", ["Materials List", "Add Material", "Edit / Delete"], horizontal=True, key="mat_action_radio")
        st.markdown("---")

        if mat_action == "Materials List":
            st.subheader("Current Stock Balance")
            try:
                df_materials = run_query("SELECT * FROM reklet.materials ORDER BY id", fetch=True)
                if not df_materials.empty:
                    df_materials['supplier_name'] = df_materials['supplier_id'].map(supplier_id_to_name)
                    df_materials['unit_name'] = df_materials['unit_id'].map(unit_id_to_name)
                    
                    display_cols = ['id', 'name', 'supplier_name', 'unit_name', 'cost_per_unit', 'stock_quantity', 'default_waste_coefficient']
                    df_display = df_materials[[c for c in display_cols if c in df_materials.columns]]
                    st.dataframe(df_display, use_container_width=True)
                else:
                    st.info("Materials warehouse is empty.")
            except Exception as e:
                st.info("Error loading materials: " + str(e))

        elif mat_action == "Add Material":
            st.subheader("Add New Material")
            with st.form("form_add_material"):
                m_name = st.text_input("Material Name")
                
                supplier_names = list(supplier_dict.keys())
                selected_supplier = st.selectbox("Supplier", ["— No Supplier —"] + supplier_names)
                m_supplier_id = supplier_dict.get(selected_supplier) if selected_supplier != "— No Supplier —" else None
                
                unit_names = list(unit_dict.keys())
                if unit_names:
                    m_unit_name = st.selectbox("Unit", unit_names)
                    m_unit_id = unit_dict[m_unit_name]
                else:
                    st.warning("The 'units' table is empty.")
                    m_unit_id = None

                m_cost = st.number_input("Cost per Unit", min_value=0.0, format="%.2f")
                m_stock = st.number_input("Stock Quantity", min_value=0.0, value=0.0)
                m_waste = st.number_input("Waste Coefficient", min_value=1.0, value=1.20, step=0.05)
                
                submitted_material = st.form_submit_button("Add Material")
                
                if submitted_material:
                    if m_name and m_unit_id:
                        try:
                            run_query(
                                "INSERT INTO reklet.materials (supplier_id, name, unit_id, cost_per_unit, stock_quantity, default_waste_coefficient) VALUES (%s, %s, %s, %s, %s, %s)",
                                (int(m_supplier_id) if m_supplier_id is not None else None, m_name, int(m_unit_id), float(m_cost), float(m_stock), float(m_waste))
                            )
                            st.success(f"Material '{m_name}' successfully added!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.warning("Please fill in the material name and select a unit.")

        else: # Edit / Delete Material
            st.subheader("Edit or Delete Material")
            try:
                materials_list_df = run_query("SELECT * FROM reklet.materials ORDER BY id", fetch=True)
                if not materials_list_df.empty:
                    mat_options = {f"{row['id']} — {row['name']}": int(row['id']) for _, row in materials_list_df.iterrows()}
                    selected_mat_label = st.selectbox("Select material:", list(mat_options.keys()))
                    selected_mat_id = mat_options[selected_mat_label]
                    
                    m_row = materials_list_df[materials_list_df['id'] == selected_mat_id].iloc[0]

                    with st.form("form_edit_material"):
                        e_m_name = st.text_input("Material Name", value=m_row['name'])
                        
                        cur_sup_id = m_row['supplier_id'] if pd.notna(m_row['supplier_id']) else None
                        sup_names_opts = ["— No Supplier —"] + list(supplier_dict.keys())
                        cur_sup_name = supplier_id_to_name.get(int(cur_sup_id), "— No Supplier —") if cur_sup_id else "— No Supplier —"
                        e_m_sup = st.selectbox("Supplier", sup_names_opts, index=sup_names_opts.index(cur_sup_name) if cur_sup_name in sup_names_opts else 0)
                        
                        cur_unit_id = m_row['unit_id'] if pd.notna(m_row['unit_id']) else None
                        unit_names_opts = list(unit_dict.keys())
                        cur_unit_name = unit_id_to_name.get(int(cur_unit_id), unit_names_opts[0] if unit_names_opts else "") if cur_unit_id else (unit_names_opts[0] if unit_names_opts else "")
                        e_m_unit = st.selectbox("Unit", unit_names_opts, index=unit_names_opts.index(cur_unit_name) if cur_unit_name in unit_names_opts else 0)
                        
                        e_m_cost = st.number_input("Cost per Unit", min_value=0.0, value=float(m_row['cost_per_unit']) if pd.notna(m_row['cost_per_unit']) else 0.0, format="%.2f")
                        e_m_stock = st.number_input("Stock Quantity", min_value=0.0, value=float(m_row['stock_quantity']) if pd.notna(m_row['stock_quantity']) else 0.0)
                        e_m_waste = st.number_input("Waste Coefficient", min_value=1.0, value=float(m_row['default_waste_coefficient']) if pd.notna(m_row['default_waste_coefficient']) else 1.20, step=0.05)
                        
                        col_upd_m, col_del_m = st.columns(2)
                        with col_upd_m:
                            update_m_btn = st.form_submit_button("Save Changes")
                        with col_del_m:
                            delete_m_btn = st.form_submit_button("Delete Material", type="primary")

                        if update_m_btn:
                            new_sup_id = supplier_dict.get(e_m_sup) if e_m_sup != "— No Supplier —" else None
                            new_unit_id = unit_dict.get(e_m_unit)
                            try:
                                run_query("""UPDATE reklet.materials SET 
                                            name = %s, supplier_id = %s, unit_id = %s, cost_per_unit = %s, stock_quantity = %s, default_waste_coefficient = %s 
                                            WHERE id = %s""",
                                          (e_m_name, int(new_sup_id) if new_sup_id is not None else None, int(new_unit_id) if new_unit_id is not None else None, 
                                           float(e_m_cost), float(e_m_stock), float(e_m_waste), selected_mat_id))
                                st.success("Material successfully updated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

                        if delete_m_btn:
                            try:
                                used_check = run_query("SELECT COUNT(*) FROM reklet.template_materials WHERE material_id = %s", (selected_mat_id,), fetch=True)
                                cnt = used_check.iloc[0, 0] if not used_check.empty else 0
                                
                                if cnt > 0:
                                    st.error(f"Cannot delete material as it is used in {cnt} product templates!")
                                else:
                                    run_query("DELETE FROM reklet.materials WHERE id = %s", (selected_mat_id,))
                                    st.success("Material successfully deleted!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                else:
                    st.info("No materials available for editing.")
            except Exception as e:
                st.info("Error loading materials: " + str(e))

    elif mat_sub_tab == "Incoming Invoices":
        st.subheader("Register Incoming Invoice (Material Receipts)")
        st.markdown("Select a supplier, specify incoming materials, quantity, and price. Stock balances will update automatically.")

        try:
            suppliers_df = run_query("SELECT id, name FROM reklet.suppliers ORDER BY name", fetch=True)
            sup_dict = {row['name']: int(row['id']) for _, row in suppliers_df.iterrows()} if not suppliers_df.empty else {}
        except:
            sup_dict = {}

        try:
            materials_df = run_query("SELECT id, name, cost_per_unit FROM reklet.materials ORDER BY name", fetch=True)
            mat_dict = {row['name']: int(row['id']) for _, row in materials_df.iterrows()} if not materials_df.empty else {}
            mat_costs = {int(row['id']): float(row['cost_per_unit']) for _, row in materials_df.iterrows()} if not materials_df.empty else {}
        except:
            mat_dict = {}
            mat_costs = {}

        if not sup_dict:
            st.warning("Please add at least one supplier in the 'Suppliers' tab first.")
        elif not mat_dict:
            st.warning("Please add materials in the 'Stock Balance' tab first.")
        else:
            with st.form("form_purchase_invoice"):
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    selected_sup_name = st.selectbox("Supplier", list(sup_dict.keys()))
                    sup_id = sup_dict[selected_sup_name]
                with col_p2:
                    invoice_date = st.date_input("Receipt Date", value=date.today())

                st.markdown("---")
                st.markdown("#### Invoice Items:")
                
                chosen_mat_name = st.selectbox("Material", list(mat_dict.keys()))
                chosen_mat_id = mat_dict[chosen_mat_name]
                
                default_price = mat_costs.get(chosen_mat_id, 0.0)

                col_q1, col_q2 = st.columns(2)
                with col_q1:
                    incoming_qty = st.number_input("Quantity", min_value=0.0001, value=1.0000, format="%.4f")
                with col_q2:
                    incoming_price = st.number_input("Unit Price", min_value=0.0, value=default_price, format="%.2f")

                submitted_invoice = st.form_submit_button("Process Incoming Invoice")

                if submitted_invoice:
                    try:
                        run_query(
                            """INSERT INTO reklet.material_transactions 
                            (material_id, supplier_id, operation_type, quantity, unit_price, transaction_type) 
                            VALUES (%s, %s, 'purchase', %s, %s, 'in')""",
                            (chosen_mat_id, sup_id, float(incoming_qty), float(incoming_price))
                        )
                        
                        run_query(
                            """UPDATE reklet.materials 
                            SET stock_quantity = stock_quantity + %s, cost_per_unit = %s 
                            WHERE id = %s""",
                            (float(incoming_qty), float(incoming_price), chosen_mat_id)
                        )
                        
                        st.success(f"Incoming invoice successfully processed! Material '{chosen_mat_name}' in quantity {incoming_qty} added to stock.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error processing invoice: {e}")

            st.markdown("---")
            st.subheader("Receipt History")
            try:
                history_df = run_query("""
                    SELECT t.id, t.created_at AS "Date", s.name AS "Supplier", m.name AS "Material", 
                           t.quantity AS "Quantity", t.unit_price AS "Unit Price"
                    FROM reklet.material_transactions t
                    LEFT JOIN reklet.suppliers s ON t.supplier_id = s.id
                    LEFT JOIN reklet.materials m ON t.material_id = m.id
                    WHERE t.operation_type = 'purchase'
                    ORDER BY t.id DESC
                """, fetch=True)
                if not history_df.empty:
                    st.dataframe(history_df, use_container_width=True)
                else:
                    st.info("Receipt history is empty.")
            except Exception as e:
                st.info("History currently unavailable: " + str(e))

    else: # Suppliers
        st.subheader("Suppliers Management")
        
        try:
            df_suppliers = run_query("SELECT id, name AS \"Company Name\", contact_person AS \"Contact Person\", phone AS \"Phone\", email AS \"Email\", category AS \"Materials Category\", conditions AS \"Terms\", type AS \"Type\" FROM reklet.suppliers ORDER BY id", fetch=True)
        except:
            df_suppliers = pd.DataFrame(columns=["id", "Company Name", "Contact Person", "Phone", "Email", "Materials Category", "Terms", "Type"])

        action = st.radio(
            "Select Action:", 
            ["Suppliers List", "Add Supplier", "Edit / Delete"], 
            horizontal=True,
            key="suppliers_action_radio"
        )
        st.markdown("---")

        if action == "Suppliers List":
            st.markdown("### Current Suppliers Database")
            if df_suppliers.empty:
                st.info("Suppliers list is empty. Add the first supplier in the 'Add Supplier' tab.")
            else:
                st.dataframe(df_suppliers, use_container_width=True)

        elif action == "Add Supplier":
            st.markdown("### Add New Supplier")
            
            with st.form("add_supplier_form"):
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("Company Name*")
                    contact_person = st.text_input("Contact Person")
                    phone = st.text_input("Phone")
                with col2:
                    email = st.text_input("Email")
                    category = st.text_input("Materials Category (e.g., hardware, chipboard)")
                    conditions = st.text_input("Terms (e.g., 50% prepay, delivery 3 days)")
                    s_type = st.selectbox("Counterparty Type", ["material_supplier", "subcontractor", "both"], index=0)

                submitted = st.form_submit_button("Save Supplier")
                
                if submitted:
                    if not name.strip():
                        st.error("Field 'Company Name' is required!")
                    else:
                        try:
                            run_query(
                                "INSERT INTO reklet.suppliers (name, contact_person, phone, email, category, conditions, type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                (name, contact_person, phone, email, category, conditions, s_type)
                            )
                            st.success(f"Supplier '{name}' successfully added!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        elif action == "Edit / Delete":
            st.markdown("### Edit or Delete Supplier")
            
            if df_suppliers.empty:
                st.info("No data available for editing.")
            else:
                supplier_options = df_suppliers["Company Name"].tolist()
                selected_name = st.selectbox("Select Supplier:", supplier_options)
                
                supplier_row = df_suppliers[df_suppliers["Company Name"] == selected_name].iloc[0]
                row_id = int(supplier_row["id"])

                with st.form("edit_supplier_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        e_name = st.text_input("Company Name*", value=supplier_row["Company Name"])
                        e_contact = st.text_input("Contact Person", value=str(supplier_row["Contact Person"]) if pd.notna(supplier_row["Contact Person"]) else "")
                        e_phone = st.text_input("Phone", value=str(supplier_row["Phone"]) if pd.notna(supplier_row["Phone"]) else "")
                    with col2:
                        e_email = st.text_input("Email", value=str(supplier_row["Email"]) if pd.notna(supplier_row["Email"]) else "")
                        e_category = st.text_input("Materials Category", value=str(supplier_row["Materials Category"]) if pd.notna(supplier_row["Materials Category"]) else "")
                        e_conditions = st.text_input("Terms", value=str(supplier_row["Terms"]) if pd.notna(supplier_row["Terms"]) else "")
                        
                        current_type = supplier_row["Type"] if "Type" in supplier_row and pd.notna(supplier_row["Type"]) else "material_supplier"
                        type_options = ["material_supplier", "subcontractor", "both"]
                        type_idx = type_options.index(current_type) if current_type in type_options else 0
                        e_type = st.selectbox("Counterparty Type", type_options, index=type_idx)

                    col_save, col_del = st.columns(2)
                    with col_save:
                        update_btn = st.form_submit_button("Update Data")
                    with col_del:
                        delete_btn = st.form_submit_button("Delete Supplier", type="primary")

                    if update_btn:
                        try:
                            run_query(
                                "UPDATE reklet.suppliers SET name = %s, contact_person = %s, phone = %s, email = %s, category = %s, conditions = %s, type = %s WHERE id = %s",
                                (e_name, e_contact, e_phone, e_email, e_category, e_conditions, e_type, row_id)
                            )
                            st.success("Supplier data successfully updated!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                    if delete_btn:
                        try:
                            mat_check = run_query("SELECT COUNT(*) FROM reklet.materials WHERE supplier_id = %s", (row_id,), fetch=True)
                            m_cnt = mat_check.iloc[0, 0] if not mat_check.empty else 0
                            
                            if m_cnt > 0:
                                st.error(f"Cannot delete supplier as {m_cnt} warehouse materials are linked to it!")
                            else:
                                run_query("DELETE FROM reklet.suppliers WHERE id = %s", (row_id,))
                                st.warning(f"Supplier '{selected_name}' deleted.")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

# 5. PRODUCTION
elif menu == "Production":
    st.header("Production Management")
    st.markdown("Production process control: distributing item quantities across workshop stages.")
    st.markdown("---")

    try:
        objects_df = run_query("SELECT id, object_name FROM reklet.objects ORDER BY id", fetch=True)
        objects_dict = {row['object_name']: int(row['id']) for _, row in objects_df.iterrows()} if not objects_df.empty else {}
    except:
        objects_dict = {}

    col_f1, _ = st.columns([2, 2])
    with col_f1:
        filter_obj = st.selectbox("Filter by Object", ["All Objects"] + list(objects_dict.keys()))

    try:
        base_query = """
            SELECT oi.id, o.object_name, c.name AS client_name, oi.item_name, oi.quantity,
                   oi.qty_production, oi.qty_ready, oi.qty_shipped, oi.qty_arrived, oi.qty_installing, oi.qty_installed
            FROM reklet.object_items oi
            JOIN reklet.objects o ON oi.object_id = o.id
            LEFT JOIN reklet.clients c ON o.client_id = c.id
        """
        if filter_obj != "All Objects":
            sel_obj_id = objects_dict[filter_obj]
            base_query += f" WHERE oi.object_id = {sel_obj_id}"
        
        base_query += " ORDER BY oi.id"
        df_prod = run_query(base_query, fetch=True)
        
        if not df_prod.empty:
            st.markdown("### Workshop Batch Distribution (in pieces)")
            df_prod_display = df_prod.copy()
            df_prod_display.insert(0, "No.", range(1, len(df_prod_display) + 1))
            
            total_plans = []
            calculated_news = []
            
            for idx, row in df_prod.iterrows():
                plan_q = int(row['quantity']) if pd.notna(row['quantity']) and int(row['quantity']) > 0 else int(row.get('quantity_needed', 0))
                if plan_q == 0:
                    plan_q = int(row['qty_production']) + int(row['qty_ready']) + int(row['qty_shipped']) + int(row['qty_arrived']) + int(row['qty_installing']) + int(row['qty_installed'])
                
                total_plans.append(plan_q)
                
                done_sum = int(row['qty_production']) + int(row['qty_ready']) + int(row['qty_shipped']) + int(row['qty_arrived']) + int(row['qty_installing']) + int(row['qty_installed'])
                calc_new = max(0, plan_q - done_sum)
                calculated_news.append(calc_new)

            df_prod_display['Total Plan'] = total_plans
            df_prod_display['Not Started (New)'] = calculated_news
            
            display_cols = ['No.', 'object_name', 'client_name', 'item_name', 'Total Plan', 'Not Started (New)', 'qty_production', 'qty_ready']
            df_editable = df_prod_display[display_cols].copy()
            
            edited_prod = st.data_editor(
                df_editable,
                key="production_quantities_editor",
                use_container_width=True,
                column_config={
                    "Total Plan": st.column_config.NumberColumn("Total Plan", disabled=True),
                    "Not Started (New)": st.column_config.NumberColumn("Not Started (New)", disabled=True),
                    "qty_production": st.column_config.NumberColumn("In Production", min_value=0, step=1),
                    "qty_ready": st.column_config.NumberColumn("Ready for Warehouse", min_value=0, step=1),
                }
            )
            
            if st.button("Save Workshop Distribution", key="save_prod_quantities"):
                for idx, row in edited_prod.iterrows():
                    real_id = int(df_prod.iloc[idx]['id'])
                    new_q_prod = int(row['qty_production'])
                    new_q_ready = int(row['qty_ready'])
                    
                    total_plan = int(df_prod_display.iloc[idx]['Total Plan'])
                    q_ship = int(df_prod.iloc[idx]['qty_shipped'])
                    q_arr = int(df_prod.iloc[idx]['qty_arrived'])
                    q_inst = int(df_prod.iloc[idx]['qty_installing'])
                    q_insted = int(df_prod.iloc[idx]['qty_installed'])
                    
                    if (new_q_prod + new_q_ready + q_ship + q_arr + q_inst + q_insted) > total_plan:
                        st.error(f"Error for item {row['item_name']}: sum of stages cannot exceed Total Plan ({total_plan})!")
                    else:
                        new_q_new = max(0, total_plan - (new_q_prod + new_q_ready + q_ship + q_arr + q_inst + q_insted))
                        run_query(
                            """UPDATE reklet.object_items SET 
                               qty_new = %s, qty_production = %s, qty_ready = %s 
                               WHERE id = %s""",
                            (new_q_new, new_q_prod, new_q_ready, real_id)
                        )
                st.success("Workshop distribution successfully saved!")
                st.rerun()
        else:
            st.info("No items for the selected filter.")
    except Exception as e:
        st.info("Error loading production module: " + str(e))

# 6. TRANSPORT
elif menu == "Transport":
    st.header("Transport & Shipping Management")
    st.markdown("Manage finished goods warehouse and shipment to objects.")
    st.markdown("---")

    try:
        objects_df = run_query("SELECT id, object_name FROM reklet.objects ORDER BY id", fetch=True)
        objects_dict = {row['object_name']: int(row['id']) for _, row in objects_df.iterrows()} if not objects_df.empty else {}
    except:
        objects_dict = {}

    col_t1, _ = st.columns([2, 2])
    with col_t1:
        filter_obj_transport = st.selectbox("Filter by Object", ["All Objects"] + list(objects_dict.keys()), key="transport_obj_filter")

    try:
        transport_query = """
            SELECT oi.id, o.object_name, c.name AS client_name, oi.item_name, oi.qty_ready, oi.qty_shipped
            FROM reklet.object_items oi
            JOIN reklet.objects o ON oi.object_id = o.id
            LEFT JOIN reklet.clients c ON o.client_id = c.id
            WHERE oi.qty_ready > 0
        """
        if filter_obj_transport != "All Objects":
            sel_obj_id_t = objects_dict[filter_obj_transport]
            transport_query += f" AND oi.object_id = {sel_obj_id_t}"
            
        transport_query += " ORDER BY oi.id"
        ready_df = run_query(transport_query, fetch=True)

        if not ready_df.empty:
            st.subheader("Finished Goods Warehouse (Waiting for Shipment)")
            st.markdown("Here is the quantity of items ready in stock (`qty_ready`). Specify how many to ship (`qty_shipped`).")
            
            ready_display = ready_df.copy()
            ready_display.insert(0, "No.", range(1, len(ready_display) + 1))
            ready_editable = ready_display.drop(columns=['id'])
            
            edited_ready = st.data_editor(
                ready_editable,
                key="shipment_quantity_editor",
                use_container_width=True,
                column_config={
                    "qty_ready": st.column_config.NumberColumn("Ready in Stock", disabled=True),
                    "qty_shipped": st.column_config.NumberColumn("Ship (In Transit)", min_value=0, step=1)
                }
            )
            
            if st.button("Confirm Batch Shipment", key="save_shipment_quantities"):
                for idx, row in edited_ready.iterrows():
                    real_id = int(ready_df.iloc[idx]['id'])
                    orig_ready = int(ready_df.iloc[idx]['qty_ready'])
                    ship_input = int(row['qty_shipped'])
                    
                    if ship_input > orig_ready:
                        st.error(f"Cannot ship more than available in stock ({orig_ready} pcs.)!")
                    else:
                        new_ready = orig_ready - ship_input
                        db_item = run_query("SELECT qty_shipped FROM reklet.object_items WHERE id = %s", (real_id,), fetch=True)
                        cur_sh = int(db_item.iloc[0]['qty_shipped']) if not db_item.empty else 0
                        
                        new_shipped = cur_sh + ship_input
                        
                        run_query(
                            "UPDATE reklet.object_items SET qty_ready = %s, qty_shipped = %s WHERE id = %s",
                            (new_ready, new_shipped, real_id)
                        )
                st.success("Shipment successfully processed!")
                st.rerun()
        else:
            st.info("No finished goods in stock (qty_ready > 0) for the selected filter.")
    except Exception as e:
        st.info("Error loading finished goods warehouse: " + str(e))

# 7. INSTALLATION
elif menu == "Installation":
    st.header("Installation Management")
    st.markdown("Control installation and status of arrival/setup on objects.")
    st.markdown("---")

    try:
        objects_df = run_query("SELECT id, object_name FROM reklet.objects ORDER BY id", fetch=True)
        objects_dict = {row['object_name']: int(row['id']) for _, row in objects_df.iterrows()} if not objects_df.empty else {}
    except:
        objects_dict = {}

    col_i1, _ = st.columns([2, 2])
    with col_i1:
        filter_obj_install = st.selectbox("Filter by Object", ["All Objects"] + list(objects_dict.keys()), key="install_obj_filter")

    try:
        install_query = """
            SELECT oi.id, o.object_name, c.name AS client_name, oi.item_name, 
                   oi.qty_shipped, oi.qty_arrived, oi.qty_installing, oi.qty_installed
            FROM reklet.object_items oi
            JOIN reklet.objects o ON oi.object_id = o.id
            LEFT JOIN reklet.clients c ON o.client_id = c.id
            WHERE (oi.qty_shipped > 0 OR oi.qty_arrived > 0 OR oi.qty_installing > 0 OR oi.qty_installed > 0)
        """
        if filter_obj_install != "All Objects":
            sel_obj_id_i = objects_dict[filter_obj_install]
            install_query += f" AND oi.object_id = {sel_obj_id_i}"
            
        install_query += " ORDER BY oi.id"
        inst_df = run_query(install_query, fetch=True)

        if not inst_df.empty:
            st.subheader("Item-by-Item Installation Tracking on Objects")
            st.markdown("Distribute item quantities across installation stages:")
            inst_display = inst_df.copy()
            inst_display.insert(0, "No.", range(1, len(inst_display) + 1))
            inst_editable = inst_display.drop(columns=['id'])
            
            edited_inst = st.data_editor(
                inst_editable,
                key="installation_quantities_editor",
                use_container_width=True,
                column_config={
                    "qty_shipped": st.column_config.NumberColumn("Shipped / In Transit", min_value=0, step=1),
                    "qty_arrived": st.column_config.NumberColumn("Arrived / Ready to Install", min_value=0, step=1),
                    "qty_installing": st.column_config.NumberColumn("Installing", min_value=0, step=1),
                    "qty_installed": st.column_config.NumberColumn("Installed", min_value=0, step=1),
                }
            )
            
            if st.button("Save Installation Statuses", key="save_installation_quantities"):
                for idx, row in edited_inst.iterrows():
                    real_id = int(inst_df.iloc[idx]['id'])
                    run_query(
                        """UPDATE reklet.object_items SET 
                           qty_shipped = %s, qty_arrived = %s, qty_installing = %s, qty_installed = %s 
                           WHERE id = %s""",
                        (int(row['qty_shipped']), int(row['qty_arrived']), int(row['qty_installing']), int(row['qty_installed']), real_id)
                    )
                st.success("Installation statuses successfully updated!")
                st.rerun()
        else:
            st.info("No shipped items for installation control matching the selected filter.")
    except Exception as e:
        st.info("Error loading installation module: " + str(e))

# 8. PAYROLL CALCULATION
elif menu == "Payroll Calculation":
    st.header("Piece-Rate Payroll Calculation")
    st.info("Payroll computation for production and installation departments.")

# 9. REPORTS
elif menu == "Reports":
    st.header("Summary Reports")
    st.info("Select and view analytical reports.")