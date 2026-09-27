import streamlit as st

from core.ui import render_button_nav
from database.migrations import ensure_material_planning_tables
from modules.clients import render_clients
from modules.objects import render_objects
from modules.products import render_products
from modules.warehouse import render_warehouse
from modules.suppliers import render_suppliers
from modules.production import render_production
from modules.finished_goods import render_finished_goods
from modules.transport import render_transport
from modules.installation import render_installation
from modules.payroll import render_payroll
from modules.reports import render_reports


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Reklet — Управление производством",
    layout="wide",
    initial_sidebar_state="expanded"
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
except Exception as e:
    st.error("Не удалось подготовить складскую модель данных.")
    st.code(str(e))
    st.stop()


# ============================================================
# HELPER FUNCTIONS
# ============================================================




# ============================================================
# DATA FUNCTIONS
# ============================================================








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
    render_clients()

# OBJECTS
# ============================================================
elif menu == "Объекты":
    render_objects()

elif menu == "Изделия":
    render_products()

# MATERIALS WAREHOUSE
# ============================================================

elif menu == "Склад материалов":
    render_warehouse()

# SUPPLIERS
# ============================================================
elif menu == "Поставщики":
    render_suppliers()

# PRODUCTION
# ============================================================

elif menu == "Производство":
    render_production()

elif menu == "Готовая продукция":
    render_finished_goods()

elif menu == "Транспорт и логистика":
    render_transport()

elif menu == "Монтаж":
    render_installation()


# SALARY
# ============================================================
elif menu == "Зарплата":
    render_payroll()

# REPORTS
# ============================================================
elif menu == "Отчёты":
    render_reports()
