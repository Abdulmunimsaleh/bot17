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
    "i want to go", "i want a trip", "plan a trip", "i want to travel", "book a flight", 
    "trip please", "vacation", "holiday", "travel", "flight", "journey"
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

# Month names for date extraction
MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june", "july", 
    "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"
]

# Improved function to extract flight information from natural language
def extract_flight_info(message: str):
    message = message.lower()
    
    # Dictionary to store extracted info
    info = {
        "origin": None,
        "destination": None,
        "date": None
    }
    
    # --- DESTINATION EXTRACTION ---
    # Look for destination indicators
    dest_patterns = [
        r"(?:to|for|destination|visit|visiting)\s+([a-z]+(?:\s+[a-z]+)?)",
        r"(?:in|at)\s+([a-z]+(?:\s+[a-z]+)?)",
        r"(?:go|going|travel|fly|flying)\s+(?:to|for|into)\s+([a-z]+(?:\s+[a-z]+)?)",
        r"trip\s+to\s+([a-z]+(?:\s+[a-z]+)?)"
    ]
    
    for pattern in dest_patterns:
        match = re.search(pattern, message)
        if match:
            possible_dest = match.group(1).strip()
            # Skip common prepositions and articles that might be caught
            if possible_dest not in ["to", "in", "at", "from", "on", "the", "a", "an"]:
                info["destination"] = possible_dest.capitalize()
                break
    
    # --- ORIGIN EXTRACTION ---
    # Look for origin indicators
    origin_patterns = [
        r"from\s+([a-z]+(?:\s+[a-z]+)?)",
        r"(?:departing|leaving|departure)\s+(?:from)?\s+([a-z]+(?:\s+[a-z]+)?)",
        r"start(?:ing)?\s+(?:from)?\s+([a-z]+(?:\s+[a-z]+)?)"
    ]
    
    for pattern in origin_patterns:
        match = re.search(pattern, message)
        if match:
            possible_origin = match.group(1).strip()
            # Skip common prepositions and articles
            if possible_origin not in ["to", "in", "at", "from", "on", "the", "a", "an"]:
                info["origin"] = possible_origin.capitalize()
                break
    
    # --- DATE EXTRACTION ---
    # Look for various date formats
    
    # Format: YYYY-MM-DD
    date_pattern1 = r"(\d{4}-\d{1,2}-\d{1,2})"
    match = re.search(date_pattern1, message)
    if match:
        info["date"] = match.group(1)
    
    # Format: Month Day (e.g., "June 15", "Jun 15", "June 15th")
    month_pattern = "|".join(MONTH_NAMES)
    date_pattern2 = rf"({month_pattern})\s+(\d{{1,2}}(?:st|nd|rd|th)?)"
    match = re.search(date_pattern2, message)
    if match and not info["date"]:
        month = match.group(1).lower()
        day = re.sub(r'(st|nd|rd|th)', '', match.group(2))
        
        # Convert month abbreviation to full name if needed
        month_mapping = {
            "jan": "january", "feb": "february", "mar": "march", "apr": "april",
            "may": "may", "jun": "june", "jul": "july", "aug": "august",
            "sep": "september", "oct": "october", "nov": "november", "dec": "december"
        }
        
        full_month = month_mapping.get(month, month)
        
        # Use current year
        current_year = datetime.now().year
        date_str = f"{full_month} {day} {current_year}"
        
        try:
            parsed_date = datetime.strptime(date_str, "%B %d %Y")
            info["date"] = parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            pass
    
    # Format: Day Month (e.g., "15 June", "15th June")
    date_pattern3 = rf"(\d{{1,2}}(?:st|nd|rd|th)?)\s+({month_pattern})"
    match = re.search(date_pattern3, message)
    if match and not info["date"]:
        day = re.sub(r'(st|nd|rd|th)', '', match.group(1))
        month = match.group(2).lower()
        
        # Convert month abbreviation to full name if needed
        month_mapping = {
            "jan": "january", "feb": "february", "mar": "march", "apr": "april",
            "may": "may", "jun": "june", "jul": "july", "aug": "august",
            "sep": "september", "oct": "october", "nov": "november", "dec": "december"
        }
        
        full_month = month_mapping.get(month, month)
        
        # Use current year
        current_year = datetime.now().year
        date_str = f"{full_month} {day} {current_year}"
        
        try:
            parsed_date = datetime.strptime(date_str, "%B %d %Y")
            info["date"] = parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            pass
    
    # Format: MM/DD/YYYY or DD/MM/YYYY
    date_pattern4 = r"(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})"
    match = re.search(date_pattern4, message)
    if match and not info["date"]:
        # Ambiguous - try both MM/DD and DD/MM format
        formats = [
            # MM/DD/YYYY
            {
                "month": match.group(1),
                "day": match.group(2),
                "year": match.group(3)
            },
            # DD/MM/YYYY
            {
                "month": match.group(2),
                "day": match.group(1),
                "year": match.group(3)
            }
        ]
        
        for format_dict in formats:
            try:
                # Handle 2-digit years
                year = format_dict["year"]
                if len(year) == 2:
                    # Assume 20XX for years less than 50, 19XX otherwise
                    year = f"20{year}" if int(year) < 50 else f"19{year}"
                
                date_str = f"{year}-{int(format_dict['month']):02d}-{int(format_dict['day']):02d}"
                parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                info["date"] = date_str
                break
            except ValueError:
                continue
    
    # Check if all required info is present
    if info["origin"] and info["destination"] and info["date"]:
        return info["origin"], info["destination"], info["date"]
    else:
        # Use Gemini AI to extract flight info for complex sentences
        if not (info["origin"] and info["destination"] and info["date"]):
            try:
                # Use Gemini to extract missing information
                extraction_prompt = f"""
                Extract travel information from this text: "{message}"
                
                Format the response as JSON with these fields:
                - origin: The city/location the person is departing from
                - destination: The city/location the person is traveling to  
                - date: The travel date in YYYY-MM-DD format
                
                For any missing information, use null.
                """
                
                response = model.generate_content(extraction_prompt)
                
                # Try to parse the AI response
                ai_response_text = response.text
                
                # Extract JSON content by finding text between { and }
                json_match = re.search(r'\{.*\}', ai_response_text, re.DOTALL)
                if json_match:
                    import json
                    try:
                        ai_info = json.loads(json_match.group(0))
                        
                        # Use AI-extracted info to fill in gaps
                        if not info["origin"] and ai_info.get("origin"):
                            info["origin"] = ai_info["origin"].capitalize()
                        
                        if not info["destination"] and ai_info.get("destination"):
                            info["destination"] = ai_info["destination"].capitalize()
                        
                        if not info["date"] and ai_info.get("date"):
                            info["date"] = ai_info["date"]
                    except json.JSONDecodeError:
                        print("Failed to parse AI response as JSON")
            except Exception as e:
                print(f"AI extraction error: {e}")
    
    # Final check if we have all required info
    if info["origin"] and info["destination"] and info["date"]:
        return info["origin"], info["destination"], info["date"]
    
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
        
        # Extract flight details with the more intelligent extraction function
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
                    "You can provide these details in any way that's comfortable for you."
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
