# Smart Freight API

FastAPI backend for the Trans Ontario freight-planning prototype.

Features in this slice:

- Cookie-based auth (login / logout / me)
- CRUD for **trucks**, **drivers**, and **orders** (Elite/Samsara-aligned fields)
- Heuristic **truck loading + routing** (`POST /optimize`): corridor-aware assignment with travel-aware insertion scoring, per-truck 2-opt stop reorder, capacity/stack/duty-drive/windows checks. Each driver has a required unique `truck_id`. Live ETAs via HERE + Open-Meteo when configured.

## Setup

```bash
cd api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

API docs: http://127.0.0.1:8000/docs

## Demo credentials

Seeded on first startup:

- **Email:** `dispatcher@transontario.ca`
- **Password:** `changeme`

Also seeds ~6 GTA trucks, ~6 drivers (sticky `truck_id`), and ~16 sample orders. Driver **names** and order **street addresses** come from Elite extracts in [`app/data/elite_seed.json`](app/data/elite_seed.json) (depot **2215 Markham Rd, Scarborough**). Drivers default to a **06:00–20:00** shift (14h window); depot ready is **06:00**; daily duty/drive caps default to **~13h**.

## Elite field mapping

| Our model | Elite / export source |
|-----------|------------------------|
| `Order.ordno` | Elite order number |
| `origin_city` / `destination_city` | `tms_SH_CITY` / `tms_RC_CITY` |
| `weight_lbs`, `skid_spots`, `linear_feet`, `dim_weight`, `pieces` | `tms_WGT`, `tms_SPOTS`, `tms_FEET`, `tms_DIMWGT`, `tms_PCS` |
| `service` | `tms_SERVICE` (LTL, OVERNIGHT, RUSH, …) |
| `equipment_required` | `tms_VEHICLE` / `equipment_requested` (truck, trailer_53, …) |
| `requires_liftgate`, `residential`, `inside_delivery`, `appointment`, `heated`, `dangerous_goods` | `tms_TAILGATE` / liftgate flags, `tms_RESIDENT`, `tms_INSIDEDL`, `tms_APPOINT`, `tms_HEATED`, `tms_DNGRGDS` |
| `Truck.unit_number` | e.g. `Truck #202` |
| Trailer fields | `Trailer #530129`, 53' class |

**Note:** Elite does not store cubic volume. Capacity uses **weight + skid spots + linear feet**, plus prototype **height / stackability** fields (not in Elite exports).

### Capacity assumptions (prototype, not full CVOR)

- Axles → max weight: van 2-axle ~10k lb; straight truck 2–3 axle ~26–33k; tractor 3–5 axle ~45–80k
- Straight truck ~10 skid spots / 24 ft; 53' trailer ~26 spots / 53 ft
- Interior height defaults: trailers 108 in; trucks 84 in; cargo vans 81 in (typical high-roof work van)
- Liftgate required when order has liftgate, residential, or inside delivery
- `trailer_53` equipment requires tractor + 53' trailer

### Stacking / height (prototype)

- Order fields: `stackable` (bool), `height_in` (inches, optional)
- Truck field: `max_interior_height_in`
- If `height_in` is set and exceeds truck interior height → reject (`too tall for truck`)
- **Non-stackable** (or stackable without height): consumes floor `skid_spots` 1:1
- **Stackable with height**: may share a same-footprint floor column if stacked heights fit under interior clearance, max **2 layers**
- Missing Elite height/stack → defaults `stackable=false`, `height_in=null` (floor-only, prior behavior)
- Optimize response includes per-order `placements` (column/layer/height) plus truck `max_*` dims for the UI **load visualization** (top + side); display assumes 1 skid spot ≈ 48×48 in
- Not modeled: crush limits, load sequence, true 3D packing

### Drivers, windows, and co-assignment (prototype)

- **Driver** quals: `licence_class` (G/DZ/AZ), DG / heated / liftgate flags; shift start/end minutes; max duty/drive hours
- **Order** optional `delivery_window_start` / `delivery_window_end`; `assigned_driver_id` set on persist
- Explicit windows are **hard**; service defaults: RUSH/SAME DAY due 15:00 (hard); OVERNIGHT prefer early (soft); LTL open to shift end
- Travel: static GTA city-pair minutes (`app/services/travel.py`), else 45 min; 15 min service per stop — or **HERE** live ETAs when `HERE_API_KEY` is set
- Weather pad via **Open-Meteo** (no key) on live legs
- **Driver.truck_id** (required, unique): each driver is permanently tied to one truck; optimize always uses that driver for that truck
- **Heuristic:** corridor grouping + travel-aware insertion scoring + per-truck 2-opt reorder; validates capacity / stack / quals / duty-drive / windows
- Load is **LIFO** (first stop at door); overflow prefers same-direction trucks
- Response includes `routing_mode` (`static`|`live`), `route` stops/ETAs, `weather_summary`
- Not in scope: map tiles, weekly HOS ledger, pickup-leg split, OR-Tools VRP, LLM routing

To pick up new seed data (driver names / addresses / trucks / shift times), delete `smart_freight.db` and restart the API, or run with `SEED_FORCE=1`.

## Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/login` | Sets HTTP-only JWT cookie |
| `POST` | `/auth/logout` | Clears cookie |
| `GET` | `/auth/me` | Current user |
| `GET` | `/health` | Liveness |

## Trucks, drivers & orders

| Method | Path |
|--------|------|
| `GET/POST` | `/trucks` |
| `GET/PATCH/DELETE` | `/trucks/{id}` |
| `GET/POST` | `/drivers` |
| `GET/PATCH/DELETE` | `/drivers/{id}` |
| `GET/POST` | `/orders` |
| `GET/PATCH/DELETE` | `/orders/{id}` |

## Optimize

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/optimize` | Body `{ "persist": false, "planning_date": "YYYY-MM-DD" }` — co-assign truck+driver; `persist: true` writes truck/driver FKs |
| `POST` | `/optimize/reset` | Clear assignments (orders, trucks, drivers) back to available/unassigned |

### Example

```bash
# Login
curl -c cookies.txt -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dispatcher@transontario.ca","password":"changeme"}'

# List seeded trucks / drivers / orders
curl -b cookies.txt http://127.0.0.1:8000/trucks
curl -b cookies.txt http://127.0.0.1:8000/drivers
curl -b cookies.txt http://127.0.0.1:8000/orders

# Dry-run optimize
curl -b cookies.txt -X POST http://127.0.0.1:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{"persist": false}'

# Persist assignments, then reset
curl -b cookies.txt -X POST http://127.0.0.1:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{"persist": true}'
curl -b cookies.txt -X POST http://127.0.0.1:8000/optimize/reset
```

## Configuration

Optional `.env` in `api/`:

```
SECRET_KEY=replace-me
DATABASE_URL=sqlite:///./smart_freight.db

# Live routing (HERE). Omit for static GTA travel table.
HERE_API_KEY=
ROUTING_ENABLED=true
```

Open-Meteo needs no key. Without `HERE_API_KEY`, travel uses the static GTA table.
