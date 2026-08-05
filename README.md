# Gym Progress Dashboard (Flask + pandas)

A self-hosted training dashboard that reads your workouts and body
metrics straight from a single Excel file and turns them into an
interactive web report: KPIs, cycle-phase-aware progressive overload
suggestions, PR tracker, weekly schedule, training calendar, and
weight/volume trends — no database required.

**🔗 Live demo:** [https://gym-progress-dashboard.onrender.com](https://gym-tracker-dashboard.onrender.com)

This is a Tailwind-free, plain HTML + Chart.js template. The data is
NOT hardcoded in a JSON file: a local server (Flask) reads your Excel
workbook with `pandas` / `openpyxl` every time the page requests it.

It's not Streamlit. It's a minimal server + your usual HTML.

## Run

Just open the link: **https://gym-tracker-dashboard.onrender.com**

Or run it locally:

```
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

## Add new data

1. Edit `Gym_Tracker.xlsx` (it sits next to `app.py`) and add your rows
   as usual, in any of its sheets:
   - **Workout Log** — one row per exercise/set logged.
   - **Body Metrics** — one row per weigh-in.
   - **Phase Reference** — editable cycle-phase rules (day ranges, rep
     targets, notes). The dashboard always reads from here, nothing is
     hardcoded in the app.
   - **Cycle Settings** — log the first day of each cycle here (most
     recent at the bottom).
   - **Weekly Schedule** — your recurring weekly plan.
2. Save the Excel file.
3. Refresh the page in the browser (F5).

No need to restart the server or touch any code: every time the browser
requests `/api/data`, Flask reopens the Excel file with pandas and
recalculates everything from scratch (KPIs, progressive overload
suggestions per phase, PR tracker, weight trend, volume trend, monthly
calendar, and progress overview).

## Structure

```
gym-dashboard/
├── app.py                  <- Flask server: reads Gym_Tracker.xlsx with pandas
│                              and exposes /api/data
├── requirements.txt
├── Procfile                <- tells Render how to start the app
├── render.yaml              <- Render Blueprint config
├── Gym_Tracker.xlsx         <- your training data (edit it freely)
└── static/
    ├── index.html           <- dashboard template, no design changes needed
    ├── style.css             <- styling
    └── app.js                <- rendering logic + fetch to /api/data
```

## Notes

- `Gym_Tracker.xlsx` must keep the same file name and stay in this
  folder (next to `app.py`, not inside `static/`).
- If you move or rename the Excel file, edit `GYM_FILE` at the top of
  `app.py`.
- Body weight can be logged in kg or lbs — the app detects the column
  header (`Body Weight (kg)` vs `Body Weight (lbs)`) and converts to
  lbs automatically for the dashboard.
- If no cycle start date is logged in **Cycle Settings**, the
  phase-related cards simply show "Not set" instead of erroring out.

