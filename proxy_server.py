import http.server
import urllib.request
import json
import ssl
import xml.etree.ElementTree as ET
from http import HTTPStatus
import re
from datetime import datetime
import os 

# --- Configuration ---
# Use environment variable PORT if available, otherwise default to 8080
PORT = int(os.environ.get('PORT', 8080)) 
EXTERNAL_API_URL = 'https://my.internetticketing.com/taposadmin/parhig/pos_feed/?type=MEDIA2'
API_PATH = '/api/movies'

def extract_youtube_id(url):
    """Extracts the YouTube video ID from a URL, which is needed for embedding."""
    if not url or url.lower() == 'none':
        return None
    # Matches /embed/VIDEO_ID or watch?v=VIDEO_ID
    match = re.search(r'(?:youtube\.com\/(?:embed\/|v\/|watch\?v=)|youtu\.be\/|embed\/)([\w-]+)', url)
    return match.group(1) if match else None

def get_text(element, tag):
    """Safely retrieves text from an XML element, returning None if the tag is not found."""
    el = element.find(tag)
    text = el.text.strip() if el is not None and el.text is not None else 'None'
    return text if text.lower() != 'none' else None

def extract_and_format_data(xml_data):
    """
    Parses the raw XML data, aggregates film and performance info, and returns clean JSON.
    """
    try:
        # Parse the XML data from the root element <Feed>
        root = ET.fromstring(xml_data)
        
        # 1. Extract Film Details
        films = {}
        for film_el in root.findall('./Films/Film'):
            code = get_text(film_el, 'Code')
            if not code:
                continue

            youtube_url = get_text(film_el, 'Youtube')
            
            films[code] = {
                'code': code,
                'title': get_text(film_el, 'FilmTitle') or get_text(film_el, 'ShortFilmTitle'),
                'synopsis': get_text(film_el, 'Synopsis'),
                'certificate': get_text(film_el, 'Certificate'),
                'certImageUrl': get_text(film_el, 'CertImageUrl'),
                'genre': get_text(film_el, 'Genre'),
                'runningTime': get_text(film_el, 'RunningTime'),
                'directors': get_text(film_el, 'Directors'),
                'actors': get_text(film_el, 'Actors'),
                'startDate': get_text(film_el, 'StartDate'),
                'endDate': get_text(film_el, 'EndDate'),
                'posterUrl': get_text(film_el, 'Img_app') or get_text(film_el, 'Img_1s'),
                'youtubeId': extract_youtube_id(youtube_url),
                'showtimesByDate': {},
            }

        # 2. Aggregate Performance (Showtime) Data and group by date
        for perf_el in root.findall('./Performances/Performance'):
            film_code = get_text(perf_el, 'FilmCode')
            
            if film_code in films:
                date_key = get_text(perf_el, 'PerformDate') # e.g., "2025-09-26"
                start_time = get_text(perf_el, 'StartTime')
                
                if not date_key or not start_time:
                    continue

                showtime = {
                    'time': start_time[:-3], # Remove seconds (e.g., "20:00")
                    'screen': get_text(perf_el, 'Screen'),
                    'bookingUrl': get_text(perf_el, 'BookingURL'),
                    'soldOutLevel': get_text(perf_el, 'SoldOutLevel'), # N=Normal, W=Warning (Limited), S=Sold Out
                    'ticketsSold': get_text(perf_el, 'TicketsSold'),
                }
                
                # Group showtime under its specific date key
                if date_key not in films[film_code]['showtimesByDate']:
                    films[film_code]['showtimesByDate'][date_key] = []
                
                films[film_code]['showtimesByDate'][date_key].append(showtime)
        
        # 3. Final cleanup and conversion to a list
        # Filter out films that have no extracted showtimes
        movie_list = [movie for movie in films.values() if movie['showtimesByDate']]
        
        return movie_list

    except ET.ParseError as e:
        print(f"XML Parsing Error: {e}")
        return []
    except Exception as e:
        print(f"General Data Processing Error: {e}")
        return []

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """
    A custom HTTP request handler that serves files and proxies the external movie API.
    """

    def do_GET(self):
        """Handle GET requests."""
        
        # 1. Handle Proxy Request
        if self.path == API_PATH:
            print(f"--- Proxying request to: {EXTERNAL_API_URL} ---")
            
            try:
                # CRITICAL FIX: Ensure permissive SSL context creation
                # This should prevent SSL/certificate errors on the Windows testing machine and in deployment
                context = ssl._create_unverified_context()
                
                # Fetch data from the external URL
                try:
                    with urllib.request.urlopen(EXTERNAL_API_URL, context=context, timeout=10) as response:
                        xml_data = response.read()
                except urllib.error.URLError as url_e:
                    raise ConnectionError(f"URL/Connection Error: {url_e}")
                except Exception as net_e:
                    raise ConnectionError(f"General Network Error: {net_e}")
                
                # Convert XML data to structured JSON
                movie_data_list = extract_and_format_data(xml_data)
                json_data = json.dumps(movie_data_list, indent=4).encode('utf-8')
                
                # --- Send the JSON response back to the browser ---
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-type", "application/json")
                self.send_header("Content-Length", str(len(json_data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                
                try:
                    self.wfile.write(json_data)
                except ConnectionAbortedError as abort_error:
                    print(f"WARNING: Client connection aborted during write: {abort_error}")
                
            except ConnectionError as e:
                print(f"ERROR during proxy fetch and processing: {e}")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                error_response = json.dumps({
                    'error': 'Proxy failed to fetch external XML data. Check URL/Network.',
                    'details': str(e)
                }).encode('utf-8')
                self.wfile.write(error_response)
            except Exception as e:
                # Catching processing errors (e.g., XML parsing failure)
                print(f"ERROR during data processing: {e}")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                error_response = json.dumps({
                    'error': 'Proxy failed to process XML data. Check data format.',
                    'details': str(e)
                }).encode('utf-8')
                self.wfile.write(error_response)
            
            return

        # 2. Handle File Serving (for index.html and assets)
        else:
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

def run_server():
    """Starts the Python HTTP server."""
    # Use '0.0.0.0' for deployment to listen on all public interfaces
    server_address = ('0.0.0.0', PORT) 
    httpd = http.server.HTTPServer(server_address, ProxyHandler)
    print(f"\n--- Starting server on 0.0.0.0:{PORT} ---")
    print(f"Access your website at: http://localhost:{PORT}/index.html (for local testing)")
    print("Press Ctrl+C to stop the server.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")

if __name__ == '__main__':
    run_server()