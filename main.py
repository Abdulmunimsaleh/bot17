from fastapi import FastAPI
from fastapi.responses import JSONResponse
import google.generativeai as genai
import re
from datetime import datetime
import requests
import json

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

# Enhanced intelligent function to extract travel information using AI
def extract_flight_info(message: str):
    print(f"Extracting flight info from: '{message}'")
    
    # First try using AI extraction to understand the full context
    try:
        extraction_prompt = f"""
        Extract travel information from this text: "{message}"
        
        I need to know:
        - Origin: The city/location the person is departing from
        - Destination: The city/location the person is traveling to  
        - Date: The travel date in YYYY-MM-DD format
        
        The text might contain phrases like "going to X", "from Y", "am from Z", etc.
        Pay close attention to prepositions ("to", "from") to correctly identify origin vs destination.
        
        Format the response in JSON with the fields:
        {{
            "origin": "City name",
            "destination": "City name",
            "date": "YYYY-MM-DD"
        }}
        
        If any information is missing, use null for that field.
        """
        
        response = model.generate_content(extraction_prompt)
        ai_response_text = response.text
        
        # Extract JSON content by finding text between { and }
        json_match = re.search(r'\{.*\}', ai_response_text, re.DOTALL)
        if json_match:
            try:
                ai_info = json.loads(json_match.group(0))
                
                origin = ai_info.get("origin")
                destination = ai_info.get("destination")
                date = ai_info.get("date")
                
                print(f"AI extracted: Origin={origin}, Destination={destination}, Date={date}")
                
                # Validate date if provided
                if date:
                    try:
                        datetime.strptime(date, "%Y-%m-%d")
                    except ValueError:
                        # Try to parse the date if it's not in YYYY-MM-DD format
                        try:
                            # Handle common date formats that might come from the AI
                            for fmt in ["%B %d, %Y", "%B %d %Y", "%d %B %Y", "%d-%m-%Y", "%m/%d/%Y"]:
                                try:
                                    parsed_date = datetime.strptime(date, fmt)
                                    date = parsed_date.strftime("%Y-%m-%d")
                                    break
                                except ValueError:
                                    continue
                        except Exception:
                            date = None
                
                # If we have all three pieces of information, return them
                if origin and destination and date:
                    return origin, destination, date
                
            except json.JSONDecodeError:
                print("Failed to parse AI response as JSON")
    except Exception as e:
        print(f"AI extraction error: {e}")
    
    # Fall back to pattern matching if AI extraction fails
    
    # Preprocess the message - convert to lowercase
    message = message.lower()
    
    # Create separate dictionaries to track potential matches with confidence scores
    destinations = {}
    origins = {}
    dates = {}
    
    # --- DESTINATION PATTERNS ---
    dest_patterns = [
        (r"(?:to|going to|go to|travel to|arrive (?:at|in)|heading to|destination)\s+([a-z]+(?:\s+[a-z]+)?)", 0.8),
        (r"(?:visit|visiting|see|seeing)\s+([a-z]+(?:\s+[a-z]+)?)", 0.7),
        (r"(?:want|planning)(?:\s+to)?\s+(?:go|visit|travel)(?:\s+to)?\s+([a-z]+(?:\s+[a-z]+)?)", 0.9)
    ]
    
    # --- ORIGIN PATTERNS ---
    origin_patterns = [
        (r"(?:from|departing from|leaving from|coming from)\s+([a-z]+(?:\s+[a-z]+)?)", 0.8),
        (r"(?:am|i am|i'm|we are|based in|located in|live in|staying in)\s+(?:from|in|at)?\s+([a-z]+(?:\s+[a-z]+)?)", 0.7),
        (r"(?:start|starting|depart|departing|flying)(?:\s+from)?\s+([a-z]+(?:\s+[a-z]+)?)", 0.9)
    ]
    
    # --- DATE PATTERNS ---
    month_names = "january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
    date_patterns = [
        (r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + month_names + r")", 0.8),  # "15th june", "15 of june"
        (r"(" + month_names + r")\s+(\d{1,2})(?:st|nd|rd|th)?", 0.8),  # "june 15", "june 15th"
        (r"on\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + month_names + r")", 0.9),  # "on the 15th of june"
        (r"on\s+(?:the\s+)?(" + month_names + r")\s+(\d{1,2})(?:st|nd|rd|th)?", 0.9),  # "on june 15th"
        (r"(\d{4}-\d{2}-\d{2})", 0.95),  # "2025-06-15"
        (r"(\d{1,2})[\/\.-](\d{1,2})[\/\.-](\d{2,4})", 0.8)  # "15/06/2025", "15.06.25", "15-06-2025"
    ]
    
    # Process destination patterns
    for pattern, confidence in dest_patterns:
        matches = re.finditer(pattern, message)
        for match in matches:
            potential_dest = match.group(1).strip()
            if len(potential_dest) > 2 and potential_dest not in ["to", "the", "a", "an", "from", "on", "in", "at"]:
                destinations[potential_dest] = max(confidence, destinations.get(potential_dest, 0))
    
    # Process origin patterns
    for pattern, confidence in origin_patterns:
        matches = re.finditer(pattern, message)
        for match in matches:
            potential_origin = match.group(1).strip()
            if len(potential_origin) > 2 and potential_origin not in ["to", "the", "a", "an", "from", "on", "in", "at"]:
                origins[potential_origin] = max(confidence, origins.get(potential_origin, 0))
    
    # Process date patterns
    for pattern, confidence in date_patterns:
        matches = re.finditer(pattern, message)
        for match in matches:
            if len(match.groups()) == 1:  # ISO format date
                dates[match.group(1)] = confidence
            elif "jan" in pattern or "february" in pattern:  # Month-Day or Day-Month patterns
                # Check if month is first or second in the pattern
                if re.search(r"\(" + month_names + r"\)", pattern.split(r"\s+")[0]):
                    # Month is first (e.g., "june 15")
                    month = match.group(1)
                    day = match.group(2)
                else:
                    # Day is first (e.g., "15 june")
                    day = match.group(1)
                    month = match.group(2)
                
                # Normalize month name
                month_mapping = {
                    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
                    "may": "may", "jun": "june", "jul": "july", "aug": "august", 
                    "sep": "september", "oct": "october", "nov": "november", "dec": "december"
                }
                full_month = month_mapping.get(month, month)
                
                # Parse the date
                try:
                    day = int(re.sub(r'(?:st|nd|rd|th)', '', day))
                    current_year = datetime.now().year
                    date_obj = datetime.strptime(f"{full_month} {day} {current_year}", "%B %d %Y")
                    formatted_date = date_obj.strftime("%Y-%m-%d")
                    dates[formatted_date] = confidence
                except (ValueError, TypeError):
                    pass
            else:  # MM/DD/YYYY or DD/MM/YYYY
                try:
                    # Try both formats
                    day = None
                    month = None
                    year = None
                    
                    if match.lastindex == 3:  # We have 3 parts
                        first, second, third = match.groups()
                        
                        # Determine which is which
                        if len(third) == 4:  # Full year
                            year = third
                            if int(first) <= 12:  # First is likely month
                                month, day = first, second
                            else:  # First is likely day
                                day, month = first, second
                        elif len(third) == 2:  # Shortened year
                            year = f"20{third}" if int(third) < 50 else f"19{third}"
                            if int(first) <= 12:  # First is likely month
                                month, day = first, second
                            else:  # First is likely day
                                day, month = first, second
                        
                        if day and month and year:
                            try:
                                date_obj = datetime.strptime(f"{year}-{int(month):02d}-{int(day):02d}", "%Y-%m-%d")
                                formatted_date = date_obj.strftime("%Y-%m-%d")
                                dates[formatted_date] = confidence
                            except (ValueError, TypeError):
                                # Try the other way around
                                try:
                                    date_obj = datetime.strptime(f"{year}-{int(day):02d}-{int(month):02d}", "%Y-%m-%d")
                                    formatted_date = date_obj.strftime("%Y-%m-%d")
                                    dates[formatted_date] = confidence
                                except (ValueError, TypeError):
                                    pass
                except (ValueError, TypeError):
                    pass
    
    # Find the most likely candidates based on confidence
    best_destination = max(destinations.items(), key=lambda x: x[1])[0] if destinations else None
    best_origin = max(origins.items(), key=lambda x: x[1])[0] if origins else None
    best_date = max(dates.items(), key=lambda x: x[1])[0] if dates else None
    
    print(f"Pattern extraction: Origin={best_origin}, Destination={best_destination}, Date={best_date}")
    
    # Special case: If origin and destination have the same value
    if best_origin and best_destination and best_origin == best_destination:
        # Try to determine which is which based on context
        if "from " + best_origin in message and "to " + best_destination not in message:
            # The word appears after "from" but not after "to", so it's likely the origin
            best_destination = None
        elif "to " + best_destination in message and "from " + best_origin not in message:
            # The word appears after "to" but not after "from", so it's likely the destination
            best_origin = None
        else:
            # Can't determine, prioritize destination and clear origin to avoid confusion
            best_origin = None
    
    # Handle special phrase "am from X"
    if not best_origin:
        am_from_match = re.search(r"(?:i'm|i am|am)\s+from\s+([a-z]+(?:\s+[a-z]+)?)", message)
        if am_from_match:
            potential_origin = am_from_match.group(1).strip()
            if potential_origin not in ["to", "the", "a", "an", "from", "on", "in", "at"]:
                best_origin = potential_origin
    
    # Capitalize names
    if best_origin:
        best_origin = best_origin.capitalize()
    if best_destination:
        best_destination = best_destination.capitalize()
    
    # Check if we have all necessary information
    if best_origin and best_destination and best_date:
        return best_origin, best_destination, best_date
    
    # If we still don't have all the information, return None
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
        
        # Extract flight details with the super intelligent extraction function
        origin, destination, departure_date = extract_flight_info(message)
        
        if origin and destination and departure_date:
            print(f"Final extraction: Origin={origin}, Destination={destination}, Date={departure_date}")
            
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
                    return {"response": f"No flights found from {origin} to {destination} on {departure_date}."}
            else:
                error_message = flight_response.text if hasattr(flight_response, 'text') else "Unknown error"
                return {"response": f"Sorry, I couldn't find flight information. Please try again with different dates or locations."}

        # If flight details aren't found, process general travel intent
        if is_general_travel_request(message):
            return {
                "response": (
                    "I'd be happy to help you plan your trip! To search for flights, please tell me:\n"
                    "- Where you're traveling from\n"
                    "- Where you want to go\n"
                    "- When you want to travel\n\n"
                    "For example, you could say something like \"I want to fly from Nairobi to Mombasa on June 15th\" or \"Looking for a trip to Mombasa from Nairobi next month.\""
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
