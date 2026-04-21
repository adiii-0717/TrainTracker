from flask import Flask, render_template, request
from datetime import datetime
import requests
import os
from urllib.parse import quote

app = Flask(__name__)

BASE_URL = "https://api.railradar.org/api/v1/trains/between"
STATION_SEARCH_URL = "https://api.railradar.org/api/v1/search/stations?query="
LIVE_API_BASE = "https://api.railradar.org/api/v1/trains"

RAILRADAR_API_KEY = os.environ.get("RAILRADAR_API_KEY", "") # Render will inject this environment variable securely

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "X-API-Key": RAILRADAR_API_KEY
}

MANUAL_STATIONS = {
    "chinchwad": "CCH",
    "dehu road": "DEHR",
    "pune": "PUNE",
    "mumbai": "CSMT",
    "lonavala": "LNL"
}

def minutes_to_time(minutes):
    if not isinstance(minutes, int):
        return "N/A"
    return f"{minutes//60:02d}:{minutes%60:02d}"

def get_station_code(station_name):
    if not station_name:
        return None

    station_name_lower = station_name.lower().strip()

    if station_name_lower in MANUAL_STATIONS:
        print(f"✅ Manual match: {station_name} → {MANUAL_STATIONS[station_name_lower]}")
        return MANUAL_STATIONS[station_name_lower]

    try:
        url = STATION_SEARCH_URL + quote(station_name)
        print(f"🔍 Searching station: {url}")

        response = requests.get(url, headers=HEADERS, timeout=5)

        try:
            data = response.json()
        except:
            print("❌ JSON decode failed")
            return None

        stations = data.get("data", {}).get("stations", [])

        if not stations:
            print(f"❌ No stations found for: {station_name}")
            return None

        filtered = [
            s for s in stations
            if not any(x in s.get("name", "").lower() for x in ["shed", "yard", "depot"])
        ]

        chosen = filtered[0] if filtered else stations[0]
        code = chosen.get("code")

        print(f"✅ API match: {station_name} → {code}")
        return code

    except Exception as e:
        print("❌ Station API error:", e)
        return None


@app.route("/", methods=["GET", "POST"])
def home():
    trains = []
    error = None
    selected_type = "ALL"

    if request.method == "POST":
        src_name = request.form.get("source")
        dest_name = request.form.get("destination")
        selected_type = request.form.get("train_type", "ALL")

        src_code = get_station_code(src_name)
        dest_code = get_station_code(dest_name)

        if not src_code or not dest_code:
            error = f"Invalid station names. Try simple names like Pune, Mumbai."
        else:
            try:
                url = f"{BASE_URL}?from={src_code}&to={dest_code}"
                print(f"🚀 Fetching trains: {url}")

                response = requests.get(url, headers=HEADERS, timeout=5)

                try:
                    data = response.json()
                except:
                    error = "API response error."
                    return render_template("index.html", trains=[], error=error)

                trains_data = data.get("data", {}).get("TrainsBetweenStationsResult", []) \
                           or data.get("data", {}).get("trains", []) \
                           or []

                for t in trains_data:
                    from_sched = t.get("fromStationSchedule", {})
                    to_sched = t.get("toStationSchedule", {})

                    trains.append({
                        "number": t.get("trainNumber", "N/A"),
                        "name": t.get("trainName", "N/A"),
                        "type": t.get("type", "N/A"),
                        "departure": minutes_to_time(from_sched.get("departureMinutes")),
                        "arrival": minutes_to_time(to_sched.get("arrivalMinutes")),
                        "duration": f"{t.get('travelTimeMinutes',0)//60}h {t.get('travelTimeMinutes',0)%60}m"
                    })

                if selected_type != "ALL":
                    trains = [t for t in trains if t["type"].lower() == selected_type.lower()]

                if not trains:
                    error = "No trains found."

            except Exception as e:
                print("❌ Train API error:", e)
                error = "Error fetching train data."

    return render_template("index.html", trains=trains, error=error, selected_type=selected_type)


@app.route("/live_status", methods=["GET"])
def status():
    train_number = request.args.get("train_number")
    journey_date = request.args.get("journey_date")

    if not train_number or not journey_date:
        return render_template("live_status.html", error="Enter train number and date")

    try:
        date = datetime.strptime(journey_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        date = journey_date

    schedule_url = f"{LIVE_API_BASE}/{train_number}/schedule?journeyDate={date}"
    live_url = f"{LIVE_API_BASE}/{train_number}?dataType=live&journeyDate={date}"

    try:
        schedule_resp = requests.get(schedule_url, headers=HEADERS, timeout=5)
        schedule_data = schedule_resp.json()

        if not schedule_data.get("success"):
            return render_template("live_status.html", error="Schedule not found")

        train_info = schedule_data["data"]["train"]
        route = schedule_data["data"]["route"]

        live_resp = requests.get(live_url, headers=HEADERS, timeout=5)
        live_data = live_resp.json() if live_resp.status_code == 200 else {}

        current_station = None
        status_message = "No live data"

        if live_data.get("success"):
            loc = live_data["data"].get("currentLocation", {})
            current_station = loc.get("stationCode")
            status = loc.get("status")

            if status == "AT_STATION":
                status_message = f"At {current_station}"
            elif status == "RUNNING_BETWEEN":
                status_message = "Running between stations"

        return render_template(
            "live_status.html",
            train_number=train_info["number"],
            train_name=train_info["name"],
            source=train_info["source"]["name"],
            destination=train_info["destination"]["name"],
            route=route,
            current_station=current_station,
            status_message=status_message
        )

    except Exception as e:
        print("❌ Live error:", e)
        return render_template("live_status.html", error="Error fetching data")


@app.route("/train_details")
def train_details():
    train_number = request.args.get("train_number")

    if not train_number:
        return render_template("train_details.html", train_info=None)

    try:
        url = f"{LIVE_API_BASE}/{train_number}"
        response = requests.get(url, headers=HEADERS, timeout=5)
        data = response.json()

        if not data.get("success"):
            return render_template("train_details.html", error="Train not found")

        return render_template("train_details.html", train_info=data["data"]["train"])

    except Exception as e:
        print("❌ Details error:", e)
        return render_template("train_details.html", error="Error fetching details")


@app.route("/about")
def about():
    return render_template("about.html")


if __name__ == "__main__":
    app.run(debug=True)
