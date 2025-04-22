from fastapi import FastAPI, Query
import google.generativeai as genai
from langdetect import detect
import json
import os
import requests
from concurrent.futures import ThreadPoolExecutor

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
            return f"Sorry, I couldn’t find flight codes for one of the cities: {origin_city} or {destination_city}."

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

def is_flight_query(question: str) -> bool:
    keywords = ["flight", "book a flight", "find flight", "cheap flights", "airfare"]
    return any(k in question.lower() for k in keywords)

def ask_question(question: str):
    data = load_data()
    try:
        detected_language = detect(question)
    except:
        detected_language = "en"
    lang_instruction = f"Respond ONLY in {detected_language}." if detected_language != "en" else "Respond in English."

    import re
    flight_pattern = re.search(r"from\s+([a-zA-Z\s]+)\s+to\s+([a-zA-Z\s]+)\s+on\s+(\d{4}-\d{2}-\d{2})", question.lower())
    if is_flight_query(question) and flight_pattern:
        origin = flight_pattern.group(1).strip()
        destination = flight_pattern.group(2).strip()
        date = flight_pattern.group(3).strip()
        return {"question": question, "answer": get_flight_info(origin, destination, date)}

    intent_pattern = re.search(r"(book|booking|flight)\s+(to|for)\s+([a-zA-Z\s]+)", question.lower())
    if intent_pattern:
        return {
            "response": "Great! I can help you with that. Could you please tell me:\n1. Which city are you departing from?\n2. Which city do you want to travel to?\n3. What is your departure date (format: YYYY-MM-DD)?"
        }

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
