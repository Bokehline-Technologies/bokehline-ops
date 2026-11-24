"""Bokehline Ops: a Streamlit data-entry app and dashboard on a fictional manufacturing database.

Run it with:  streamlit run app.py

Two modes:
- Demo mode (default): each visitor gets a private copy of bokehline_practice.db.
  Changes stay in that copy and disappear when the session ends. The shipped
  database file is never modified.
- Working mode: set the BOKEHLINE_DB environment variable to the path of your own
  database file, and the app reads and writes that file directly.
"""
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

DEMO_DB = Path(__file__).parent / "bokehline_practice.db"
WORKING_DB = os.environ.get("BOKEHLINE_DB")
DEMO_MODE = not WORKING_DB

PHASES = ["Phase 1 - Plan", "Phase 2 - Product Design", "Phase 3 - Process Design",
          "Phase 4 - Validation", "Phase 5 - Launch", "Closed"]
GATES = ["G1 Concept Approval", "G2 Design Freeze", "G3 Process Freeze",
         "G4 PPAP Approval", "G5 Launch Readiness"]

st.set_page_config(page_title="Bokehline Ops", page_icon="📋", layout="wide")


def fresh_demo_copy():
    """Copy the shipped demo database to a private temp file for this browser session."""
    fd, path = tempfile.mkstemp(prefix="bokehline_demo_", suffix=".db")
    os.close(fd)
    shutil.copyfile(DEMO_DB, path)
    return path


if DEMO_MODE:
    if not DEMO_DB.exists():
        st.error(f"Can't find {DEMO_DB.name}. Put it in the same folder as app.py, then refresh.")
        st.stop()
    if "demo_db" not in st.session_state:
        st.session_state.demo_db = fresh_demo_copy()
    DB_PATH = Path(st.session_state.demo_db)
else:
    DB_PATH = Path(WORKING_DB).expanduser()
    if not DB_PATH.exists():
        st.error(f"BOKEHLINE_DB points to {DB_PATH}, but that file doesn't exist.")
        st.stop()


# ---------- database helpers ----------
def connect():
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def writer():
    """Open a connection for saving. If another program (like DB Browser) has the
    database locked, show a friendly message instead of a crash. Nothing is saved."""
    con = connect()
    try:
        with con:
            yield con
    except sqlite3.OperationalError as e:
        if "locked" in str(e):
            st.error("The database is busy, so nothing was saved. If DB Browser is open, click "
                     "Write Changes or Revert Changes there, then try again.")
            st.stop()
        raise
    finally:
        con.close()


def query(sql, params=()):
    """Run a SELECT and return the results as a table (DataFrame)."""
    with connect() as con:
        return pd.read_sql_query(sql, con, params=params)


# ---------- sidebar ----------
st.sidebar.title("Bokehline Ops")
page = st.sidebar.radio("Go to", ["Dashboard", "New program", "Purchase orders", "Production runs", "Browse data"], label_visibility="collapsed")
if DEMO_MODE:
    st.sidebar.info("Demo mode: try any form. Your changes are visible only to you "
                    "and reset when you leave.")
    if st.sidebar.button("Reset demo data"):
        old = st.session_state.demo_db
        st.session_state.demo_db = fresh_demo_copy()
        try:
            os.remove(old)
        except OSError:
            pass
        st.rerun()
else:
    st.sidebar.caption(f"Working database: {DB_PATH.name}")
st.sidebar.divider()
st.sidebar.caption("All data is fictional. Companies, people, part numbers, "
                   "and figures are made up.")


# ---------- page: dashboard ----------
if page == "Dashboard":
    st.title("Operations dashboard")

    PLANT_COLORS = alt.Scale(domain=["US-IN", "US-TN", "BTH"], range=["#3987e5", "#d95926", "#199e70"])
    BAR_COLOR = "#3987e5"

    # ---- filters (one row) ----
    plant_codes = query("SELECT plant_code FROM plants ORDER BY plant_id")["plant_code"].tolist()
    bounds = query("SELECT MIN(run_date) AS lo, MAX(run_date) AS hi FROM production_runs").iloc[0]
    lo, hi = date.fromisoformat(bounds["lo"]), date.fromisoformat(bounds["hi"])
    f1, f2 = st.columns([2, 2])
    picked = f1.multiselect("Plants", plant_codes, default=plant_codes)
    rng = f2.date_input("Production dates", value=(lo, hi), min_value=lo, max_value=hi)
    if not picked:
        st.info("Pick at least one plant.")
        st.stop()
    d_from, d_to = (rng if isinstance(rng, tuple) and len(rng) == 2 else (lo, hi))
    ph = ",".join("?" * len(picked))
    pf = [*picked, d_from.isoformat(), d_to.isoformat()]

    # ---- KPI tiles ----
    k = query(f"""
        SELECT
          (SELECT COUNT(*) FROM programs WHERE status <> 'Closed') AS active,
          (SELECT COUNT(*) FROM programs WHERE status = 'Red') AS red,
          (SELECT COUNT(*) FROM purchase_orders WHERE received_date IS NULL) AS open_po,
          (SELECT COUNT(*) FROM purchase_orders WHERE received_date IS NULL AND promised_date < DATE('now')) AS overdue_po,
          (SELECT ROUND(100.0 * SUM(r.qty_scrapped) / SUM(r.qty_produced), 2)
             FROM production_runs r JOIN plants p ON p.plant_id = r.plant_id
             WHERE p.plant_code IN ({ph}) AND r.run_date BETWEEN ? AND ?) AS scrap_pct
    """, pf).iloc[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active programs", int(k["active"]))
    m2.metric("Programs at Red", int(k["red"]))
    m3.metric("Open POs", int(k["open_po"]))
    m3.caption(f"{int(k['overdue_po'])} past their promised date")
    m4.metric("Scrap rate", f"{k['scrap_pct']:.2f}%" if k["scrap_pct"] is not None else "–")

    st.divider()
    c1, c2 = st.columns(2)

    # ---- scrap % by month, per plant ----
    scrap = query(f"""
        SELECT strftime('%Y-%m', r.run_date) AS month, p.plant_code AS plant,
               SUM(r.qty_produced) AS produced, SUM(r.qty_scrapped) AS scrapped,
               ROUND(100.0 * SUM(r.qty_scrapped) / SUM(r.qty_produced), 2) AS scrap_pct
        FROM production_runs r JOIN plants p ON p.plant_id = r.plant_id
        WHERE p.plant_code IN ({ph}) AND r.run_date BETWEEN ? AND ?
        GROUP BY month, plant ORDER BY month""", pf)
    with c1:
        st.subheader("Scrap rate by month")
        if scrap.empty:
            st.caption("No production in this range.")
        else:
            base = alt.Chart(scrap).encode(
                x=alt.X("month:O", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("scrap_pct:Q", title="Scrap %", scale=alt.Scale(zero=True)),
                color=alt.Color("plant:N", scale=PLANT_COLORS, title="Plant",
                                legend=alt.Legend(orient="top")),
                tooltip=[alt.Tooltip("plant:N", title="Plant"), alt.Tooltip("month:O", title="Month"),
                         alt.Tooltip("scrap_pct:Q", title="Scrap %", format=".2f"),
                         alt.Tooltip("produced:Q", title="Produced", format=","),
                         alt.Tooltip("scrapped:Q", title="Scrapped", format=",")])
            chart = base.mark_line(strokeWidth=2) + base.mark_point(size=64, filled=True)
            st.altair_chart(chart, width="stretch")

    # ---- defect pareto ----
    pareto = query(f"""
        SELECT d.defect_type, SUM(d.qty) AS qty
        FROM defects d JOIN production_runs r ON r.run_id = d.run_id
        JOIN plants p ON p.plant_id = r.plant_id
        WHERE p.plant_code IN ({ph}) AND r.run_date BETWEEN ? AND ?
        GROUP BY d.defect_type ORDER BY qty DESC""", pf)
    with c2:
        st.subheader("Defect Pareto")
        if pareto.empty:
            st.caption("No defects in this range.")
        else:
            pareto["pct"] = 100 * pareto["qty"] / pareto["qty"].sum()
            pareto["cum_pct"] = pareto["pct"].cumsum()
            order = pareto["defect_type"].tolist()
            bars = alt.Chart(pareto).mark_bar(color=BAR_COLOR, cornerRadiusEnd=4).encode(
                y=alt.Y("defect_type:N", sort=order, title=None, axis=alt.Axis(labelLimit=200)),
                x=alt.X("qty:Q", title="Defect qty"),
                tooltip=[alt.Tooltip("defect_type:N", title="Defect"),
                         alt.Tooltip("qty:Q", title="Qty", format=","),
                         alt.Tooltip("pct:Q", title="% of total", format=".1f"),
                         alt.Tooltip("cum_pct:Q", title="Cumulative %", format=".1f")])
            pareto["label"] = pareto["cum_pct"].map(lambda v: f"{v:.0f}% cum.")
            labels = bars.mark_text(align="left", dx=4).encode(
                text="label:N", color=alt.value("gray"))
            st.altair_chart(bars + labels, width="stretch")

    c3, c4 = st.columns(2)

    # ---- supplier on-time delivery ----
    otd = query(f"""
        SELECT s.name AS supplier, s.rating, COUNT(*) AS received,
               SUM(CASE WHEN po.received_date > po.promised_date THEN 1 ELSE 0 END) AS late,
               ROUND(100.0 * SUM(CASE WHEN po.received_date <= po.promised_date THEN 1 ELSE 0 END) / COUNT(*), 1) AS on_time_pct
        FROM purchase_orders po
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        JOIN plants p ON p.plant_id = po.plant_id
        WHERE po.received_date IS NOT NULL AND p.plant_code IN ({ph})
        GROUP BY s.supplier_id ORDER BY on_time_pct DESC""", picked)
    with c3:
        st.subheader("Supplier on-time delivery")
        st.caption("All received POs for the selected plants. Letter = supplier rating.")
        if otd.empty:
            st.caption("No received POs.")
        else:
            otd["label"] = otd["supplier"] + " (" + otd["rating"] + ")"
            bars = alt.Chart(otd).mark_bar(color=BAR_COLOR, cornerRadiusEnd=4).encode(
                y=alt.Y("label:N", sort=otd["label"].tolist(), title=None, axis=alt.Axis(labelLimit=260)),
                x=alt.X("on_time_pct:Q", title="On-time %", scale=alt.Scale(domain=[0, 100])),
                tooltip=[alt.Tooltip("supplier:N", title="Supplier"), alt.Tooltip("rating:N", title="Rating"),
                         alt.Tooltip("on_time_pct:Q", title="On-time %", format=".1f"),
                         alt.Tooltip("received:Q", title="POs received"), alt.Tooltip("late:Q", title="Late")])
            text = bars.mark_text(align="left", dx=4).encode(
                text=alt.Text("on_time_pct:Q", format=".0f"), color=alt.value("gray"))
            st.altair_chart(bars + text, width="stretch")

    # ---- programs by phase & status ----
    phase = query("""SELECT current_phase AS phase, status, COUNT(*) AS n
                     FROM programs GROUP BY current_phase, status""")
    with c4:
        st.subheader("Programs by phase")
        st.caption("All programs. Color shows R/Y/G status.")
        status_scale = alt.Scale(domain=["Green", "Yellow", "Red", "Closed"],
                                 range=["#0ca30c", "#fab219", "#d03b3b", "#8a8984"])
        chart = alt.Chart(phase).mark_bar(cornerRadiusEnd=4, stroke=None).encode(
            y=alt.Y("phase:N", sort=PHASES, title=None, axis=alt.Axis(labelLimit=220)),
            x=alt.X("n:Q", title="Programs", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("status:N", scale=status_scale, title="Status",
                            legend=alt.Legend(orient="top")),
            order=alt.Order("status:N"),
            tooltip=[alt.Tooltip("phase:N", title="Phase"), alt.Tooltip("status:N", title="Status"),
                     alt.Tooltip("n:Q", title="Programs")])
        st.altair_chart(chart, width="stretch")

    with st.expander("View the data behind these charts"):
        t1, t2, t3, t4 = st.tabs(["Scrap by month", "Defect Pareto", "Supplier OTD", "Programs by phase"])
        t1.dataframe(scrap, hide_index=True, width="stretch")
        t2.dataframe(pareto.drop(columns=["label"], errors="ignore"), hide_index=True, width="stretch")
        t3.dataframe(otd.drop(columns=["label"], errors="ignore"), hide_index=True, width="stretch")
        t4.dataframe(phase, hide_index=True, width="stretch")


# ---------- page: new program ----------
elif page == "New program":
    st.title("New program")
    st.caption("Add an APQP program. Dropdowns pull live values from the database.")

    customers = query("SELECT customer_id, name, segment FROM customers ORDER BY name")
    pms = query("""SELECT employee_id, first_name || ' ' || last_name AS name
                   FROM employees WHERE title = 'Program Manager' ORDER BY name""")
    plants = query("SELECT plant_id, plant_code || ' – ' || name AS label FROM plants ORDER BY plant_id")

    with st.form("new_program", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Program name", placeholder="Zone Controller Gen 2")
        cust_label = c2.selectbox(
            "Customer", customers.apply(lambda r: f"{r['name']} ({r['segment']})", axis=1))

        c1, c2 = st.columns(2)
        pm_name = c1.selectbox("Program manager", pms["name"])
        plant_label = c2.selectbox("Plant", plants["label"])

        c1, c2 = st.columns(2)
        kickoff = c1.date_input("Kickoff date", value=date.today())
        sop = c2.date_input("SOP date", value=date.today() + timedelta(days=365))

        c1, c2 = st.columns(2)
        volume = c1.number_input("Annual volume", min_value=0, step=5000, value=50000)
        budget = c2.number_input("Tooling budget ($)", min_value=0, step=5000, value=100000)

        submitted = st.form_submit_button("Save program", type="primary")

    if submitted:
        errors = []
        if not name.strip():
            errors.append("Enter a program name.")
        if sop <= kickoff:
            errors.append("SOP date has to be after the kickoff date.")
        if errors:
            for e in errors:
                st.error(e)
        else:
            cust_id = int(customers.iloc[customers.apply(
                lambda r: f"{r['name']} ({r['segment']})", axis=1).tolist().index(cust_label)]["customer_id"])
            pm_id = int(pms.loc[pms["name"] == pm_name, "employee_id"].iloc[0])
            plant_id = int(plants.loc[plants["label"] == plant_label, "plant_id"].iloc[0])

            with writer() as con:
                cur = con.cursor()
                next_id = cur.execute("SELECT COALESCE(MAX(program_id), 0) + 1 FROM programs").fetchone()[0]
                code = f"PRG-{kickoff.year}-{next_id:03d}"
                cur.execute(
                    """INSERT INTO programs (program_id, program_code, name, customer_id,
                         program_manager_id, plant_id, current_phase, status,
                         kickoff_date, sop_date, annual_volume, tooling_budget)
                       VALUES (?, ?, ?, ?, ?, ?, 'Phase 1 - Plan', 'Green', ?, ?, ?, ?)""",
                    (next_id, code, name.strip(), cust_id, pm_id, plant_id,
                     kickoff.isoformat(), sop.isoformat(), int(volume), float(budget)))
                # Plan the five gate reviews, evenly spaced between kickoff and SOP
                span = (sop - kickoff).days
                for i, gate in enumerate(GATES, start=1):
                    planned = kickoff + timedelta(days=round(span * i / 5))
                    cur.execute(
                        "INSERT INTO gate_reviews (program_id, gate, planned_date) VALUES (?, ?, ?)",
                        (next_id, gate, planned.isoformat()))
            st.success(f"Saved {code} {name.strip()}, with 5 gate reviews planned.")

    st.subheader("Recent programs")
    recent = query("""
        SELECT p.program_code AS Code, p.name AS Name, c.name AS Customer,
               p.current_phase AS Phase, p.status AS Status,
               p.kickoff_date AS Kickoff, p.sop_date AS SOP
        FROM programs p JOIN customers c ON c.customer_id = p.customer_id
        ORDER BY p.program_id DESC LIMIT 10""")
    st.dataframe(recent, hide_index=True, width="stretch")


# ---------- page: purchase orders ----------
elif page == "Purchase orders":
    st.title("Purchase orders")

    suppliers = query("SELECT supplier_id, name, commodity, rating FROM suppliers ORDER BY name")
    supplier_labels = suppliers.apply(lambda r: f"{r['name']} ({r['commodity']}, {r['rating']})", axis=1).tolist()
    plants = query("SELECT plant_id, plant_code || ' – ' || name AS label FROM plants ORDER BY plant_id")

    # ---- new PO ----
    st.subheader("New purchase order")
    with st.form("new_po", clear_on_submit=True):
        c1, c2 = st.columns(2)
        sup_label = c1.selectbox("Supplier", supplier_labels)
        plant_label = c2.selectbox("Ship to plant", plants["label"])

        c1, c2 = st.columns(2)
        order_date = c1.date_input("Order date", value=date.today())
        promised = c2.date_input("Promised date", value=date.today() + timedelta(days=30))

        st.caption("Line items: click a cell to edit, use the + row at the bottom to add lines")
        lines = st.data_editor(
            pd.DataFrame({"item": [""], "qty": [1000], "unit_price": [0.0]}),
            num_rows="dynamic", hide_index=True, width="stretch",
            column_config={
                "item": st.column_config.TextColumn("Item", required=True),
                "qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, required=True),
                "unit_price": st.column_config.NumberColumn("Unit price ($)", min_value=0.0, format="$%.4f", required=True),
            })
        submitted = st.form_submit_button("Save PO", type="primary")

    if submitted:
        clean = lines.dropna(subset=["item", "qty", "unit_price"])
        clean = clean[clean["item"].astype(str).str.strip() != ""]
        errors = []
        if clean.empty:
            errors.append("Add at least one line item with an item name, qty, and price.")
        if promised < order_date:
            errors.append("Promised date can't be before the order date.")
        if errors:
            for e in errors:
                st.error(e)
        else:
            sup_id = int(suppliers.iloc[supplier_labels.index(sup_label)]["supplier_id"])
            plant_id = int(plants.loc[plants["label"] == plant_label, "plant_id"].iloc[0])
            with writer() as con:
                cur = con.cursor()
                next_id = cur.execute("SELECT COALESCE(MAX(po_id), 0) + 1 FROM purchase_orders").fetchone()[0]
                po_number = f"PO-{25000 + next_id}"
                cur.execute(
                    """INSERT INTO purchase_orders (po_id, po_number, supplier_id, plant_id,
                         order_date, promised_date, received_date)
                       VALUES (?, ?, ?, ?, ?, ?, NULL)""",
                    (next_id, po_number, sup_id, plant_id, order_date.isoformat(), promised.isoformat()))
                for _, r in clean.iterrows():
                    cur.execute("INSERT INTO po_lines (po_id, item, qty, unit_price) VALUES (?, ?, ?, ?)",
                                (next_id, str(r["item"]).strip(), int(r["qty"]), float(r["unit_price"])))
            total = float((clean["qty"] * clean["unit_price"]).sum())
            st.success(f"Saved {po_number}: {len(clean)} line(s), total ${total:,.2f}")

    st.divider()

    # ---- receive a PO ----
    st.subheader("Receive a PO")
    open_pos = query("""
        SELECT po.po_id, po.po_number, s.name AS supplier, po.promised_date
        FROM purchase_orders po JOIN suppliers s ON s.supplier_id = po.supplier_id
        WHERE po.received_date IS NULL ORDER BY po.promised_date""")
    if open_pos.empty:
        st.info("No open POs. Everything has been received.")
    else:
        open_labels = open_pos.apply(
            lambda r: f"{r['po_number']} – {r['supplier']} (promised {r['promised_date']})", axis=1).tolist()
        with st.form("receive_po"):
            c1, c2 = st.columns([2, 1])
            pick = c1.selectbox("Open PO", open_labels)
            rec_date = c2.date_input("Received date", value=date.today())
            received = st.form_submit_button("Mark received")
        if received:
            row = open_pos.iloc[open_labels.index(pick)]
            with writer() as con:
                con.execute("UPDATE purchase_orders SET received_date = ? WHERE po_id = ?",
                            (rec_date.isoformat(), int(row["po_id"])))
            late = (rec_date - date.fromisoformat(row["promised_date"])).days
            timing = f"{late} day(s) late" if late > 0 else "on time"
            st.success(f"{row['po_number']} marked received ({timing}).")

    st.divider()

    # ---- recent POs ----
    st.subheader("Recent POs")
    recent = query("""
        SELECT po.po_number AS "PO", s.name AS Supplier, pl.plant_code AS Plant,
               po.order_date AS Ordered, po.promised_date AS Promised,
               COALESCE(po.received_date, 'Open') AS Received,
               ROUND(SUM(l.qty * l.unit_price), 2) AS "Total ($)"
        FROM purchase_orders po
        JOIN suppliers s ON s.supplier_id = po.supplier_id
        JOIN plants pl ON pl.plant_id = po.plant_id
        LEFT JOIN po_lines l ON l.po_id = po.po_id
        GROUP BY po.po_id ORDER BY po.po_id DESC LIMIT 10""")
    st.dataframe(recent, hide_index=True, width="stretch")


# ---------- page: production runs ----------
elif page == "Production runs":
    st.title("Production runs")
    st.caption("Log a shift's output. Scrap is the total of defects marked Scrap, so the two always match.")

    parts = query("""SELECT pt.part_id, pt.part_number || ' – ' || pt.description AS label
                     FROM parts pt ORDER BY pt.part_number""")
    plants = query("SELECT plant_id, plant_code || ' – ' || name AS label FROM plants ORDER BY plant_id")
    defect_types = query("SELECT DISTINCT defect_type FROM defects ORDER BY defect_type")["defect_type"].tolist()

    with st.form("new_run", clear_on_submit=True):
        c1, c2 = st.columns(2)
        part_label = c1.selectbox("Part", parts["label"])
        plant_label = c2.selectbox("Plant", plants["label"])

        c1, c2, c3 = st.columns(3)
        run_date = c1.date_input("Run date", value=date.today())
        shift = c2.radio("Shift", [1, 2, 3], horizontal=True)
        produced = c3.number_input("Qty produced", min_value=1, step=100, value=2000)

        st.caption("Defects: one line per defect type. Use the + row to add lines; leave empty if the run was clean.")
        defects_in = st.data_editor(
            pd.DataFrame({"defect_type": pd.Series(dtype="str"), "qty": pd.Series(dtype="int"),
                          "disposition": pd.Series(dtype="str")}),
            num_rows="dynamic", hide_index=True, width="stretch",
            column_config={
                "defect_type": st.column_config.SelectboxColumn("Defect type", options=defect_types, required=True),
                "qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, required=True),
                "disposition": st.column_config.SelectboxColumn(
                    "Disposition", options=["Scrap", "Rework", "Use As Is"], default="Scrap", required=True),
            })
        submitted = st.form_submit_button("Save run", type="primary")

    if submitted:
        d = defects_in.dropna(subset=["defect_type", "qty"]).copy()
        d["disposition"] = d["disposition"].fillna("Scrap")
        scrapped = int(d.loc[d["disposition"] == "Scrap", "qty"].sum()) if not d.empty else 0
        if scrapped > produced:
            st.error(f"Scrapped ({scrapped:,}) can't be more than produced ({produced:,}).")
        else:
            part_id = int(parts.loc[parts["label"] == part_label, "part_id"].iloc[0])
            plant_id = int(plants.loc[plants["label"] == plant_label, "plant_id"].iloc[0])
            with writer() as con:
                cur = con.cursor()
                cur.execute("""INSERT INTO production_runs (part_id, plant_id, run_date, shift, qty_produced, qty_scrapped)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (part_id, plant_id, run_date.isoformat(), int(shift), int(produced), scrapped))
                run_id = cur.lastrowid
                for _, r in d.iterrows():
                    cur.execute("INSERT INTO defects (run_id, defect_type, qty, disposition) VALUES (?, ?, ?, ?)",
                                (run_id, r["defect_type"], int(r["qty"]), r["disposition"]))
            pct = 100 * scrapped / produced
            st.success(f"Saved run #{run_id}: {produced:,} produced, {scrapped:,} scrapped ({pct:.2f}%), "
                       f"{len(d)} defect line(s).")

    st.subheader("Recent runs")
    recent = query("""
        SELECT r.run_id AS "Run", r.run_date AS Date, pl.plant_code AS Plant, r.shift AS Shift,
               pt.part_number AS Part, r.qty_produced AS Produced, r.qty_scrapped AS Scrapped,
               ROUND(100.0 * r.qty_scrapped / r.qty_produced, 2) AS "Scrap %"
        FROM production_runs r
        JOIN plants pl ON pl.plant_id = r.plant_id
        JOIN parts pt ON pt.part_id = r.part_id
        ORDER BY r.run_id DESC LIMIT 10""")
    st.dataframe(recent, hide_index=True, width="stretch")


# ---------- page: browse data ----------
elif page == "Browse data":
    st.title("Browse data")
    tables = query("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")["name"].tolist()
    c1, c2 = st.columns([1, 2])
    table = c1.selectbox("Table", tables, index=tables.index("programs"))
    search = c2.text_input("Search", placeholder="Type to filter rows")

    df = query(f'SELECT * FROM "{table}"')
    if search:
        mask = df.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        df = df[mask]
    st.caption(f"{len(df):,} rows")
    st.dataframe(df, hide_index=True, width="stretch")
