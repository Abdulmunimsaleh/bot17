from fastapi import FastAPI
from fastapi.responses import JSONResponse
import google.generativeai as genai
import re
from datetime import datetime
import requests

app = FastAPI()

# Gemini config
genai.configure(api_key="AIzaSyAcQ64mgrvtNfTR3ebbHcZxzWfRkWHyI-E")
model = genai.GenerativeModel("gemini-1.5-pro")

# Keywords that suggest the user hasn't provided enough travel info yet
initial_intent_keywords = [
    "i want to go", "i want a trip", "plan a trip", "i want to travel", "book a flight", "trip please", "vacation", "holiday"
]

# Format key details only
def format_short(text):
    lines = text.strip().split('\n')
    filtered = []
    keywords = ["Destination", "Trip Type", "Duration", "Highlights", "Key Activities", "-"]
    for line in lines:
        if any(k.lower() in line.lower() for k in keywords):
            filtered.append(line.strip())
    return "\n".join(filtered[:15])  # limit to first 15 matching lines

# Simple intent detection
def is_general_travel_request(message: str) -> bool:
    return any(kw in message.lower() for kw in initial_intent_keywords)

# Function to extract flight details with flexible date formats
def extract_flight_info(message: str):
    # More flexible patterns to match different sentence structures
    patterns = [
        # Original pattern: "from X to Y on Z"
        r"\bfrom (\w+)\s+to (\w+)\s+on\s+([A-Za-z]+(?: \d{1,2})?|\d{4}-\d{2}-\d{2})\b",
        
        # New pattern: "to Y from X on Z"
        r"\bto (\w+)\s+from (\w+)\s+on\s+([A-Za-z]+(?: \d{1,2})?|\d{4}-\d{2}-\d{2})\b",
        
        # Additional pattern: "I want to go to Y from X on Z"
        r"want to go to (\w+)\s+from (\w+)\s+on\s+([A-Za-z]+(?: \d{1,2})?|\d{4}-\d{2}-\d{2})\b",
        
        # Additional pattern for more variations
        r"(?:travel|fly|trip)(?:\s+to)?\s+(\w+)\s+from\s+(\w+)\s+on\s+([A-Za-z]+(?: \d{1,2})?|\d{4}-\d{2}-\d{2})\b"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message.lower())
        if match:
            # For patterns where destination comes first (to Y from X)
            if "to" in pattern.split("from")[0]:
                destination = match.group(1).capitalize()
                origin = match.group(2).capitalize()
            # For patterns where origin comes first (from X to Y)
            else:
                origin = match.group(1).capitalize()
                destination = match.group(2).capitalize()
                
            departure_date = match.group(3)

            # Convert textual dates like 'June 15' to a standard format like '2025-06-15'
            try:
                if re.match(r'\d{4}-\d{2}-\d{2}', departure_date):  # If date is in YYYY-MM-DD format
                    departure_date = datetime.strptime(departure_date, "%Y-%m-%d").strftime("%Y-%m-%d")
                else:  # If date is in Month Day format (e.g., June 15)
                    # Use CURRENT year (not next year) for date
                    current_year = datetime.now().year
                    date_with_year = f"{departure_date} {current_year}"
                    
                    # Try different date formats
                    for date_format in ["%B %d %Y", "%b %d %Y"]:
                        try:
                            parsed_date = datetime.strptime(date_with_year, date_format)
                            departure_date = parsed_date.strftime("%Y-%m-%d")
                            print(f"Successfully parsed date to: {departure_date}")
                            break
                        except ValueError:
                            continue
            except Exception as e:
                print(f"Date parsing error: {e}")
                return None, None, None  # Return None if date parsing fails

            return origin, destination, departure_date

    # If no matches were found with any pattern
    return None, None, None

# Function to get city code from city name using the cities API
def get_city_code(city_name):
    try:
        cities_api_url = f"https://tripzoori01-app.fly.dev/api/v1/base/cities/search?query={city_name}"
        print(f"Calling cities API: {cities_api_url}")
        cities_response = requests.get(cities_api_url)
        
        if cities_response.status_code == 200:
            cities_data = cities_response.json()
            print(f"Cities API response: {cities_data}")
            if cities_data and len(cities_data) > 0:
                # Return the airport code of the first matching city
                return cities_data[0].get("code")
    except Exception as e:
        print(f"Error fetching city code: {e}")
    
    return None

@app.get("/chat")
async def chat_endpoint(message: str = ""):
    if not message:
        return JSONResponse(status_code=400, content={"error": "Missing 'message' query parameter"})

    try:
        print(f"Processing message: '{message}'")
        
        # Extract flight details first
        origin, destination, departure_date = extract_flight_info(message)
        
        if origin and destination and departure_date:
            print(f"Extracted: Origin={origin}, Destination={destination}, Date={departure_date}")
            
            # Get airport codes for the cities
            origin_code = get_city_code(origin)
            destination_code = get_city_code(destination)
            
            # If we couldn't find the codes, use the city names as a fallback
            if not origin_code:
                print(f"Could not find code for {origin}, using name")
                origin_code = origin
            if not destination_code:
                print(f"Could not find code for {destination}, using name")
                destination_code = destination
                
            print(f"Using codes: Origin={origin_code}, Destination={destination_code}")
            
            # Make API call to get flight info using the user's actual inputs
            flight_api_url = f"https://tripzoori01-app.fly.dev/api/v1/flights/search?origin={origin_code}&destination={destination_code}&departure_date={departure_date}"
            print(f"Flight API URL: {flight_api_url}")
            
            flight_response = requests.get(flight_api_url)
            print(f"Flight API status code: {flight_response.status_code}")
            
            if flight_response.status_code == 200:
                flight_data = flight_response.json()
                
                # Extract itineraries from the flight data
                flight_info = flight_data.get("itineraries", [])
                print(f"Found {len(flight_info)} flight itineraries")
                
                if flight_info:
                    # Format a nice response with the flight details
                    flight_summary = flight_info[0]  # Get the first flight option
                    
                    # Extract key details for a clean response
                    segments = flight_summary.get("segments", [])
                    
                    if segments:
                        # Format departure and arrival details
                        first_segment = segments[0]
                        last_segment = segments[-1]
                        
                        # Format times for display
                        dep_time = datetime.fromisoformat(first_segment["departureTime"].replace('Z', '+00:00'))
                        arr_time = datetime.fromisoformat(last_segment["arrivalTime"].replace('Z', '+00:00'))
                        formatted_dep_time = dep_time.strftime("%B %d, %Y at %H:%M")
                        formatted_arr_time = arr_time.strftime("%B %d, %Y at %H:%M")
                        
                        # Calculate total duration across all segments
                        total_duration_minutes = sum(segment.get("duration", 0) for segment in segments)
                        hours = total_duration_minutes // 60
                        minutes = total_duration_minutes % 60
                        
                        # Get price
                        price_info = flight_summary.get("price", {})
                        total_fare = price_info.get("totalFare", "N/A")
                        currency = price_info.get("currency", "USD")
                        
                        # Create a clean response
                        formatted_response = (
                            f"Flight found from {origin} to {destination}!\n\n"
                            f"Departure: {first_segment.get('departureCity')} ({first_segment.get('departureAirportCode')}) on {formatted_dep_time}\n"
                            f"Arrival: {last_segment.get('arrivalCity')} ({last_segment.get('arrivalAirportCode')}) on {formatted_arr_time}\n"
                            f"Duration: {hours}h {minutes}m\n"
                            f"Stops: {len(segments) - 1}\n"
                            f"Price: {currency} {total_fare}\n"
                            f"Airline: {first_segment.get('airlineName')}"
                        )
                        
                        return {"response": formatted_response}
                    else:
                        return {"response": f"Flight found from {origin} to {destination}, but no segment details available."}
                else:
                    # No flights found with the user's parameters
                    return {"response": f"No flights found from {origin} ({origin_code}) to {destination} ({destination_code}) on {departure_date}."}
            else:
                error_message = flight_response.text if hasattr(flight_response, 'text') else "Unknown error"
                return {"response": f"Sorry, I couldn't find flight information. The flight search API returned status: {flight_response.status_code}. Error: {error_message}"}

        # If flight details aren't found, process general travel intent
        if is_general_travel_request(message):
            return {
                "response": (
                    "Great! Let's plan your trip. I need a few details first:\n"
                    "1. Where do you want to go?\n"
                    "2. Where are you departing from?\n"
                    "3. What date do you want to travel?\n"
                    "You can answer all at once, like: 'I want to go to Paris from Nairobi on June 15'."
                )
            }

        # Otherwise proceed to generate full response
        prompt = (
            f"You are a smart travel assistant. A user says: '{message}'.\n"
            f"Reply in a concise format only including:\n"
            f"- Destination\n- Trip type\n- Duration\n- 4–5 key highlights\n"
            f"Do not include full-day itineraries or example prompts."
        )
        response = model.generate_content(prompt)
        concise_response = format_short(response.text)
        return {"response": concise_response}

    except Exception as e:
        print(f"Exception: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
