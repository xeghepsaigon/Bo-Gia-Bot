import telebot
from telebot import types
import google.generativeai as genai
import PIL.Image
import io
import time
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json
import random
from flask import Flask, request
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CẤU HÌNH từ ENV ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
HERE_API_KEY = os.getenv('HERE_API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))

# --- CACHE & CONFIG ---
FLIGHT_CACHE = {
    'data': [],
    'timestamp': 0,
    'cache_duration': 300  # 5 phút
}

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def get_random_header():
    """Random User-Agent để tránh chặn"""
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://www.flightradar24.com/',
        'Origin': 'https://www.flightradar24.com',
        'DNT': '1',
        'Connection': 'keep-alive',
    }

# --- CẤU HÌNH ---
GEMINI_API_KEY = "AIzaSyDzmchOj4bYWbIQEABTSd0pRcn35USr-pE"
TELEGRAM_TOKEN = "7936894568:AAE09DbRmAQNIlqBvBKZGTu8U-Z37O3AfZk"
HERE_API_KEY = "1mFHwRVlN-EI6cwBscAq0rkVJ_uoOVm6J1DyVSwUc0E"

# 1. Kết nối Google AI
genai.configure(api_key=GEMINI_API_KEY)

# 2. HÀM CHỌN MODEL TỰ ĐỘNG (Sửa lỗi 404)
def select_working_model():
    print("🔍 Đang quét danh sách model khả dụng...")
    try:
        # Lấy danh sách các model mà Key này được phép dùng
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        print(f"📋 Danh sách model bạn có quyền dùng: {available_models}")
        
        # Thứ tự ưu tiên (phòng trường hợp lỗi tên model)
        priorities = [
            'models/gemini-1.5-flash-latest', 
            'models/gemini-1.5-flash', 
            'models/gemini-pro-vision'
        ]
        
        for p in priorities:
            if p in available_models:
                print(f"✅ Đã chọn model: {p}")
                return p
        return available_models[0] # Chọn model đầu tiên nếu không khớp ưu tiên
    except Exception as e:
        print(f"❌ Không thể lấy danh sách model: {e}")
        return 'models/gemini-1.5-flash' # Mặc định nếu lỗi

SELECTED_MODEL_NAME = select_working_model()
model = genai.GenerativeModel(
    model_name=SELECTED_MODEL_NAME,
    system_instruction="Chỉ trả về định dạng: 'Origin: [địa chỉ] | Destination: [địa chỉ]'"
)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- HANDLER CẤU LỆNH ---
@bot.message_handler(commands=['start', 'sanbay'])
def handle_start(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_airport = types.KeyboardButton("✈️ Sân Bay")
    btn_photo = types.KeyboardButton("📸 Gửi Ảnh")
    markup.add(btn_airport, btn_photo)
    
    bot.send_message(message.chat.id, "🚗 Chào bạn! Chọn tùy chọn hoặc gửi ảnh để check kẹt xe thực tế!", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "✈️ Sân Bay")
def handle_airport(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    airports = [
        types.KeyboardButton("🛫 Tân Sơn Nhất (SGN)"),
        types.KeyboardButton("🛬 Nội Bài (HAN)"),
        types.KeyboardButton("✈️ Đà Nẵng (DAD)"),
        types.KeyboardButton("🔙 Quay Lại")
    ]
    markup.add(*airports)
    bot.send_message(message.chat.id, "Chọn sân bay:", reply_markup=markup)

# --- HÀM LẤY DANH SÁCH CHUYẾN BAY ---
def scrape_flightradar24(airport_code):
    """Scrape từ FlightRadar24 API (ưu tiên)"""
    try:
        print(f"🔍 Đang lấy từ FlightRadar24 API ({airport_code})...")
        url = "https://api.flightradar24.com/common/v1/airport.json"
        params = {
            'code': airport_code,
            'plugin[]': 'schedule'
        }
        
        response = requests.get(url, headers=get_random_header(), params=params, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ FlightRadar24 status {response.status_code}")
            return None
        
        data = response.json()
        flights_data = data.get('result', {}).get('response', {}).get('airport', {}).get('pluginData', {}).get('schedule', {}).get('arrivals', {}).get('data', [])
        
        if not flights_data:
            print(f"⚠️ Không có chuyến bay từ FlightRadar24 ({airport_code})")
            return None
        
        flights = []
        for item in flights_data[:8]:
            try:
                flight = item.get('flight', {})
                
                # Lấy thời gian
                arrival_timestamp = flight.get('time', {}).get('estimated', {}).get('arrival') or flight.get('time', {}).get('scheduled', {}).get('arrival')
                if arrival_timestamp:
                    arrival_time = datetime.fromtimestamp(arrival_timestamp).strftime("%H:%M")
                else:
                    arrival_time = "N/A"
                
                origin_country = flight.get('airport', {}).get('origin', {}).get('position', {}).get('country', {}).get('name', '')
                is_domestic = origin_country == 'Vietnam'
                
                # Determine terminal based on airport
                if airport_code == 'SGN':
                    terminal = 'T1 (Quốc Nội)' if is_domestic else 'T2/T3 (Quốc Tế)'
                else:
                    terminal = 'T1' if is_domestic else 'T2'
                
                flight_data = {
                    "flight": flight.get('identification', {}).get('number', {}).get('default', 'N/A'),
                    "from": flight.get('airport', {}).get('origin', {}).get('name', 'N/A'),
                    "time": arrival_time,
                    "status": flight.get('status', {}).get('text', 'Chưa xác định'),
                    "terminal": terminal
                }
                flights.append(flight_data)
                
            except Exception as e:
                print(f"❌ Parse error: {e}")
                continue
        
        return flights if flights else None
        
    except Exception as e:
        print(f"❌ FlightRadar24 error: {e}")
        return None

def scrape_flightaware(airport_code):
    """Scrape từ FlightAware"""
    try:
        print(f"🔍 Đang lấy từ FlightAware ({airport_code})...")
        url = f"https://www.flightaware.com/live/airport/{airport_code}/arrivals"
        
        response = requests.get(url, headers=get_random_header(), timeout=10)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            print(f"❌ FlightAware status {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        flights = []
        
        table_rows = soup.find_all('tr', class_=['row oddrow', 'row evenrow'])
        
        if not table_rows:
            table_rows = soup.select('table tbody tr')
        
        if not table_rows:
            print(f"⚠️ Không tìm thấy chuyến bay trên FlightAware ({airport_code})")
            return None
        
        for row in table_rows[:8]:
            try:
                tds = row.find_all('td')
                if len(tds) < 3:
                    continue
                
                flight_number = tds[0].text.strip()
                if not flight_number:
                    continue
                
                flight_data = {
                    "flight": flight_number,
                    "from": tds[2].text.strip() if len(tds) > 2 else "N/A",
                    "time": tds[3].text.strip() if len(tds) > 3 else "N/A",
                    "status": tds[4].text.strip() if len(tds) > 4 else "N/A",
                    "terminal": "T2"
                }
                flights.append(flight_data)
                
            except Exception as e:
                print(f"❌ Parse error: {e}")
                continue
        
        return flights if flights else None
        
    except Exception as e:
        print(f"❌ FlightAware error: {e}")
        return None

def load_flights_from_json(airport_code):
    """Tải từ file JSON"""
    try:
        with open('flights_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            flights = data.get('arrivals', [])
            print(f"✅ Lấy {len(flights)} chuyến bay từ file JSON")
            return flights
    except Exception as e:
        print(f"❌ Lỗi đọc file: {e}")
        return []

def get_arriving_flights(airport_code='SGN'):
    """Lấy chuyến bay từ real sources (ưu tiên FlightRadar24)"""
    
    # Check cache
    cache_key = f"flights_{airport_code}"
    now = time.time()
    if cache_key in FLIGHT_CACHE and FLIGHT_CACHE[cache_key]['data'] and (now - FLIGHT_CACHE[cache_key]['timestamp']) < FLIGHT_CACHE[cache_key]['cache_duration']:
        print(f"📦 Dùng dữ liệu cache ({airport_code}, 5 phút)")
        return FLIGHT_CACHE[cache_key]['data']
    
    # Try FlightRadar24 (ưu tiên)
    flights = scrape_flightradar24(airport_code)
    if flights:
        if cache_key not in FLIGHT_CACHE:
            FLIGHT_CACHE[cache_key] = {'data': [], 'timestamp': 0, 'cache_duration': 300}
        FLIGHT_CACHE[cache_key]['data'] = flights
        FLIGHT_CACHE[cache_key]['timestamp'] = now
        print(f"✅ Lấy được {len(flights)} chuyến bay từ FlightRadar24")
        return flights
    
    # Try FlightAware
    flights = scrape_flightaware(airport_code)
    if flights:
        if cache_key not in FLIGHT_CACHE:
            FLIGHT_CACHE[cache_key] = {'data': [], 'timestamp': 0, 'cache_duration': 300}
        FLIGHT_CACHE[cache_key]['data'] = flights
        FLIGHT_CACHE[cache_key]['timestamp'] = now
        print(f"✅ Lấy được {len(flights)} chuyến bay từ FlightAware")
        return flights
    
    # Fallback JSON
    print(f"⚠️ Không lấy được từ real sources, dùng file JSON")
    return load_flights_from_json(airport_code)

def load_flights_from_json():
    """Tải dữ liệu chuyến bay từ file JSON"""
    try:
        with open('flights_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            flights = data.get('arrivals', [])
            print(f"✅ Lấy {len(flights)} chuyến bay từ file JSON")
            return flights
    except Exception as e:
        print(f"❌ Lỗi đọc file: {e}")
        return []

@bot.callback_query_handler(func=lambda call: call.data.startswith(('sgn_t1', 'sgn_t2', 'sgn_t3', 'han_', 'dad_')))
def handle_terminal_selection_generic(call):
    bot.answer_callback_query(call.id)
    
    # Parse airport code and terminal
    if call.data.startswith('sgn_'):
        airport_code = 'SGN'
        terminal_type = call.data.split('_')[1]  # 't1', 't2', 't3'
        
        # Map SGN terminals
        terminal_map = {
            't1': 'Quốc Nội T1',
            't2': 'Quốc Tế T2',
            't3': 'Quốc Nội T3'
        }
        terminal_display = terminal_map.get(terminal_type, terminal_type)
        airport_name = 'Tân Sơn Nhất'
    else:
        # For HAN and DAD
        parts = call.data.split('_')
        airport_code = parts[0].upper()
        is_domestic = parts[1] == 'domestic'
        
        airport_names = {
            'HAN': 'Nội Bài',
            'DAD': 'Đà Nẵng'
        }
        
        terminal_type = "Quốc Nội (T1)" if is_domestic else "Quốc Tế"
        airport_name = airport_names.get(airport_code, airport_code)
        terminal_display = terminal_type
    
    flights = get_arriving_flights(airport_code)
    
    # Filter flights by terminal
    filtered_flights = []
    for f in flights:
        terminal = f.get('terminal', '')
        
        if call.data.startswith('sgn_'):
            # SGN-specific filtering
            if terminal_type == 't1' and 'T1' in terminal:
                filtered_flights.append(f)
            elif terminal_type == 't2' and 'T2' in terminal:
                filtered_flights.append(f)
            elif terminal_type == 't3' and 'T3' in terminal:
                filtered_flights.append(f)
        else:
            # Generic filtering for other airports
            is_domestic = parts[1] == 'domestic'
            if is_domestic and 'T1' in terminal:
                filtered_flights.append(f)
            elif not is_domestic and ('T1' not in terminal or 'T2' in terminal):
                filtered_flights.append(f)
    
    if not filtered_flights:
        filtered_flights = flights[:8]  # Hiển thị tất cả nếu không có filter
    
    # Hiển thị thông tin chuyến bay chi tiết
    flight_details = ""
    for idx, flight in enumerate(filtered_flights[:8], 1):
        flight_details += f"\n🛬 {idx} - {flight.get('flight', 'N/A')}\n"
        flight_details += f"🔹 {flight.get('from', 'N/A')}\n"
        flight_details += f"🔹 Terminal: {flight.get('terminal', terminal_display)}\n"
        flight_details += f"👉 Hạ cánh: {flight.get('time', 'N/A')}\n"
        flight_details += f"⛔️ Dự kiến: {flight.get('time', 'N/A')}\n"
    
    msg = f"""✈️ Danh sách chuyến bay hạ cánh - {airport_name} ({terminal_display}):
{flight_details}

📸 Gửi ảnh chứa:
- Origin: địa chỉ khác
- Destination: Chuyến bay nào đó - {airport_name} ({terminal_display})
"""
    
    bot.send_message(call.message.chat.id, msg)

@bot.message_handler(func=lambda message: "Tân Sơn Nhất" in message.text)
def handle_tansonnhat(message):
    markup = types.InlineKeyboardMarkup()
    btn_t1 = types.InlineKeyboardButton("🇻🇳 Quốc Nội T1", callback_data="sgn_t1")
    btn_t2 = types.InlineKeyboardButton("🌍 Quốc Tế T2", callback_data="sgn_t2")
    btn_t3 = types.InlineKeyboardButton("🇻🇳 Quốc Nội T3", callback_data="sgn_t3")
    btn_back = types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back_airport_menu")
    
    markup.add(btn_t1)
    markup.add(btn_t2)
    markup.add(btn_t3)
    markup.add(btn_back)
    
    bot.send_message(message.chat.id, "🛬 Chọn nhà ga hạ cánh:", reply_markup=markup)

@bot.message_handler(func=lambda message: "Nội Bài" in message.text)
def handle_noi_bai(message):
    markup = types.InlineKeyboardMarkup()
    btn_domestic = types.InlineKeyboardButton("🇻🇳 Quốc Nội (T1)", callback_data="han_domestic")
    btn_intl = types.InlineKeyboardButton("🌍 Quốc Tế (T2)", callback_data="han_intl")
    btn_back = types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back_airport_menu")
    
    markup.add(btn_domestic)
    markup.add(btn_intl)
    markup.add(btn_back)
    
    bot.send_message(message.chat.id, "🛬 Chọn ga hạ cánh:", reply_markup=markup)

@bot.message_handler(func=lambda message: "Đà Nẵng" in message.text)
def handle_da_nang(message):
    markup = types.InlineKeyboardMarkup()
    btn_domestic = types.InlineKeyboardButton("🇻🇳 Quốc Nội (T1)", callback_data="dad_domestic")
    btn_intl = types.InlineKeyboardButton("🌍 Quốc Tế (T2)", callback_data="dad_intl")
    btn_back = types.InlineKeyboardButton("🔙 Quay Lại", callback_data="back_airport_menu")
    
    markup.add(btn_domestic)
    markup.add(btn_intl)
    markup.add(btn_back)
    
    bot.send_message(message.chat.id, "🛬 Chọn ga hạ cánh:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["terminal_domestic", "terminal_intl"])
def handle_terminal_selection(call):
    bot.answer_callback_query(call.id)
    
    is_domestic = call.data == "terminal_domestic"
    terminal_type = "Quốc Nội (T1)" if is_domestic else "Quốc Tế (T2/T3)"
    
    flights = get_arriving_flights('SGN')
    
    # Filter flights by terminal type
    filtered_flights = []
    for f in flights:
        terminal = f.get('terminal', '')
        if is_domestic and 'T1' in terminal:
            filtered_flights.append(f)
        elif not is_domestic and ('T2' in terminal or 'T3' in terminal):
            filtered_flights.append(f)
    
    if not filtered_flights:
        filtered_flights = flights  # Hiển thị tất cả nếu không có filter
    
    # Hiển thị thông tin chuyến bay chi tiết
    flight_details = ""
    for idx, flight in enumerate(filtered_flights[:8], 1):
        flight_details += f"\n🛬 {idx} - {flight.get('flight', 'N/A')}\n"
        flight_details += f"🔹 {flight.get('from', 'N/A')}\n"
        flight_details += f"🔹 Terminal: {flight.get('terminal', terminal_type)}\n"
        flight_details += f"👉 Hạ cánh: {flight.get('time', 'N/A')}\n"
        flight_details += f"⛔️ Dự kiến: {flight.get('time', 'N/A')}\n"
    
    msg = f"""✈️ Danh sách chuyến bay hạ cánh - {terminal_type}:
{flight_details}

📸 Gửi ảnh chứa:
- Origin: địa chỉ khác
- Destination: Chuyến bay nào đó - Tân Sơn Nhất ({terminal_type})
"""
    
    bot.send_message(call.message.chat.id, msg)

@bot.callback_query_handler(func=lambda call: call.data.startswith("flight_"))
def handle_flight_selection(call):
    bot.answer_callback_query(call.id)
    
    # Parse flight info từ callback_data
    data_parts = call.data.replace("flight_", "").rsplit("_", 1)
    flight_code = data_parts[0]
    terminal_info = data_parts[1].replace("_", " ") if len(data_parts) > 1 else "T2/T3"
    
    # Tìm flight đầy đủ
    flights = get_arriving_flights()
    flight_info = None
    for f in flights:
        if flight_code in f.get('flight', ''):
            flight_info = f
            break
    
    if not flight_info:
        flight_info = {'flight': flight_code, 'from': 'N/A', 'time': 'N/A', 'terminal': terminal_info}
    
    # Format thông tin chi tiết
    detail_msg = f"""
🛬 {flight_code}

🔹 {flight_info.get('from', 'N/A')}
🔹 Terminal: {flight_info.get('terminal', terminal_info)}

👉 Hạ cánh: {flight_info.get('time', 'N/A')}
⛔️ Dự kiến: {flight_info.get('time', 'N/A')}

📸 Bây giờ gửi ảnh chứa:
- Origin: địa chỉ khác
- Destination: {flight_code} - Tân Sơn Nhất ({terminal_info})
"""
    
    bot.send_message(call.message.chat.id, detail_msg)

@bot.callback_query_handler(func=lambda call: call.data.startswith("flight_"))
def handle_flight_selection(call):
    bot.answer_callback_query(call.id)
    
    # Parse flight info từ callback_data
    data_parts = call.data.replace("flight_", "").rsplit("_", 1)
    flight_code = data_parts[0]
    terminal_info = data_parts[1].replace("_", " ") if len(data_parts) > 1 else "T2/T3"
    
    # Tìm flight đầy đủ
    flights = get_arriving_flights()
    flight_info = None
    for f in flights:
        if flight_code in f.get('flight', ''):
            flight_info = f
            break
    
    if not flight_info:
        flight_info = {'flight': flight_code, 'from': 'N/A', 'time': 'N/A', 'terminal': terminal_info}
    
    # Format thông tin chi tiết
    detail_msg = f"""
🛬 {flight_code}

🔹 {flight_info.get('from', 'N/A')}
🔹 Terminal: {flight_info.get('terminal', terminal_info)}

👉 Hạ cánh: {flight_info.get('time', 'N/A')}
⛔️ Dự kiến: {flight_info.get('time', 'N/A')}

📸 Bây giờ gửi ảnh chứa:
- Origin: địa chỉ khác
- Destination: {flight_code} - Tân Sơn Nhất ({terminal_info})
"""
    
    bot.send_message(call.message.chat.id, detail_msg)

@bot.message_handler(func=lambda message: message.text == "🔙 Quay Lại")
def handle_back(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_airport = types.KeyboardButton("✈️ Sân Bay")
    btn_photo = types.KeyboardButton("📸 Gửi Ảnh")
    markup.add(btn_airport, btn_photo)
    
    bot.send_message(message.chat.id, "🚗 Chọn tùy chọn:", reply_markup=markup)

# --- HÀM TÍNH THỜI GIAN THỰC (HERE MAPS) ---
def get_realtime_traffic(origin_addr, dest_addr):
    try:
        geo_url = "https://geocode.search.hereapi.com/v1/geocode"
        start_res = requests.get(geo_url, params={'q': origin_addr, 'apiKey': HERE_API_KEY}).json()
        end_res = requests.get(geo_url, params={'q': dest_addr, 'apiKey': HERE_API_KEY}).json()
        
        print(f"DEBUG START: {start_res}")
        print(f"DEBUG END: {end_res}")
        
        if not start_res.get('items') or not end_res.get('items'):
            print(f"❌ HERE không tìm thấy: Origin items={bool(start_res.get('items'))}, Dest items={bool(end_res.get('items'))}")
            return None
            
        start_pos = start_res['items'][0]['position']
        end_pos = end_res['items'][0]['position']
        
        route_url = "https://router.hereapi.com/v8/routes"
        params = {
            'transportMode': 'car',
            'origin': f"{start_pos['lat']},{start_pos['lng']}",
            'destination': f"{end_pos['lat']},{end_pos['lng']}",
            'return': 'summary',
            'departureTime': datetime.utcnow().isoformat() + 'Z',
            'apiKey': HERE_API_KEY
        }
        res = requests.get(route_url, params=params).json()
        print(f"DEBUG ROUTE RESPONSE: {res}")
        
        if 'routes' not in res:
            print(f"❌ HERE Routes API lỗi: {res}")
            return None
            
        summary = res['routes'][0]['sections'][0]['summary']
        
        minutes = round(summary['duration'] / 60)
        distance = summary['length'] / 1000
        return f"{minutes} phút / {distance:.1f} km"
    except Exception as e:
        print(f"❌ LỖI HERE MAPS: {e}")
        return None

# --- XỬ LÝ PHOTO ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        status_msg = bot.reply_to(message, "⏳ AI đang đọc địa chỉ...")
        
        file_info = bot.get_file(message.photo[-1].file_id)
        img_data = bot.download_file(file_info.file_path)
        img = PIL.Image.open(io.BytesIO(img_data))
        
        # Gọi Gemini
        response = model.generate_content(["Trích xuất Origin và Destination trong ảnh này", img])
        ai_text = response.text.strip()
        print(f"DEBUG AI: {ai_text}")

        if "|" in ai_text:
            parts = ai_text.split("|")
            origin = parts[0].replace("Origin:", "").strip()
            dest = parts[1].replace("Destination:", "").strip()
            
            bot.edit_message_text(f"📍 Lộ trình:\nTừ: {origin}\nĐến: {dest}\n\n⏳ Đang check kẹt xe thực tế...", 
                                  chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            
            result = get_realtime_traffic(origin, dest)
            if result:
                bot.edit_message_text(f"🏁 **Kết quả thực tế:**\n🚗 {result}", 
                                      chat_id=status_msg.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
            else:
                bot.edit_message_text("⚠️ HERE Maps không tìm thấy tọa độ.", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        else:
            bot.edit_message_text(f"⚠️ AI chưa tách được địa chỉ. Nội dung đọc được:\n{ai_text}", chat_id=status_msg.chat.id, message_id=status_msg.message_id)

    except Exception as e:
        print(f"LỖI: {e}")
        bot.send_message(message.chat.id, f"⚠️ Lỗi hệ thống: {str(e)[:50]}")

if __name__ == "__main__":
    # --- SETUP WEBHOOK ---
    app = Flask(__name__)
    
    @app.route('/webhook', methods=['POST'])
    def webhook():
        """Webhook endpoint để nhận updates từ Telegram"""
        json_data = request.get_json()
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return "ok", 200
    
    @app.route('/', methods=['GET'])
    def health():
        """Health check endpoint"""
        return "Bot is running", 200
    
    try:
        # Set webhook
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"🚀 BOT WEBHOOK SETUP! URL: {WEBHOOK_URL}")
        print(f"📡 Model: {SELECTED_MODEL_NAME}")
        print(f"🔌 Flask running on port {FLASK_PORT}")
        
        # Chạy Flask server
        app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
        
    except Exception as e:
        print(f"❌ Webhook setup lỗi: {e}")
        print("⚠️ Fallback về polling...")
        bot.remove_webhook()
        print(f"🚀 BOT POLLING MODE! Model: {SELECTED_MODEL_NAME}")
        bot.infinity_polling()