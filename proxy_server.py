import http.server
import urllib.request
import json
import ssl
import xml.etree.ElementTree as ET
from http import HTTPStatus
import re

# --- Configuration ---
PORT = 8080
EXTERNAL_API_URL = 'https://my.internetticketing.com/taposadmin/parhig/pos_feed/?type=MEDIA2'
API_PATH = '/api/movies'

def extract_youtube_id(url):
    if not url or url.lower() == 'none':
        return None
    match = re.search(r'(?:youtube\.com\/(?:embed\/|v\/|watch\?v=)|youtu\.be\/|embed\/)([\w-]+)', url)
    return match.group(1) if match else None

def get_text(element, tag):
    el = element.find(tag)
    text = el.text.strip() if el is not None and el.text is not None else None
    return text

def extract_and_format_data(xml_data):
    try:
        root = ET.fromstring(xml_data)
        films = {}
        for film_el in root.findall('./Films/Film'):
            code = get_text(film_el, 'Code')
            if not code:
                continue
            
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
                if not date_key or not start_time:
                    continue
                
                showtime = {
                    'time': start_time[:-3],
                    'screen': get_text(perf_el, 'Screen'),
                    'bookingUrl': get_text(perf_el, 'BookingURL'),
                    'soldOutLevel': get_text(perf_el, 'SoldOutLevel'),
                    'ticketsSold': get_text(perf_el, 'TicketsSold'),
                    'passesAllowed': get_text(perf_el, 'Passes'), # <-- CORRECTED LOCATION
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
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(EXTERNAL_API_URL, context=context) as response:
                    xml_data = response.read()
                
                movie_data_list = extract_and_format_data(xml_data)
                json_data = json.dumps(movie_data_list, indent=4).encode('utf-8')
                
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json_data)
            except Exception as e:
                print(f"ERROR during proxy fetch: {e}")
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Proxy Error")
            return
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

def run_server():
    server_address = ('', PORT)
    httpd = http.server.HTTPServer(server_address, ProxyHandler)
    print(f"Starting server on http://localhost:{PORT}")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()