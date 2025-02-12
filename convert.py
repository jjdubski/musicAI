import csv
import ast
import os
import time
import glob
import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

# Load environment variables
load_dotenv() 
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SCOPE = "user-library-read user-read-email user-top-read user-read-private"

# Check for missing environment variables
missing_vars = []
if not CLIENT_ID:
    missing_vars.append("SPOTIFY_CLIENT_ID")
if not CLIENT_SECRET:
    missing_vars.append("SPOTIFY_CLIENT_SECRET")
if not REDIRECT_URI:
    missing_vars.append("SPOTIFY_REDIRECT_URI")

# Raise an error if any environment variables are missing
if missing_vars:
    raise ValueError(f"Missing environment variable(s): {', '.join(missing_vars)}")


auth_manager = SpotifyOAuth(client_id=CLIENT_ID,
                            client_secret=CLIENT_SECRET,
                            redirect_uri=REDIRECT_URI,
                            scope=SCOPE)
sp = spotipy.Spotify(auth_manager=auth_manager)

song_cache = {}

# Clear all files in the specified folder.
def clear_output_folder(folder_path):
    for root, dirs, files in os.walk(folder_path, topdown=False):
        for file in files:
            os.remove(os.path.join(root, file))
        for dir in dirs:
            os.rmdir(os.path.join(root, dir))
    print(f"Cleared all files and folders in {folder_path} folder")

# Function to convert input data to structured CSV
def convert_to_csv(data, output_file):
    with open(output_file, 'w', newline='', encoding='utf8') as csvfile:
        fieldnames = ['artist', 'title', 'album', 'prompt', 'include_top_ten_tracks', 'include_top_ten_artists', 'include_saved_albums', 'include_saved_tracks', 'include_country']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in data:
            prompt = row[0]
            responses = row[1:6]
            options = row[6:]  # Changed to include all elements from index 6 onwards
            if prompt.lower().strip() == "input prompt":
                # print(f"Skipping header row: {row}")
                continue
            for response in responses:
                try:
                    if(response.strip() == True or response.strip() == False):
                        continue
                    track_id = response.strip()
                    try:
                        if track_id not in song_cache:
                            print(f"Fetching track ID {track_id} from Spotify API...")
                            song_cache[track_id] = sp.track(track_id)
                        else:
                            print(f"Track ID {track_id} found in cache.")
                        track = song_cache[track_id]
                        artist = track['artists'][0]['name']
                        title = track['name']
                        album = track['album']['name']
                        row_dict = {
                            'prompt': prompt,
                            'artist': artist,
                            'title': title,
                            'album': album,
                            'include_top_ten_tracks': options[0].strip(),
                            'include_top_ten_artists': options[1].strip(),
                            'include_saved_albums': options[2].strip(),
                            'include_saved_tracks': options[3].strip(),
                            'include_country': options[4].strip() if len(options) > 4 else ''
                        }
                        writer.writerow(row_dict)
                    except spotipy.exceptions.SpotifyException as e:
                        print(f"Spotify API error for track ID {response}: {e}")
                        if "rate limit" in str(e).lower() or "timeout" in str(e).lower():
                            wait_time = 60 
                            print(f"Rate limit or timeout error. Waiting for {wait_time} seconds before retrying...")
                            time.sleep(wait_time)
                    time.sleep(0.1)  # Add a delay to avoid rate limiting
                except (SyntaxError, ValueError) as e:
                    print(f"Error evaluating response: {response} - {e}")
            time.sleep(0.5)  # Add a delay to avoid rate limiting

def main():
    # Load input data from all CSV files in the output directory
    output_dir_path = './output'
    formatted_dir_path = './formatted'

    if not os.path.exists(formatted_dir_path):
        os.makedirs(formatted_dir_path)
    clear_output_folder(formatted_dir_path)

    # folder_number = 1    
    for filename in sorted(os.listdir(output_dir_path)):
        if filename.endswith('.csv'):
            # Create a unique folder for each group of files based on output number
            # unique_folder_path = os.path.join(formatted_dir_path, f'output')
            # os.makedirs(unique_folder_path, exist_ok=True)
            # Check if number after first - and after output is the same as folder_number
            # if filename.split('-')[1] != str(folder_number):
            #     folder_number += 1
            
            input_file_path = os.path.join(output_dir_path, filename)
            output_file_path = os.path.join(formatted_dir_path, filename)
            
            data = []
            with open(input_file_path, 'r') as csvfile:
                csvreader = csv.reader(csvfile)
                for row in csvreader:
                    data.append(row)
            convert_to_csv(data, output_file_path)

    print(f"Done.")

if __name__ == "__main__":
    main()