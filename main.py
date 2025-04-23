from fastapi import FastAPI, Query
import google.generativeai as genai
from langdetect import detect
import json
import os
import requests
from concurrent.futures import ThreadPoolExecutor
import re
import datetime
from dateutil import parser
import calendar

genai.configure(api_key="AIzaSyAcQ64mgrvtNfTR3ebbHcZxzWfRkWHyI-E")

app = FastAPI()

TIDIO_CHAT_URL = "https://www.tidio.com/panel/inbox/conversations/unassigned/"
CITY_LOOKUP_API = "https://tripzoori01-app.fly.dev/api/v1/base/cities/search?query="

WEBSITE_PAGES = [
    "https://dev.tripzoori.com/",
    "https://dev.tripzoori.com/faq-tripzoori"
]

def scrape_website(urls=WEBSITE_PAGES):
    combined_content = ""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for url in urls:
                page = browser.new_page()
                page.goto(url)
                page.wait_for_selector("body")
                combined_content += f"\nPage Content from {url}:\n{page.inner_text('body')}\n"
            browser.close()
        with open("website_data.json", "w", encoding="utf-8") as f:
            json.dump({"content": combined_content}, f, indent=4)
        return combined_content
    except Exception as e:
        print(f"Error during scraping: {e}")
        return ""

def load_data():
    try:
        if os.path.exists("website_data.json"):
            with open("website_data.json", "r", encoding="utf-8") as f:
                file_content = f.read().strip()
                if not file_content:
                    return ""
                try:
                    data = json.loads(file_content)
                    return data.get("content", "")
                except json.JSONDecodeError:
                    return ""
        else:
            return scrape_website()
    except Exception as e:
        print(f"Error in load_data: {e}")
        return ""

def send_message_to_tidio(message: str):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(TIDIO_CHAT_URL)
            page.wait_for_selector("textarea", timeout=10000)
            page.fill("textarea", message)
            page.keyboard.press("Enter")
            browser.close()
    except Exception as e:
        print(f"Error sending to Tidio: {e}")
        return False
    return True

def needs_human_agent(question: str, answer: str) -> bool:
    triggers = [
        "I can't", "I do not", "I am unable", "I don't have information",
        "I cannot", "I am just an AI", "I don't know", "I only provide information",
        "I'm not sure", "I apologize", "Unfortunately, I cannot"
    ]
    keywords = ["complaints", "refunds", "booking issue", "flight problem", "support", "human agent", "live agent"]
    return any(t in answer.lower() for t in triggers) or any(k in question.lower() for k in keywords)

def get_city_code(city_name: str) -> str:
    try:
        response = requests.get(CITY_LOOKUP_API + city_name)
        response.raise_for_status()
        cities = response.json()
        if cities and isinstance(cities, list):
            return cities[0]["code"]
        else:
            return ""
    except Exception as e:
        print(f"City code fetch failed for {city_name}: {e}")
        return ""

def get_flight_info(origin_city: str, destination_city: str, departure_date: str):
    try:
        origin_code = get_city_code(origin_city)
        destination_code = get_city_code(destination_city)

        if not origin_code or not destination_code:
            return f"Sorry, I couldn't find flight codes for one of the cities: {origin_city} or {destination_city}."

        url = f"https://tripzoori01-app.fly.dev/api/v1/flights/search?origin={origin_code}&destination={destination_code}&departure_date={departure_date}"
        response = requests.get(url)
        response.raise_for_status()
        flights = response.json().get("itineraries", [])

        if not flights:
            return "No flights were found for the specified route and date."

        sorted_flights = sorted(flights, key=lambda x: x["price"]["totalFare"])[:2]
        results = []
        for flight in sorted_flights:
            segments = flight["segments"]
            price = flight["price"]["totalFare"]
            currency = flight["price"]["currency"]

            journey_description = []
            for idx, seg in enumerate(segments):
                journey_description.append(
                    f"Segment {idx+1}:\n"
                    f"✈️ {seg['airlineName']} Flight {seg['flightNumber']} from "
                    f"{seg['departureCity']} ({seg['departureAirportCode']}) to {seg['arrivalCity']} ({seg['arrivalAirportCode']})\n"
                    f"🕑 Departure: {seg['departureTime']} → Arrival: {seg['arrivalTime']}\n"
                    f"💺 Class: {seg['cabinClass']}\n"
                )
            journey_str = "\n".join(journey_description)
            results.append(f"{journey_str}\n💵 Total Price: {price} {currency}\n{'='*50}")

        return "\n\n".join(results)
    except Exception as e:
        return f"Error retrieving flight data: {str(e)}"

def parse_human_readable_date(date_str: str) -> str:
    """Convert various date formats to YYYY-MM-DD"""
    try:
        # Current date for reference
        today = datetime.datetime.now()
        current_year = today.year
        
        # Handle relative dates
        if re.search(r'\b(today|tonight)\b', date_str, re.IGNORECASE):
            return today.strftime('%Y-%m-%d')
        elif re.search(r'\b(tomorrow|tmrw|tmr)\b', date_str, re.IGNORECASE):
            return (today + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        elif re.search(r'\bnext week\b', date_str, re.IGNORECASE):
            return (today + datetime.timedelta(days=7)).strftime('%Y-%m-%d')
        elif re.search(r'\bnext month\b', date_str, re.IGNORECASE):
            if today.month == 12:
                next_month = datetime.datetime(today.year + 1, 1, min(today.day, 31))
            else:
                next_month = datetime.datetime(today.year, today.month + 1, min(today.day, calendar.monthrange(today.year, today.month + 1)[1]))
            return next_month.strftime('%Y-%m-%d')
        
        # Use regex to catch formats like "22nd of May" or "22nd May" without explicit year
        day_month_pattern = re.search(r'(\d{1,2})(st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*', date_str.lower())
        if day_month_pattern:
            day = int(day_month_pattern.group(1))
            month_str = day_month_pattern.group(3)
            month_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 
                         'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
            month = month_map[month_str[:3].lower()]
            
            # If date is in the past for current year, use next year
            date_with_year = datetime.datetime(current_year, month, day)
            if date_with_year < today:
                date_with_year = datetime.datetime(current_year + 1, month, day)
                
            return date_with_year.strftime('%Y-%m-%d')
            
        # Try dateutil parser as a backup
        try:
            parsed_date = parser.parse(date_str, fuzzy=True)
            # Handle missing year by adding current year
            if parsed_date.year == 1900:  # dateutil's default when year is missing
                if parsed_date.replace(year=current_year) < today:
                    parsed_date = parsed_date.replace(year=current_year + 1)
                else:
                    parsed_date = parsed_date.replace(year=current_year)
            return parsed_date.strftime('%Y-%m-%d')
        except:
            pass
            
        return ""
    except Exception as e:
        print(f"Error parsing date '{date_str}': {e}")
        return ""

def extract_travel_info(question: str):
    """
    Extract origin, destination and date from natural language query
    """
    origin = None
    destination = None
    date_str = None
    
    # Clean up the query - replace specific words that might confuse the parsing
    cleaned_question = question.lower()
    cleaned_question = re.sub(r'\bheading\b', 'to', cleaned_question)
    cleaned_question = re.sub(r'\btraveling\b', 'travel', cleaned_question)
    
    # Extract date first to avoid it being misidentified as a location
    date_patterns = [
        r'on\s+([a-zA-Z0-9\s,\.\/\-]+(?:of\s+[a-zA-Z]+)?(?:\s+\d{4})?)',
        r'for\s+([a-zA-Z0-9\s,\.\/\-]+(?:of\s+[a-zA-Z]+)?(?:\s+\d{4})?)',
        r'date[:]?\s+([a-zA-Z0-9\s,\.\/\-]+(?:of\s+[a-zA-Z]+)?(?:\s+\d{4})?)',
        r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[a-zA-Z]+(?:\s+\d{4})?)',
        r'([a-zA-Z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, cleaned_question)
        if match:
            date_candidates = match.group(1).strip().rstrip('.,:;')
            # Don't include question fragments in the date
            if 'are there' not in date_candidates and 'is there' not in date_candidates:
                date_str = date_candidates
                # Remove the date part from the question to avoid confusion in city extraction
                cleaned_question = cleaned_question.replace(match.group(0), ' ')
                break
    
    # Common patterns for origin/destination
    city_patterns = [
        # from X to Y
        r'from\s+([a-zA-Z\s]+?)\s+to\s+([a-zA-Z\s]+?)(?:\s+on|\s+for|\s+at|\s+in|\s+\?|$|\.)',
        # departing X going to Y
        r'(?:departing|leaving)\s+(?:from\s+)?([a-zA-Z\s]+?)\s+(?:to|going to|heading to|for)\s+([a-zA-Z\s]+?)(?:\s+on|\s+for|\s+at|\s+in|\s+\?|$|\.)',
        # X to Y (where X is likely origin)
        r'(?:^|\s)([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\s+to\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)(?:\s+on|\s+for|\s+at|\s+in|\s+\?|$|\.)',
    ]
    
    for pattern in city_patterns:
        match = re.search(pattern, cleaned_question)
        if match:
            origin = match.group(1).strip().rstrip('.,:;')
            destination = match.group(2).strip().rstrip('.,:;')
            break
    
    # If we still don't have cities, try looser individual city detection
    if not origin or not destination:
        from_pattern = r'(?:from|departing|departing from|leaving|leaving from)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)'
        to_pattern = r'(?:to|going to|heading to|destination|arriving at|arrive at|arrival)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)'
        
        from_match = re.search(from_pattern, cleaned_question)
        to_match = re.search(to_pattern, cleaned_question)
        
        if from_match:
            origin = from_match.group(1).strip().rstrip('.,:;')
        if to_match:
            destination = to_match.group(1).strip().rstrip('.,:;')
    
    # Format the date if found
    formatted_date = None
    if date_str:
        formatted_date = parse_human_readable_date(date_str)
    
    return {
        "origin": origin,
        "destination": destination,
        "date": formatted_date,
        "date_str": date_str
    }

def is_flight_query(question: str) -> bool:
    keywords = ["flight", "book", "booking", "book a flight", "find flight", "cheap flights", "airfare", 
                "travel", "trip", "tickets", "fly", "flying", "journey", "departure", "departing"]
    return any(k in question.lower() for k in keywords)

def is_partial_booking_info(info):
    """Check if we have partial booking information"""
    return any([info["origin"], info["destination"], info["date_str"]]) and not all([info["origin"], info["destination"], info["date"]])

def ask_question(question: str):
    data = load_data()
    try:
        detected_language = detect(question)
    except:
        detected_language = "en"
    lang_instruction = f"Respond ONLY in {detected_language}." if detected_language != "en" else "Respond in English."

    # Debug info - print what was extracted
    print(f"Processing question: {question}")
    travel_info = extract_travel_info(question)
    print(f"Extracted info: {travel_info}")

    # Check if this is a flight query
    if is_flight_query(question):
        # Try to extract travel information        
        # If we have complete information, proceed with the flight search
        if travel_info["origin"] and travel_info["destination"] and travel_info["date"]:
            return {"question": question, "answer": get_flight_info(travel_info["origin"], travel_info["destination"], travel_info["date"])}
        
        # If we have partial information, ask for the missing details
        elif is_partial_booking_info(travel_info):
            missing_info_prompt = "I'd be happy to help you find flights. "
            
            if not travel_info["origin"]:
                missing_info_prompt += "Which city will you be departing from? "
            
            if not travel_info["destination"]:
                missing_info_prompt += "Where would you like to go to? "
            
            if not travel_info["date"]:
                if travel_info["date_str"]:
                    missing_info_prompt += f"I couldn't understand the date '{travel_info['date_str']}'. Could you please provide the date in a format like 'May 22, 2025' or 'next Friday'? "
                else:
                    missing_info_prompt += "When would you like to travel? "
            
            # Include the information we already have for confirmation
            if travel_info["origin"] or travel_info["destination"] or travel_info["date"]:
                missing_info_prompt += "\n\nHere's what I understood so far: "
                if travel_info["origin"]:
                    missing_info_prompt += f"\n- Departing from: {travel_info['origin']}"
                if travel_info["destination"]:
                    missing_info_prompt += f"\n- Going to: {travel_info['destination']}"
                if travel_info["date"]:
                    missing_info_prompt += f"\n- Date: {travel_info['date']}"
            
            return {"response": missing_info_prompt}
        
        # Generic booking intent detected but no specific details
        else:
            return {
                "response": "I'd be happy to help you find flights! Could you please provide the following details?\n\n1. Where will you be departing from?\n2. Where would you like to go?\n3. When do you plan to travel? (You can say things like 'May 22nd', 'next Friday', or '06/15/2025')"
            }

    # Handle conversation state - if they're responding to our questions about booking
    state_keywords = {
        "departure": ["from", "leaving", "departing", "departure city", "starting from"],
        "destination": ["to", "going to", "destination", "arriving at", "want to visit"],
        "date": ["on", "date", "when", "departing on", "leaving on", "travel on"]
    }
    
    for state, keywords in state_keywords.items():
        if any(k in question.lower() for k in keywords) and len(question.split()) < 5:
            # This looks like an answer to our previous question
            if state == "departure":
                return {"response": f"Great! You're departing from {question.strip()}. Where would you like to go?"}
            elif state == "destination":
                return {"response": f"Perfect! When would you like to travel to {question.strip()}? (You can say dates like 'next Friday', '22nd May', etc.)"}
            elif state == "date":
                date = parse_human_readable_date(question)
                if date:
                    return {"response": f"Thanks! I've noted your travel date as {date}. To complete your flight search, could you please tell me your departure city and destination?"}
                else:
                    return {"response": "I'm having trouble understanding that date format. Could you please provide it in a format like 'May 22, 2025' or 'next Friday'?"}
    
    prompt = f"""
You are a helpful AI assistant that answers questions based ONLY on the content of the website below.

{lang_instruction}

Website Content:
{data}

User's Question: {question}

Answer:
"""
    model = genai.GenerativeModel("gemini-1.5-pro")
    response = model.generate_content(prompt)
    answer = response.text.strip()

    if needs_human_agent(question, answer):
        send_message_to_tidio(f"User asked: '{question}'\nBot could not answer.")
        return {
            "message": "I am unable to answer this question right now, but don't worry, we are connecting you to a live agent.",
            "status": "transferred_to_human"
        }

    return {"question": question, "answer": answer}

@app.get("/ask")
async def get_answer(question: str = Query(..., title="Question", description="Ask a question about the website or flights")):
    if any(keyword in question.lower() for keyword in ["transfer to human agent", "talk to a person", "speak to support"]):
        message_sent = send_message_to_tidio(f"User requested a human agent for: '{question}'")
        return {
            "message": "Please hold on, we're connecting you to a live agent.",
            "status": "transferred_to_human" if message_sent else "error"
        }

    with ThreadPoolExecutor() as executor:
        result = executor.submit(ask_question, question).result()
    return result
