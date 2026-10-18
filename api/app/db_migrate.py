"""Lightweight SQLite column adds for local prototype DBs (create_all does not alter)."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _existing_columns(engine: Engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        truck_cols = _existing_columns(engine, "trucks")
        if truck_cols and "max_interior_height_in" not in truck_cols:
            conn.execute(
                text(
                    "ALTER TABLE trucks ADD COLUMN max_interior_height_in INTEGER NOT NULL DEFAULT 84"
                )
            )
        elif truck_cols and "max_interior_height_in" in truck_cols:
            # Align legacy / prior defaults → trailer 108" / van 81" / truck 84"
            conn.execute(
                text(
                    "UPDATE trucks SET max_interior_height_in = 108 "
                    "WHERE (has_trailer = 1 OR trailer_size_class = 'ft53') "
                    "AND max_interior_height_in IN (110, 90, 84)"
                )
            )
            conn.execute(
                text(
                    "UPDATE trucks SET max_interior_height_in = 81 "
                    "WHERE vehicle_class = 'van' "
                    "AND NOT (has_trailer = 1 OR trailer_size_class = 'ft53') "
                    "AND max_interior_height_in IN (110, 90, 84)"
                )
            )
            conn.execute(
                text(
                    "UPDATE trucks SET max_interior_height_in = 84 "
                    "WHERE vehicle_class != 'van' "
                    "AND NOT (has_trailer = 1 OR trailer_size_class = 'ft53') "
                    "AND max_interior_height_in IN (110, 90)"
                )
            )
        if truck_cols and "current_address" not in truck_cols:
            conn.execute(
                text(
                    "ALTER TABLE trucks ADD COLUMN current_address VARCHAR(255) NOT NULL DEFAULT ''"
                )
            )
            conn.execute(
                text(
                    "UPDATE trucks SET current_address = home_terminal_city "
                    "WHERE current_address = '' OR current_address IS NULL"
                )
            )
        if truck_cols and "current_lat" not in truck_cols:
            conn.execute(text("ALTER TABLE trucks ADD COLUMN current_lat FLOAT"))
        if truck_cols and "current_lng" not in truck_cols:
            conn.execute(text("ALTER TABLE trucks ADD COLUMN current_lng FLOAT"))

        order_cols = _existing_columns(engine, "orders")
        if order_cols and "stackable" not in order_cols:
            conn.execute(
                text("ALTER TABLE orders ADD COLUMN stackable BOOLEAN NOT NULL DEFAULT 0")
            )
        if order_cols and "height_in" not in order_cols:
            conn.execute(text("ALTER TABLE orders ADD COLUMN height_in FLOAT"))
        if order_cols and "delivery_window_start" not in order_cols:
            conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_window_start DATETIME"))
        if order_cols and "delivery_window_end" not in order_cols:
            conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_window_end DATETIME"))
        if order_cols and "assigned_driver_id" not in order_cols:
            conn.execute(text("ALTER TABLE orders ADD COLUMN assigned_driver_id INTEGER"))
        if order_cols and "stop_seq" not in order_cols:
            conn.execute(text("ALTER TABLE orders ADD COLUMN stop_seq INTEGER"))
        if order_cols and "origin_address" not in order_cols:
            conn.execute(
                text("ALTER TABLE orders ADD COLUMN origin_address VARCHAR(255) NOT NULL DEFAULT ''")
            )
            conn.execute(
                text(
                    "UPDATE orders SET origin_address = origin_city || ', ON' "
                    "WHERE origin_address = '' OR origin_address IS NULL"
                )
            )
        if order_cols and "destination_address" not in order_cols:
            conn.execute(
                text(
                    "ALTER TABLE orders ADD COLUMN destination_address VARCHAR(255) NOT NULL DEFAULT ''"
                )
            )
            conn.execute(
                text(
                    "UPDATE orders SET destination_address = destination_city || ', ON' "
                    "WHERE destination_address = '' OR destination_address IS NULL"
                )
            )

        driver_cols = _existing_columns(engine, "drivers")
        if not driver_cols:
            return

        if "hos_cycle" not in driver_cols:
            conn.execute(
                text(
                    "ALTER TABLE drivers ADD COLUMN hos_cycle VARCHAR(32) "
                    "NOT NULL DEFAULT 'cycle_70_7'"
                )
            )
        if "hos_exempt" not in driver_cols:
            conn.execute(
                text(
                    "ALTER TABLE drivers ADD COLUMN hos_exempt BOOLEAN NOT NULL DEFAULT 0"
                )
            )

        # Rename / backfill default_truck_id → truck_id (required, unique 1:1)
        if "truck_id" not in driver_cols:
            conn.execute(text("ALTER TABLE drivers ADD COLUMN truck_id INTEGER"))
            if "default_truck_id" in driver_cols:
                conn.execute(
                    text(
                        "UPDATE drivers SET truck_id = default_truck_id "
                        "WHERE truck_id IS NULL AND default_truck_id IS NOT NULL"
                    )
                )
            # Assign any remaining null truck_id to unused trucks (1:1)
            rows = conn.execute(
                text("SELECT id FROM drivers WHERE truck_id IS NULL ORDER BY code")
            ).fetchall()
            used = {
                r[0]
                for r in conn.execute(
                    text("SELECT truck_id FROM drivers WHERE truck_id IS NOT NULL")
                ).fetchall()
            }
            free = [
                r[0]
                for r in conn.execute(text("SELECT id FROM trucks ORDER BY unit_number")).fetchall()
                if r[0] not in used
            ]
            for (driver_id,) in rows:
                if not free:
                    break
                tid = free.pop(0)
                conn.execute(
                    text("UPDATE drivers SET truck_id = :tid WHERE id = :did"),
                    {"tid": tid, "did": driver_id},
                )
            # SQLite cannot easily ADD UNIQUE/NOT NULL after the fact; app enforces.
            # Index for uniqueness when possible
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_drivers_truck_id ON drivers (truck_id)"
                    )
                )
            except Exception:
                pass

        # hos_status_logs is created by metadata.create_all; ensure columns exist if table present
        hos_cols = _existing_columns(engine, "hos_status_logs")
        if hos_cols:
            if "note" not in hos_cols:
                conn.execute(
                    text("ALTER TABLE hos_status_logs ADD COLUMN note VARCHAR(255)")
                )
