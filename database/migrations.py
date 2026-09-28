import streamlit as st
import pandas as pd

from core.db import run_query, run_transaction


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
        run_transaction([
            (statements[0], ()),
            (statements[1], ())
        ])
        st.session_state["_product_categories_ready"] = True
    except Exception:
        st.session_state["_product_categories_ready"] = False
        raise



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


def ensure_material_planning_tables():
    """Ensure all warehouse planning/snapshot tables exist.

    The schema is created in a separate transaction from historical backfill.
    This is intentionally idempotent so a deployment can recover automatically
    when an earlier version of the app did not create all warehouse tables.
    Reservation workflow is retired; any legacy reservation tables in PostgreSQL
    are deliberately left untouched and are no longer created, read, or written.
    """
    # Do a very cheap existence check even when a previous Streamlit run marked
    # the migration as ready. This protects a long-lived session if a table/column
    # was missing or restored after that flag was set.
    try:
        check = run_query(
            """
            SELECT
                to_regclass('reklet.purchase_orders') AS purchase_orders,
                to_regclass('reklet.purchase_order_items') AS purchase_order_items,
                to_regclass('reklet.material_consumption') AS material_consumption,
                to_regclass('reklet.object_item_material_costs') AS object_item_material_costs
            """,
            fetch=True,
        )
        ready = (
            not check.empty
            and all(pd.notna(check.iloc[0][col]) for col in check.columns)
        )
        if ready:
            col_check = run_query(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='reklet'
                  AND table_name='material_consumption'
                  AND column_name='unit_cost_snapshot'
                """,
                fetch=True,
            )
            if not col_check.empty:
                st.session_state['_material_planning_tables_ready'] = True
                return
    except Exception:
        # Fall through to the idempotent CREATE/ALTER statements below.
        pass

    schema_statements = [
        ("""
        CREATE TABLE IF NOT EXISTS reklet.purchase_orders (
            id serial4 PRIMARY KEY,
            supplier_id int4 NOT NULL REFERENCES reklet.suppliers(id) ON DELETE RESTRICT,
            order_date date NOT NULL DEFAULT CURRENT_DATE,
            status text NOT NULL DEFAULT 'ordered',
            notes text NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT purchase_orders_status_check CHECK (status IN ('ordered','partial','received','cancelled'))
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.purchase_order_items (
            id serial4 PRIMARY KEY,
            purchase_order_id int4 NOT NULL REFERENCES reklet.purchase_orders(id) ON DELETE CASCADE,
            object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
            material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
            quantity_ordered numeric NOT NULL,
            quantity_received numeric NOT NULL DEFAULT 0,
            unit_price numeric NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT purchase_order_items_ordered_positive_check CHECK (quantity_ordered > 0),
            CONSTRAINT purchase_order_items_received_nonnegative_check CHECK (quantity_received >= 0),
            CONSTRAINT purchase_order_items_received_limit_check CHECK (quantity_received <= quantity_ordered)
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.material_consumption (
            id serial4 PRIMARY KEY,
            object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE RESTRICT,
            object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
            material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
            quantity numeric NOT NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT material_consumption_positive_check CHECK (quantity > 0)
        )
        """, ()),
        ("""
        CREATE TABLE IF NOT EXISTS reklet.object_item_material_costs (
            id serial4 PRIMARY KEY,
            object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE CASCADE,
            material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
            quantity_per_unit numeric NOT NULL,
            waste_coefficient numeric NOT NULL,
            unit_cost numeric NOT NULL,
            created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT object_item_material_costs_unique UNIQUE (object_item_id, material_id),
            CONSTRAINT object_item_material_costs_quantity_check CHECK (quantity_per_unit >= 0),
            CONSTRAINT object_item_material_costs_waste_check CHECK (waste_coefficient >= 0),
            CONSTRAINT object_item_material_costs_cost_check CHECK (unit_cost >= 0)
        )
        """, ()),
        ("ALTER TABLE reklet.material_consumption ADD COLUMN IF NOT EXISTS unit_cost_snapshot numeric NULL", ()),
        ("CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON reklet.purchase_orders(supplier_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_purchase_order_items_order ON reklet.purchase_order_items(purchase_order_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_purchase_order_items_object_material ON reklet.purchase_order_items(object_id, material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_consumption_object ON reklet.material_consumption(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_consumption_item ON reklet.material_consumption(object_item_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_consumption_material ON reklet.material_consumption(material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_object_item_material_costs_item ON reklet.object_item_material_costs(object_item_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_object_item_material_costs_material ON reklet.object_item_material_costs(material_id)", ()),
    ]

    run_transaction(schema_statements)
    st.session_state['_material_planning_tables_ready'] = True




def ensure_task_three_tables():
    """Create persistent tables required by Tasks 1-3. Idempotent migration.

    This function intentionally creates only the non-reservation Task 1-3
    tables. Legacy reservation tables, if they already exist in PostgreSQL,
    are left untouched and are not read or written by the application.
    """
    if st.session_state.get("_task_three_tables_ready"):
        return

    statements = [
        (
            """
            ALTER TABLE reklet.purchase_order_items
            ALTER COLUMN object_id DROP NOT NULL
            """,
            (),
        ),
        (
            """
            ALTER TABLE reklet.purchase_order_items
            ADD COLUMN IF NOT EXISTS production_request_id int4 NULL
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.material_production_requests (
                id serial4 PRIMARY KEY,
                object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
                object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE RESTRICT,
                material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
                quantity_requested numeric NOT NULL,
                quantity_supplied numeric NOT NULL DEFAULT 0,
                status text NOT NULL DEFAULT 'sent',
                created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                notes text NULL,
                CONSTRAINT material_production_requests_quantity_check CHECK (quantity_requested > 0),
                CONSTRAINT material_production_requests_supplied_check CHECK (quantity_supplied >= 0),
                CONSTRAINT material_production_requests_status_check CHECK (status IN ('sent','purchasing','ready','completed','cancelled'))
            )
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.material_waste_transactions (
                id serial4 PRIMARY KEY,
                material_id int4 NOT NULL REFERENCES reklet.materials(id) ON DELETE RESTRICT,
                object_id int4 NULL REFERENCES reklet.objects(id) ON DELETE SET NULL,
                source_type text NOT NULL,
                quantity numeric NOT NULL,
                unit_cost_snapshot numeric NOT NULL DEFAULT 0,
                reason text NULL,
                created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                CONSTRAINT material_waste_source_check CHECK (source_type IN ('stock','production')),
                CONSTRAINT material_waste_quantity_check CHECK (quantity > 0)
            )
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.work_time_calculations (
                id serial4 PRIMARY KEY,
                object_id int4 NOT NULL REFERENCES reklet.objects(id) ON DELETE RESTRICT,
                distance_km numeric NOT NULL DEFAULT 0,
                loading_minutes numeric NOT NULL DEFAULT 240,
                road_minutes numeric NOT NULL DEFAULT 240,
                unloading_minutes numeric NOT NULL DEFAULT 240,
                production_minutes numeric NOT NULL DEFAULT 0,
                installation_minutes numeric NOT NULL DEFAULT 0,
                transport_minutes numeric NOT NULL DEFAULT 720,
                total_minutes numeric NOT NULL DEFAULT 0,
                calculated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
                CONSTRAINT work_time_distance_check CHECK (distance_km >= 0),
                CONSTRAINT work_time_minutes_check CHECK (production_minutes >= 0 AND installation_minutes >= 0 AND transport_minutes >= 0 AND total_minutes >= 0)
            )
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS reklet.work_time_calculation_items (
                id serial4 PRIMARY KEY,
                calculation_id int4 NOT NULL REFERENCES reklet.work_time_calculations(id) ON DELETE CASCADE,
                object_item_id int4 NOT NULL REFERENCES reklet.object_items(id) ON DELETE RESTRICT,
                item_name text NOT NULL,
                quantity int4 NOT NULL,
                unit_cost numeric NOT NULL DEFAULT 0,
                base_production_minutes numeric NOT NULL DEFAULT 0,
                quantity_class text NOT NULL,
                time_multiplier numeric NOT NULL DEFAULT 1,
                production_minutes numeric NOT NULL DEFAULT 0,
                installation_minutes numeric NOT NULL DEFAULT 0,
                CONSTRAINT work_time_item_quantity_check CHECK (quantity > 0),
                CONSTRAINT work_time_item_minutes_check CHECK (unit_cost >= 0 AND base_production_minutes >= 0 AND time_multiplier > 0 AND production_minutes >= 0 AND installation_minutes >= 0)
            )
            """,
            (),
        ),
        ("CREATE INDEX IF NOT EXISTS idx_material_production_requests_object ON reklet.material_production_requests(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_production_requests_item ON reklet.material_production_requests(object_item_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_production_requests_material ON reklet.material_production_requests(material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_waste_material ON reklet.material_waste_transactions(material_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_material_waste_object ON reklet.material_waste_transactions(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_work_time_calculations_object ON reklet.work_time_calculations(object_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_work_time_calculation_items_calc ON reklet.work_time_calculation_items(calculation_id)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_work_time_calculation_items_item ON reklet.work_time_calculation_items(object_item_id)", ()),
    ]

    statements.extend([
        (
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname='purchase_order_items_production_request_id_fkey'
                ) THEN
                    ALTER TABLE reklet.purchase_order_items
                    ADD CONSTRAINT purchase_order_items_production_request_id_fkey
                    FOREIGN KEY (production_request_id)
                    REFERENCES reklet.material_production_requests(id)
                    ON DELETE SET NULL;
                END IF;
            END $$;
            """,
            (),
        ),
        (
            "ALTER TABLE reklet.material_production_requests DROP CONSTRAINT IF EXISTS material_production_requests_supplied_check",
            (),
        ),
        (
            "ALTER TABLE reklet.material_production_requests ADD CONSTRAINT material_production_requests_supplied_check CHECK (quantity_supplied >= 0)",
            (),
        ),
        (
            "ALTER TABLE reklet.material_transactions DROP CONSTRAINT IF EXISTS material_transactions_operation_type_check",
            (),
        ),
        (
            """
            ALTER TABLE reklet.material_transactions
            ADD CONSTRAINT material_transactions_operation_type_check
            CHECK (operation_type IN ('purchase','production_transfer','production_allocation','production_return'))
            """,
            (),
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_purchase_order_items_production_request ON reklet.purchase_order_items(production_request_id)",
            (),
        ),
    ])

    run_transaction(statements)
    st.session_state["_task_three_tables_ready"] = True


def ensure_object_item_material_costs(object_id):
    """Create missing frozen material-cost snapshots for one object only."""
    ensure_material_planning_tables()
    run_query(
        """
        INSERT INTO reklet.object_item_material_costs
            (object_item_id, material_id, quantity_per_unit, waste_coefficient, unit_cost)
        SELECT
            oi.id,
            ptm.material_id,
            COALESCE(ptm.quantity_per_unit, 0),
            COALESCE(ptm.waste_coefficient, m.default_waste_coefficient, 1),
            COALESCE(m.cost_per_unit, 0)
        FROM reklet.object_items oi
        JOIN reklet.product_template_materials ptm
          ON ptm.product_template_id = COALESCE(oi.product_template_id, oi.template_id)
        JOIN reklet.materials m ON m.id = ptm.material_id
        WHERE oi.object_id=%s
          AND NOT EXISTS (
              SELECT 1
              FROM reklet.object_item_material_costs existing
              WHERE existing.object_item_id=oi.id
          )
        ON CONFLICT (object_item_id, material_id) DO NOTHING
        """,
        (object_id,),
    )


