from flask import Flask, render_template, request
from datetime import datetime
import requests
import os
from urllib.parse import quote

app = Flask(__name__)

BASE_URL = "https://api.railradar.org/api/v1/trains/between"
STATION_SEARCH_URL = "https://api.railradar.org/api/v1/search/stations?query="
LIVE_API_BASE = "https://api.railradar.org/api/v1/trains"

RAILRADAR_API_KEY = os.environ.get("RAILRADAR_API_KEY")

if not RAILRADAR_API_KEY:
    print("API KEY NOT FOUND")
else:
    print("API KEY LOADED")

def add_api_key(url):
    if "?" in url:
        return f"{url}&apiKey={RAILRADAR_API_KEY}"
    else:
        return f"{url}?apiKey={RAILRADAR_API_KEY}"

@app.route("/test_api")
def test_api():
    try:
        url = add_api_key("https://api.railradar.org/api/v1/search/stations?query=pune")
        response = requests.get(url, timeout=15)
        
        return {
            "status_code": response.status_code,
            "response": response.json()
        }
        
    except Exception as e:
        return {"error": str(e)}

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
        return MANUAL_STATIONS[station_name_lower]

    try:
        url = add_api_key(STATION_SEARCH_URL + quote(station_name))
        response = requests.get(url, timeout=15)
        data = response.json()
        
        data_block = data.get("data") or {}
        stations = data_block.get("stations", []) or []

        if not stations:
            return None

        return stations[0].get("code")

    except Exception as e:
        print("Station API error:", e)
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
            error = f"Invalid station names: {src_name} or {dest_name} not found"
        else:
            try:
                url = add_api_key(f"{BASE_URL}?from={src_code}&to={dest_code}")
                response = requests.get(url, timeout=15)
                data = response.json()

                if not data.get("success"):
                    error = f"API Error: {data.get('error', {}).get('message', 'Failed to fetch trains')}"
                else:
                    data_block = data.get("data") or {}
                    trains_data = (
                        data_block.get("TrainsBetweenStationsResult") or
                        data_block.get("trains") or
                        []
                    )

                    for t in trains_data:
                        from_sched = t.get("fromStationSchedule") or {}
                        to_sched = t.get("toStationSchedule") or {}
                        travel_mins = t.get("travelTimeMinutes") or 0
                        t_type = str(t.get("type") or "N/A")

                        trains.append({
                            "number": str(t.get("trainNumber") or "N/A"),
                            "name": str(t.get("trainName") or "N/A"),
                            "type": t_type,
                            "departure": minutes_to_time(from_sched.get("departureMinutes")),
                            "arrival": minutes_to_time(to_sched.get("arrivalMinutes")),
                            "duration": f"{travel_mins//60}h {travel_mins%60}m",
                            "days": str(t.get("runningDays") or "Daily")
                        })

                    if selected_type != "ALL":
                        trains = [t for t in trains if t["type"].lower() == selected_type.lower()]

                    if not trains:
                        error = f"No trains found between {src_name} ({src_code}) and {dest_name} ({dest_code})."

            except Exception as e:
                print("Train API error:", e)
                error = "Error connecting to train API. Please try again."

    return render_template("index.html", trains=trains, error=error, selected_type=selected_type)

@app.route("/live_status")
def live_status():
    train_number = request.args.get("train_number")
    journey_date = request.args.get("journey_date")

    if not train_number or not journey_date:
        return render_template("live_status.html", error="Enter train number and date")

    try:
        date = datetime.strptime(journey_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        date = journey_date

    try:
        schedule_url = add_api_key(f"{LIVE_API_BASE}/{train_number}/schedule?journeyDate={date}")
        live_url = add_api_key(f"{LIVE_API_BASE}/{train_number}?dataType=live&journeyDate={date}")

        schedule_response = requests.get(schedule_url, timeout=15)
        schedule_data = schedule_response.json()

        if not schedule_data.get("success"):
            error_msg = schedule_data.get('error', {}).get('message', 'Schedule not found')
            return render_template("live_status.html", error=f"Error: {error_msg}")

        data_block = schedule_data.get("data") or {}
        train_info = data_block.get("train") or {}
        route = data_block.get("route") or []

        source_obj = train_info.get("source") or train_info.get("from") or {}
        source = source_obj.get("name") if isinstance(source_obj, dict) else "N/A"
        
        dest_obj = train_info.get("destination") or train_info.get("to") or {}
        destination = dest_obj.get("name") if isinstance(dest_obj, dict) else "N/A"

        live_response = requests.get(live_url, timeout=15)
        live_data = live_response.json()

        current_station = None
        status_message = "No live data"

        if live_data.get("success"):
            l_data_block = live_data.get("data") or {}
            loc = l_data_block.get("currentLocation") or {}
            current_station = loc.get("stationCode")
            status = loc.get("status")

            if status == "AT_STATION":
                status_message = f"At {current_station}"
            elif status == "RUNNING_BETWEEN":
                status_message = "Running between stations"

        return render_template(
            "live_status.html",
            train_number=train_info.get("number", "N/A"),
            train_name=train_info.get("name", "N/A"),
            source=source,
            destination=destination,
            route=route,
            current_station=current_station,
            status_message=status_message
        )

    except Exception as e:
        print("Live error:", e)
        return render_template("live_status.html", error="Error fetching live data. Train might not be running today.")

@app.route("/train_details")
def train_details():
    train_number = request.args.get("train_number")

    if not train_number:
        return render_template("train_details.html", train_info=None)

    try:
        url = add_api_key(f"{LIVE_API_BASE}/{train_number}")
        response = requests.get(url, timeout=15)
        data = response.json()

        if not data.get("success"):
            error_msg = data.get('error', {}).get('message', 'Train not found')
            return render_template("train_details.html", error=f"Error: {error_msg}")
            
        data_block = data.get("data") or {}
        train_info = data_block.get("train") or {}

        return render_template("train_details.html", train_info=train_info)

    except Exception as e:
        print("Details error:", e)
        return render_template("train_details.html", error="Error fetching details")

@app.route("/about")
def about():
    return render_template("about.html")

if __name__ == "__main__":
    app.run(debug=True)
