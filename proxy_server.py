import http.server
import json
import ssl
import xml.etree.ElementTree as ET
from http import HTTPStatus
import re
import os
import requests # Use requests for more robust HTTP calls

# --- Configuration ---
# Render provides the PORT environment variable. Fallback to 8080 for local testing.
PORT = int(os.environ.get('PORT', 8080))
EXTERNAL_API_URL = 'https://my.internetticketing.com/taposadmin/parhig/pos_feed/?type=MEDIA2'
API_PATH = '/api/movies'

def extract_youtube_id(url):
    if not url or url.lower() == 'none':
        return None
    match = re.search(r'(?:youtube\.com\/(?:embed\/|v\/|watch\?v=)|youtu\.be\/|embed\/)([\w-]+)', url)
    return match.group(1) if match else None

def get_text(element, tag):
    el = element.find(tag)
    return el.text.strip() if el is not None and el.text is not None else None

def extract_and_format_data(xml_data):
    try:
        root = ET.fromstring(xml_data)
        films = {}
        for film_el in root.findall('./Films/Film'):
            code = get_text(film_el, 'Code')
            if not code: continue
            
            films[code] = {
                'code': code,
                'title': get_text(film_el, 'FilmTitle') or get_text(film_el, 'ShortFilmTitle'),
                'synopsis': get_text(film_el, 'Synopsis'),
                'certificate': get_text(film_el, 'Certificate'),
                'runningTime': get_text(film_el, 'RunningTime'),
                'directors': get_text(film_el, 'Directors'),
                'actors': get_text(film_el, 'Actors'),
                'posterUrl': get_text(film_el, 'Img_app') or get_text(film_el, 'Img_1s'),
                'youtubeId': extract_youtube_id(get_text(film_el, 'Youtube')),
                'showtimesByDate': {},
            }

        for perf_el in root.findall('./Performances/Performance'):
            film_code = get_text(perf_el, 'FilmCode')
            if film_code in films:
                date_key = get_text(perf_el, 'PerformDate')
                start_time = get_text(perf_el, 'StartTime')
                if not date_key or not start_time: continue
                
                showtime = {
                    'time': start_time[:-3],
                    'screen': get_text(perf_el, 'Screen'),
                    'bookingUrl': get_text(perf_el, 'BookingURL'),
                    'soldOutLevel': get_text(perf_el, 'SoldOutLevel'),
                    'ticketsSold': get_text(perf_el, 'TicketsSold'),
                    'passesAllowed': get_text(perf_el, 'Passes'),
                }
                
                if date_key not in films[film_code]['showtimesByDate']:
                    films[film_code]['showtimesByDate'][date_key] = []
                films[film_code]['showtimesByDate'][date_key].append(showtime)
        
        return [movie for movie in films.values() if movie['showtimesByDate']]
    except Exception as e:
        print(f"Data Processing Error: {e}")
        return []

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == API_PATH:
            try:
                # Use requests to fetch data, which is more reliable. verify=False ignores SSL errors.
                response = requests.get(EXTERNAL_API_URL, verify=False)
                response.raise_for_status() # Raises an exception for bad status codes (4xx or 5xx)
                
                movie_data_list = extract_and_format_data(response.content)
                json_data = json.dumps(movie_data_list, indent=4).encode('utf-8')
                
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json_data)
            except requests.exceptions.RequestException as e:
                print(f"ERROR during proxy fetch: {e}")
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Proxy Error: {e}")
            return
        # Serve local files like index.html
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

def run_server(server_class=http.server.HTTPServer, handler_class=ProxyHandler):
    # Bind to 0.0.0.0 to be accessible externally (required by Render)
    server_address = ('0.0.0.0', PORT)
    httpd = server_class(server_address, handler_class)
    print(f"Starting server on port {PORT}...")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()

