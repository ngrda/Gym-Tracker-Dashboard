"""
Gym Progress Dashboard - Web API Application.
Parses a local Excel workbook and outputs consolidated training analytics via REST,
including cycle-phase-aware progressive overload suggestions.
"""

from pathlib import Path
from datetime import date, datetime
from typing import Dict, Any, List, Optional
import calendar
import re
import openpyxl

import pandas as pd
from flask import Flask, jsonify, send_from_directory

# ------------------------------------------------------------------
# Configuration & Application Setup
# ------------------------------------------------------------------
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
GYM_FILE = APP_DIR / "Gym_Tracker.xlsx"

DEFAULT_CYCLE_LENGTH = 28
KG_TO_LBS = 2.20462

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")


# ------------------------------------------------------------------
# Helper Functions (Data parsing and safety conversions)
# ------------------------------------------------------------------

def _read_sheet(path: Path, sheet: str, skiprows: int = 4) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet, skiprows=skiprows)
    df = df.dropna(how="all")
    return df


def parse_reps(raw) -> List[int]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, (int, float)):
        return [int(raw)]
    text = str(raw).strip()
    if not text:
        return []
    parts = re.split(r"[-,/]", text)
    reps = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            reps.append(int(p))
    return reps


def safe_float(val) -> Optional[float]:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_int(val, default=None):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        return int(val)
    except (ValueError, TypeError):
        return default


# ------------------------------------------------------------------
# Excel Sheet Loaders (Workout log, body metrics, schedule, etc.)
# ------------------------------------------------------------------

def load_workout_log() -> pd.DataFrame:
    df = _read_sheet(GYM_FILE, "Workout Log")
    df = df.rename(columns=lambda c: str(c).strip())

    weight_col = next((c for c in df.columns if c.startswith("Weight")), "Weight")
    df = df.dropna(subset=["Date", "Exercise"])

    records = []
    for _, row in df.iterrows():
        reps_list = parse_reps(row.get("Reps"))
        sets_declared = safe_int(row.get("Sets"))
        if len(reps_list) == 1 and sets_declared and sets_declared > 1:
            reps_list = reps_list * sets_declared

        weight = safe_float(row.get(weight_col)) or 0.0
        total_reps = sum(reps_list) if reps_list else 0
        min_reps = min(reps_list) if reps_list else None
        actual_sets = len(reps_list) if reps_list else sets_declared
        volume = round(weight * total_reps, 1)

        records.append({
            "date": pd.to_datetime(row["Date"]),
            "exercise": str(row["Exercise"]).strip(),
            "category": str(row.get("Category", "")).strip(),
            "weight": weight,
            "is_bodyweight": weight == 0.0,
            "reps_list": reps_list,
            "total_reps": total_reps,
            "min_reps": min_reps,
            "sets": actual_sets,
            "volume": volume,
        })

    out = pd.DataFrame(records)
    if not out.empty:
        out["date_key"] = out["date"].dt.strftime("%Y-%m-%d")
    return out


def load_body_metrics() -> pd.DataFrame:
    df = _read_sheet(GYM_FILE, "Body Metrics")
    df = df.dropna(subset=["Date"])
    df["Date"] = pd.to_datetime(df["Date"])
    weight_col = next((c for c in df.columns if "Weight" in str(c)), None)
    
    is_kg = "kg" in str(weight_col).lower() if weight_col else False
    
    df["weight_raw"] = pd.to_numeric(df[weight_col], errors="coerce")
    df = df.dropna(subset=["weight_raw"]).sort_values("Date")
    
    if is_kg:
        df["weight"] = (df["weight_raw"] * KG_TO_LBS).round(1)
    else:
        df["weight"] = df["weight_raw"].round(1)

    return df[["Date", "weight"]].rename(columns={"Date": "date"})


def load_phase_reference() -> pd.DataFrame:
    df = _read_sheet(GYM_FILE, "Phase Reference")
    df = df.dropna(subset=["Phase"])
    return df


def load_cycle_settings():
    wb = openpyxl.load_workbook(GYM_FILE, data_only=True)
    ws = wb["Cycle Settings"]

    starts = []
    for row in ws.iter_rows(min_row=6, max_col=2, values_only=True):
        start_val, length_val = row[0], row[1]
        if start_val is None:
            continue
        if isinstance(start_val, str):
            start_val = pd.to_datetime(start_val)
        starts.append((start_val, safe_int(length_val, DEFAULT_CYCLE_LENGTH)))

    if not starts:
        return None, DEFAULT_CYCLE_LENGTH
    starts.sort(key=lambda t: t[0])
    last_start, cycle_length = starts[-1]
    return last_start, cycle_length or DEFAULT_CYCLE_LENGTH


def load_weekly_schedule() -> List[Dict[str, str]]:
    try:
        df = _read_sheet(GYM_FILE, "Weekly Schedule")
        df = df.dropna(subset=["Day"])
        return [{"day": r["Day"], "activity": r.get("Activity", "")} for _, r in df.iterrows()]
    except Exception:
        return []


# ------------------------------------------------------------------
# Cycle Phase Computation
# ------------------------------------------------------------------

def compute_current_phase(today: date) -> Dict[str, Any]:
    last_start, cycle_length = load_cycle_settings()
    phases = load_phase_reference()

    if last_start is None:
        return {
            "available": False,
            "message": "No cycle start date logged yet in Cycle Settings.",
        }

    start_date = last_start.date() if isinstance(last_start, (pd.Timestamp, datetime)) else last_start
    cycle_day = ((today - start_date).days % cycle_length) + 1

    match = phases[(phases["Start Day"] <= cycle_day) & (phases["End Day"] >= cycle_day)]
    if match.empty:
        return {
            "available": False,
            "cycle_day": cycle_day,
            "cycle_length": cycle_length,
            "message": "No matching phase found - check the Phase Reference sheet.",
        }

    row = match.iloc[0]
    
    phase_raw = str(row["Phase"]).strip()
    goal = row.get("Main Goal")
    goal_str = str(goal).strip() if goal and not pd.isna(goal) else ""

    if "Follicular" in phase_raw or "Folicular" in phase_raw or "Hypertrophy" in goal_str or "Hipertrofia" in goal_str:
        training_target = "Hypertrophy & Strength"
        rep_min, rep_max = 6, 12
    elif "Ovulation" in phase_raw or "Ovulacion" in phase_raw or "Max Strength" in goal_str or "Fuerza" in goal_str:
        training_target = "Max Strength"
        rep_min, rep_max = 1, 6
    elif ("Luteal" in phase_raw and "Premenstrual" not in phase_raw and "Late" not in phase_raw) or "Endurance" in goal_str or "Resistencia" in goal_str:
        training_target = "Endurance"
        rep_min, rep_max = 12, 15
    elif "Premenstrual" in phase_raw or "Late Luteal" in phase_raw or "Deload" in goal_str or "Descarga" in goal_str:
        training_target = "Deload"
        rep_min, rep_max = 15, 20
    else:
        training_target = goal_str or "Hypertrophy & Strength"
        rep_min = safe_int(row.get("Rep Target Min"), 6)
        rep_max = safe_int(row.get("Rep Target Max"), 12)

    excel_min = safe_int(row.get("Rep Target Min"))
    excel_max = safe_int(row.get("Rep Target Max"))
    if excel_min is not None and excel_max is not None:
        rep_min, rep_max = excel_min, excel_max

    return {
        "available": True,
        "cycle_day": cycle_day,
        "cycle_length": cycle_length,
        "phase": phase_raw,
        "hormones": row.get("Dominant Hormones", ""),
        "goal": training_target,
        "rep_target_min": rep_min,
        "rep_target_max": rep_max,
        "notes": row.get("Training Notes", ""),
    }


# ------------------------------------------------------------------
# Progressive Overload & Phase Tagging Logic
# ------------------------------------------------------------------

def build_overload_suggestions(workout_log: pd.DataFrame, phase: Dict[str, Any]) -> List[Dict[str, Any]]:
    if workout_log.empty:
        return []

    target_min = phase.get("rep_target_min") if phase.get("available") else None
    target_max = phase.get("rep_target_max") if phase.get("available") else None

    suggestions = []
    for exercise, grp in workout_log.groupby("exercise"):
        grp_sorted = grp.sort_values("date")
        latest = grp_sorted.iloc[-1]
        
        reps_list = latest.get("reps_list") or []
        avg_reps = sum(reps_list) / len(reps_list) if reps_list else (safe_int(latest.get("min_reps")) or 0)
        is_bw = bool(latest["is_bodyweight"])
        
        ex_lower = exercise.lower()
        is_pullup = "pull" in ex_lower and "up" in ex_lower

        suggestion = "-"
        badge = "neutral"

        if target_min is not None and target_max is not None and reps_list:
            if avg_reps > target_max:
                if is_pullup:
                    suggestion = "Add less assistance weight"
                elif is_bw:
                    suggestion = "Add resistance / a harder variation"
                else:
                    suggestion = "Increase weight next session"
                badge = "up"
            elif len(grp_sorted) > 1:
                prev = grp_sorted.iloc[-2]
                prev_reps = prev.get("reps_list") or []
                if prev_reps and reps_list[0] < prev_reps[0] and float(latest["weight"]) == float(prev["weight"]):
                    suggestion = "Maintain weight & complete all reps"
                    badge = "hold"

            if suggestion == "-":
                if is_bw and avg_reps < target_min:
                    suggestion = "Pick an easier variation or rest"
                    badge = "down"
                elif not is_bw:
                    suggestion = ""
                    badge = "neutral"

        suggestions.append({
            "exercise": exercise,
            "category": latest["category"],
            "last_date": latest["date"].strftime("%b %d, %Y"),
            "weight": float(latest["weight"]),
            "is_bodyweight": is_bw,
            "last_reps": [int(x) for x in reps_list],
            "min_reps": safe_int(latest["min_reps"]),
            "suggestion": suggestion,
            "badge": badge,
        })

    suggestions.sort(key=lambda s: s["exercise"])
    return suggestions


def tag_workout_phases(workout_log: pd.DataFrame, phases: pd.DataFrame, last_start, cycle_length: int) -> pd.Series:
    if workout_log.empty or last_start is None:
        return pd.Series([None] * len(workout_log), index=workout_log.index, dtype=object)

    start_date = last_start.date() if isinstance(last_start, (pd.Timestamp, datetime)) else last_start

    def phase_for_date(d):
        dd = d.date() if isinstance(d, (pd.Timestamp, datetime)) else d
        cycle_day = ((dd - start_date).days % cycle_length) + 1
        match = phases[(phases["Start Day"] <= cycle_day) & (phases["End Day"] >= cycle_day)]
        if match.empty:
            return None
        return str(match.iloc[0]["Phase"]).strip()

    return workout_log["date"].apply(phase_for_date)


def build_overload_by_phase(
    workout_log: pd.DataFrame, phases: pd.DataFrame, last_start, cycle_length: int
) -> List[Dict[str, Any]]:
    workout_log = workout_log.copy()
    if not workout_log.empty:
        workout_log["_phase"] = tag_workout_phases(workout_log, phases, last_start, cycle_length)

    by_phase = []
    for _, row in phases.iterrows():
        phase_name = str(row["Phase"]).strip()
        goal = row.get("Main Goal")
        goal_str = str(goal).strip() if goal is not None and not pd.isna(goal) else phase_name
        notes = row.get("Training Notes")
        notes_str = str(notes).strip() if notes is not None and not pd.isna(notes) else ""
        rep_min = safe_int(row.get("Rep Target Min"))
        rep_max = safe_int(row.get("Rep Target Max"))

        phase_dict = {
            "available": rep_min is not None and rep_max is not None,
            "rep_target_min": rep_min,
            "rep_target_max": rep_max,
        }

        if not workout_log.empty and last_start is not None:
            phase_log = workout_log[workout_log["_phase"] == phase_name]
        else:
            phase_log = workout_log.iloc[0:0]

        by_phase.append({
            "phase": phase_name,
            "goal": goal_str,
            "rep_target_min": rep_min,
            "rep_target_max": rep_max,
            "notes": notes_str,
            "start_day": safe_int(row.get("Start Day")),
            "end_day": safe_int(row.get("End Day")),
            "suggestions": build_overload_suggestions(phase_log, phase_dict),
        })

    by_phase.sort(key=lambda p: (p["start_day"] is None, p["start_day"]))
    return by_phase


# ------------------------------------------------------------------
# Monthly Calendar Builder
# ------------------------------------------------------------------

def build_calendar_month(workout_log: pd.DataFrame, today: date) -> Dict[str, Any]:
    first_weekday, num_days = calendar.monthrange(today.year, today.month)

    trained_days: List[int] = []
    if not workout_log.empty:
        month_mask = (workout_log["date"].dt.year == today.year) & (workout_log["date"].dt.month == today.month)
        month_log = workout_log[month_mask]
        trained_days = sorted(int(d) for d in month_log["date"].dt.day.unique())

    return {
        "month_label": today.strftime("%B %Y"),
        "first_weekday": first_weekday,
        "num_days": num_days,
        "trained_days": trained_days,
        "today_day": today.day,
    }


# ------------------------------------------------------------------
# Main Data Aggregation (KPIs, PRs, Trends, and API Response)
# ------------------------------------------------------------------

def build_gym_data() -> Dict[str, Any]:
    workout_log = load_workout_log()
    body_metrics = load_body_metrics()
    weekly_schedule = load_weekly_schedule()
    today = date.today()
    phase = compute_current_phase(today)

    if not workout_log.empty:
        month_mask = (workout_log["date"].dt.year == today.year) & (workout_log["date"].dt.month == today.month)
        month_log = workout_log[month_mask]
        
        training_dates_month = sorted(month_log["date_key"].unique())
        total_workouts = len(training_dates_month)
        total_volume = round(float(month_log["volume"].sum()), 1)
        
        training_dates_all = sorted(workout_log["date_key"].unique())
    else:
        total_workouts = 0
        total_volume = 0.0
        training_dates_all = []

    current_weight = None
    weight_delta = None
    if not body_metrics.empty:
        current_weight = round(float(body_metrics.iloc[-1]["weight"]), 1)
        if len(body_metrics) > 1:
            weight_delta = round(current_weight - float(body_metrics.iloc[0]["weight"]), 1)

    kpis = {
        "current_weight": current_weight,
        "weight_delta": weight_delta,
        "total_workouts": total_workouts,
        "total_volume": total_volume,
    }

    weight_trend = [
        {"date": r["date"].strftime("%b %d, %Y"), "weight": round(float(r["weight"]), 1)}
        for _, r in body_metrics.iterrows()
    ]

    volume_trend = []
    if not workout_log.empty:
        wl = workout_log.copy()
        wl["week_of_month"] = ((wl["date"].dt.day - 1) // 7) + 1
        wl["week_label"] = "W" + wl["week_of_month"].astype(str) + " " + wl["date"].dt.strftime("%B")
        wl["week_sort_key"] = wl["date"].dt.strftime("%Y-%m") + "-" + wl["week_of_month"].astype(str).str.zfill(2)
        by_week = (
            wl.groupby(["week_sort_key", "week_label"])["volume"]
            .sum()
            .reset_index()
            .sort_values("week_sort_key")
        )
        for _, r in by_week.iterrows():
            volume_trend.append({"date": r["week_label"], "volume": round(float(r["volume"]), 1)})

    pr_tracker = []
    prs_this_month = 0
    if not workout_log.empty:
        for exercise, grp in workout_log.groupby("exercise"):
            grp_sorted = grp.sort_values("date").copy()
            is_bw = bool(grp_sorted.iloc[-1]["is_bodyweight"])
            grp_sorted["max_set_reps"] = grp_sorted["reps_list"].apply(lambda r: max(r) if r else 0)

            if is_bw:
                rep_field = "total_reps"
                ranked = grp_sorted.sort_values(by=["total_reps", "date"], ascending=[True, False])
            else:
                rep_field = "max_set_reps"
                ranked = grp_sorted.sort_values(by=["weight", "max_set_reps", "date"], ascending=[True, True, False])

            best = ranked.iloc[-1]
            best_weight = None if is_bw else float(best["weight"])
            best_reps = int(best[rep_field])

            previous_entries = ranked[ranked["date"] < best["date"]]
            if not previous_entries.empty:
                prev_best = previous_entries.iloc[-1]
                reps_diff = int(best[rep_field] - prev_best[rep_field])
                if is_bw:
                    if reps_diff > 0:
                        vs_last_pr = f"↑ {reps_diff} reps"
                    elif reps_diff < 0:
                        vs_last_pr = f"↓ {abs(reps_diff)} reps"
                    else:
                        vs_last_pr = "→ Matched previous"
                else:
                    weight_diff = round(float(best["weight"] - prev_best["weight"]), 1)
                    if weight_diff > 0:
                        vs_last_pr = f"↑ {weight_diff} lbs"
                    elif weight_diff < 0:
                        vs_last_pr = f"↓ {abs(weight_diff)} lbs"
                    elif reps_diff > 0:
                        vs_last_pr = f"↑ {reps_diff} rep{'s' if reps_diff != 1 else ''} (same weight)"
                    elif reps_diff < 0:
                        vs_last_pr = f"↓ {abs(reps_diff)} rep{'s' if abs(reps_diff) != 1 else ''} (same weight)"
                    else:
                        vs_last_pr = "→ Matched previous"
            else:
                vs_last_pr = "-"

            best_date = best["date"]
            if best_date.year == today.year and best_date.month == today.month:
                prs_this_month += 1

            pr_tracker.append({
                "exercise": exercise,
                "category": best["category"],
                "is_bodyweight": is_bw,
                "best_weight": best_weight,
                "best_reps": best_reps,
                "vs_last_pr": vs_last_pr,
                "date": best_date.strftime("%b %d, %Y"),
            })
        pr_tracker.sort(key=lambda p: p["exercise"])

    kpis["prs_this_month"] = prs_this_month

    overload_suggestions = build_overload_suggestions(workout_log, phase)
    last_start, cycle_length = load_cycle_settings()
    overload_by_phase = build_overload_by_phase(workout_log, load_phase_reference(), last_start, cycle_length)

    calendar_month = build_calendar_month(workout_log, today)

    return {
        "kpis": kpis,
        "cycle": phase,
        "overload_suggestions": overload_suggestions,
        "overload_by_phase": overload_by_phase,
        "pr_tracker": pr_tracker,
        "weight_trend": weight_trend,
        "volume_trend": volume_trend,
        "calendar_month": calendar_month,
        "weekly_schedule": weekly_schedule,
        "training_dates": training_dates_all,
    }


# ------------------------------------------------------------------
# Flask Application Routes & Server Initialization
# ------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/data")
def api_data():
    if not GYM_FILE.exists():
        return jsonify({"error": f"Missing required file: {GYM_FILE.name}"}), 404
    try:
        return jsonify(build_gym_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    app.run(host=host, port=port, debug=False)
