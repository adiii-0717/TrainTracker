from flask import Flask, render_template, request
from datetime import datetime
import requests

app = Flask(__name__)

# ✅ Correct RailRadar API base URLs
BASE_URL = "https://railradar.in/api/v1/trains/between"
STATION_SEARCH_URL = "https://railradar.in/api/v1/search/stations?q="

# ✅ Convert minutes to HH:MM format
def minutes_to_time(minutes):
    if not isinstance(minutes, int):
        return "N/A"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

# ✅ Get station code by name
def get_station_code(station_name):
    """
    Fetches the most appropriate station code for a given name from RailRadar API.
    Prefers main stations over sheds/yards/depots.
    """
    try:
        url = STATION_SEARCH_URL + station_name
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            print(f"❌ Failed to fetch station code for {station_name} (HTTP {response.status_code})")
            return None

        data = response.json()
        stations = data.get("data", {}).get("stations", [])

        if not stations:
            print(f"⚠️ No stations found for {station_name}")
            return None

        # Filter out irrelevant stations (like sheds, depots, yards)
        filtered = [
            s for s in stations
            if not any(bad in s.get("name", "").lower() for bad in ["shed", "yard", "depot", "loco", "cab", "goods"])
        ]

        chosen = filtered[0] if filtered else stations[0]
        code = chosen.get("code")

        print(f"✅ Station '{station_name}' resolved to code: {code} ({chosen.get('name')})")
        return code

    except Exception as e:
        print(f"❌ Error fetching station code for '{station_name}': {e}")
        return None


@app.route("/", methods=["GET", "POST"])
def home():
    trains = []
    error = None
    selected_type = "ALL"  # Default

    if request.method == "POST":
        src_name = request.form.get("source")
        dest_name = request.form.get("destination")
        selected_type = request.form.get("train_type", "ALL")

        # Convert station names to codes
        src_code = get_station_code(src_name)
        dest_code = get_station_code(dest_name)

        if not src_code or not dest_code:
            error = f"Invalid station names entered. Try '{src_name}' and '{dest_name}'."
        else:
            try:
                url = f"{BASE_URL}?from={src_code}&to={dest_code}"
                print(f"🔍 Fetching trains from: {url}")
                response = requests.get(url, timeout=10)
                data = response.json()

                trains_data = data.get("data", {}).get("TrainsBetweenStationsResult", [])
                if not trains_data:
                    trains_data = data.get("data", {}).get("trains", [])

                for t in trains_data:
                    from_sched = t.get("fromStationSchedule", {})
                    to_sched = t.get("toStationSchedule", {})

                    if from_sched.get("stopsAt", True) and to_sched.get("stopsAt", True):
                        trains.append({
                            "number": t.get("trainNumber", "N/A"),
                            "name": t.get("trainName", "N/A"),
                            "type": t.get("type", "N/A"),
                            "departure": minutes_to_time(from_sched.get("departureMinutes")),
                            "arrival": minutes_to_time(to_sched.get("arrivalMinutes")),
                            "duration": f"{t.get('travelTimeMinutes', 0)//60}h {t.get('travelTimeMinutes', 0)%60}m",
                            "days": str(t.get("runningDaysBitmap", "N/A"))
                        })

                # ✅ Apply train type filter
                if selected_type != "ALL":
                    trains = [t for t in trains if t["type"].lower() == selected_type.lower()]
                    print(f"🎯 Filter applied: {selected_type}, Remaining trains: {len(trains)}")

                if not trains:
                    error = "No trains found for selected type or route."

            except Exception as e:
                print(f"❌ Error fetching trains: {e}")
                error = "Error fetching train data. Please try again later."

    return render_template(
        "index.html",
        trains=trains,
        error=error,
        active_page="home",
        selected_type=selected_type
    )


@app.route("/live_status", methods=["GET", "POST"])
def status():
    train_number = request.args.get("train_number")
    journey_date = request.args.get("journey_date")

    def template_minutes_to_time(minutes):
        return minutes_to_time(minutes)

    if not train_number or not journey_date:
        return render_template("live_status.html", error="Please enter both Train Number and Journey Date", minutes_to_time=template_minutes_to_time)

    try:
        converted_date = datetime.strptime(journey_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        converted_date = journey_date

    schedule_url = f"https://railradar.in/api/v1/trains/{train_number}/schedule?journeyDate={converted_date}"
    live_url = f"https://railradar.in/api/v1/trains/{train_number}?dataType=live&journeyDate={converted_date}"

    try:
        schedule_resp = requests.get(schedule_url)
        schedule_data = schedule_resp.json()

        if not schedule_data.get("success"):
            return render_template("live_status.html", error="Train schedule not found.", minutes_to_time=template_minutes_to_time)

        train_info = schedule_data["data"]["train"]
        route = schedule_data["data"]["route"]

        live_resp = requests.get(live_url)
        live_data = live_resp.json() if live_resp.status_code == 200 else {}

        current_station = None
        delay = None
        status_message = "No live data available."

        if live_data.get("success"):
            live_info = live_data["data"]
            current_loc = live_info.get("currentLocation", {})
            current_station = current_loc.get("stationCode", "N/A")
            status = current_loc.get("status", "UNKNOWN")
            delay = live_info.get("overallDelayMinutes", 0)

            if status == "AT_STATION":
                status_message = f"Train is currently standing at {current_station}."
            elif status == "RUNNING_BETWEEN":
                status_message = "Train is currently running between stations."
            else:
                status_message = "Train status is currently unavailable."

        for stop in route:
            stop["isCurrent"] = stop["station"]["code"] == current_station

        return render_template(
            "live_status.html",
            train_number=train_info["number"],
            train_name=train_info["name"],
            source=train_info["source"]["name"],
            destination=train_info["destination"]["name"],
            journey_date=converted_date,
            current_station=current_station,
            delay=delay,
            status_message=status_message,
            route=route,
            minutes_to_time=template_minutes_to_time,
            active_page="live_status"
        )

    except Exception as e:
        print("❌ Error fetching train data:", e)
        return render_template("live_status.html", error="Error fetching train information.", minutes_to_time=template_minutes_to_time)


@app.route("/train_details", methods=["GET"])
def train_details():
    train_number1 = request.args.get("train_number1")
    train_number = request.args.get("train_number")

    train_number = train_number or train_number1
    train_number1 = train_number1 or train_number

    if not train_number:
        return render_template("train_details.html", train_info=None, error=None)

    try:
        url = f"https://railradar.in/api/v1/trains/{train_number}"
        print(f"🔍 Fetching detailed train info from: {url}")
        response = requests.get(url, timeout=10)
        data = response.json()

        if not data.get("success"):
            return render_template("train_details.html", train_info=None, error="Train details not found.")

        train_info = data.get("data", {}).get("train", {})

        return render_template("train_details.html", train_info=train_info, error=None, active_page="train_details")

    except Exception as e:
        print("❌ Error fetching train details:", e)
        return render_template("train_details.html", train_info=None, error="Error fetching train details.")


@app.route("/about")
def about():
    return render_template("about.html", active_page="about")

if __name__ == "__main__":
    app.run(debug=False)
