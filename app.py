import streamlit as st
import pandas as pd
import psycopg2
from datetime import date

# Set wide layout so the horizontal menu looks clean and neat
st.set_page_config(page_title="Reklet — Production Management", layout="wide")

# PostgreSQL connection settings in Supabase (через Session Pooler)
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
        connect_timeout=5  # Защита от зависания сети
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

# --- SIMPLE AUTHENTICATION (Без сложных хэшей) ---
if 'authentication_status' not in st.session_state:
    st.session_state['authentication_status'] = None

if not st.session_state['authentication_status']:
    st.subheader("Login to Reklet — Production Management")
    with st.form("login_form"):
        username_input = st.text_input("Username")
        password_input = st.text_input("Password", type="password")
        submit_login = st.form_submit_button("Login")
        
        if submit_login:
            # Укажите здесь нужные логин и пароль
            if username_input == "admin" and password_input == "12345":
                st.session_state['authentication_status'] = True
                st.session_state['username'] = "admin"
                st.session_state['name'] = "Administrator"
                st.rerun()
            else:
                st.session_state['authentication_status'] = False
                st.error('Неверное имя пользователя или пароль')
    
    st.stop()

# Кнопка выхода в боковой панели
if st.sidebar.button('Выйти'):
    st.session_state['authentication_status'] = None
    st.rerun()

# --- ОСНОВНОЙ КОД ПРИЛОЖЕНИЯ ---
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

    else:
        st.info("Please add objects in the Objects Database first.")
