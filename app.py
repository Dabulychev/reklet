import streamlit as st

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

    st.markdown(
        """
        <style>
        .reklet-login-title {
            font-size: 3.2rem;
            line-height: 1.05;
            font-weight: 700;
            margin-bottom: 0.45rem;
        }
        .reklet-login-subtitle {
            font-size: 0.9rem;
            line-height: 1.45;
            margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="reklet-login-header">
            <div class="reklet-login-title">Reklet</div>
            <div class="reklet-login-subtitle">
                Для входа введите Логин: <strong>demo</strong> Пароль: <strong>demo</strong>.<br>
                В режиме демо вы можете добавлять, корректировать, удалять, проводить операции.<br>
                Внизу страниц находятся раскрывающиеся инструкции — описание страницы.<br>
                Все данные после закрытия окна будут удалены.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

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
# NEW WORKSPACE NAVIGATION
# ============================================================

from modules.workspace import render_workspace


def render_reference_center():
    st.subheader("Справочники")
    options = ["Клиенты", "Изделия", "Склад материалов", "Поставщики"]
    current = st.session_state.get("reference_section")
    if current not in options:
        current = options[0]
        st.session_state["reference_section"] = current
    cols = st.columns(len(options), gap="small")
    for col, option in zip(cols, options):
        with col:
            if st.button(option, key=f"reference_{option}", use_container_width=True):
                st.session_state["reference_section"] = option
                st.rerun()

    st.markdown("---")
    section = st.session_state["reference_section"]
    if section == "Клиенты":
        render_clients()
    elif section == "Изделия":
        render_products()
    elif section == "Склад материалов":
        render_warehouse()
    elif section == "Поставщики":
        render_suppliers()


def render_service_center():
    st.subheader("Служебные разделы")
    options = [
        "Производство", "Готовая продукция", "Транспорт",
        "Монтаж", "Зарплата", "Отчёты",
    ]
    current = st.session_state.get("service_section")
    if current not in options:
        current = options[0]
        st.session_state["service_section"] = current
    cols = st.columns(3, gap="small")
    for idx, option in enumerate(options):
        with cols[idx % 3]:
            if st.button(option, key=f"service_{option}", use_container_width=True):
                st.session_state["service_section"] = option
                st.rerun()

    st.markdown("---")
    section = st.session_state["service_section"]
    if section == "Производство":
        render_production()
    elif section == "Готовая продукция":
        render_finished_goods()
    elif section == "Транспорт":
        render_transport()
    elif section == "Монтаж":
        render_installation()
    elif section == "Зарплата":
        render_payroll()
    elif section == "Отчёты":
        render_reports()


st.markdown("""
<style>
.reklet-work-nav {
    margin-bottom: 0.35rem;
}
.stButton > button {
    border-radius: 0 !important;
    box-shadow: none !important;
    transition: none !important;
    animation: none !important;
    transform: none !important;
    min-height: 40px !important;
}
</style>
""", unsafe_allow_html=True)

main_options = ["Рабочее место", "Справочники", "Служебные разделы"]
if "main_workspace_section" not in st.session_state:
    st.session_state["main_workspace_section"] = "Рабочее место"

nav_cols = st.columns(3, gap="small")
for col, option in zip(nav_cols, main_options):
    with col:
        if st.button(
            option,
            key=f"main_workspace_nav_{option}",
            use_container_width=True,
            type="primary" if st.session_state["main_workspace_section"] == option else "secondary",
        ):
            st.session_state["main_workspace_section"] = option
            st.rerun()

st.markdown("---")

if st.session_state["main_workspace_section"] == "Рабочее место":
    render_workspace()
elif st.session_state["main_workspace_section"] == "Справочники":
    render_reference_center()
else:
    render_service_center()
