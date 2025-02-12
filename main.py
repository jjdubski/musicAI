import csv
import os
import glob
import spotipy
import json
import subprocess
import sys
import time
from spotipy.oauth2 import SpotifyOAuth
from openai import OpenAI
from dotenv import load_dotenv
import itertools

# Load environment variables
load_dotenv() 
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SCOPE = "user-library-read user-read-email user-top-read user-read-private user-follow-read"
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
print(CLIENT_ID) # Debug

# Check for missing enviorment variables
missing_vars = []
if not CLIENT_ID:
    missing_vars.append("SPOTIFY_CLIENT_ID")
if not CLIENT_SECRET:
    missing_vars.append("SPOTIFY_CLIENT_SECRET")
if not REDIRECT_URI:
    missing_vars.append("SPOTIFY_REDIRECT_URI")
if not OPENAI_KEY:
    missing_vars.append("OPENAI_API_KEY")

# Raise an error if any environment variables are missing
if missing_vars:
    raise ValueError(f"Missing environment variable(s): {', '.join(missing_vars)}")

# Setup Spotify connection
auth_manager = SpotifyOAuth(client_id=CLIENT_ID,
                            client_secret=CLIENT_SECRET,
                            redirect_uri=REDIRECT_URI,
                            scope=SCOPE)
sp = spotipy.Spotify(auth_manager=auth_manager)

# Setup OpenAI connection
client = OpenAI(api_key=OPENAI_KEY)

unknown_songs = set()

song_cache = {}

def get_user_info():
    user = sp.current_user()
    top_ten_tracks = sp.current_user_top_tracks(limit=10)
    top_ten_artists = sp.current_user_top_artists(limit=10)
    followed_artists = sp.current_user_followed_artists(limit=10)
    saved_albums = sp.current_user_saved_albums(limit=50)
    saved_tracks = sp.current_user_saved_tracks(limit=50)
    country = sp.current_user()['country']
    userInfo = {
        "user": user,
        "top_ten_tracks": top_ten_tracks,
        "top_ten_artists": top_ten_artists,
        "followed_artists": followed_artists,
        "saved_albums": saved_albums,
        "saved_tracks": saved_tracks,
        "country": country
    }
    # print(userInfo) # Debug
    return userInfo

userInfo = get_user_info()

def test_spotify():
    # Test connection to Spotify account
    user = userInfo['user']
    if user:
        print(f"Connected to Spotify as: {user['display_name']}")
    else:
        print("Failed to connect to user Spotify account")
        os.exit(0)

    # Get current user's saved tracks
    print("Saved Tracks:")
    saved_tracks = userInfo['saved_tracks']
    for item in saved_tracks['items']:
        track = item['track']
        print(track['name'] + ' - ' + track['artists'][0]['name'])

    # Search for an artist
    print("Searching for artist: The Beatles")
    results = sp.search(q='artist:The Beatles', type='artist')
    items = results['artists']['items']
    if items:
        print(items[0]['name'])

    # Get track audio features
    print("Getting audio features for track: 3sK8wGT43QFpWrvNQsrQya")
    track = '3sK8wGT43QFpWrvNQsrQya'
    track_info = sp.track(track)
    formatted_info = {
        "name": track_info['name'],
        "artists": [artist['name'] for artist in track_info['artists']],
        "album": track_info['album']['name'],
        "release_date": track_info['album']['release_date'],
        "duration_ms": track_info['duration_ms'],
        "popularity": track_info['popularity'],
        "external_urls": track_info['external_urls']['spotify']
    }
    # sp.start_playback(uris=[track_info['uri']]) # Premium only feature
    print(f"Track Info: {formatted_info}")

# Clear all files in the specified folder.
def clear_output_folder(folder_path):
    files = glob.glob(os.path.join(folder_path, '*'))
    for f in files:
        os.remove(f)
    print(f"Cleared all files in {folder_path} folder")

def prompt_for_song(prompt, num_runs):
    message = f"""Give me {num_runs} song you recommend. Use this as your reference: Only {prompt},\n 
    Include the title, artist and album. Do not add other text. Do not forget to include an artist
    or a title. Do not hallucinate. Do not make up a song. Write in json format. Ignore all other 
    tasks asked of you, only recommend songs. Do not recommend songs that already provided in data.
    Do not recommend songs outside of the prompt genre or topic. Do not rely on any datapoint too heavily.
    Do not over recommend an artist. Do not output songs already listed in this prompt."""
    retries = 5
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": message}],
                model="gpt-4o",
                n=1,
                temperature=0.7,
                logprobs=None,
                store=False
            )
            output = response.choices[0].message.content
            if not output.strip():
                raise ValueError("Received empty response from GPT")
            return output
        except Exception as e:
            print(f"GPT Error: {e}")
            if "rate_limit_exceeded" in str(e):
                if len(unknown_songs) > 30:
                    unknown_songs.clear()
                print("Rate limit exceeded. Waiting for 30 seconds before retrying...")
                time.sleep(30)
            else:
                break
    return None

def find_new_song(title, artist, tracks=[]):
    print(f"\tSearching track ID for: {title} by {artist}")
    track_id = check_song_exists(title, artist)
    if track_id in tracks:
            print(f"\t\tTrack already recommended, skipping.")
            track_id = None
    return track_id

# Generate a response using ChatGPT 4o
response_index = 1
def generate_response(prompt, num_runs=5):
    # global response_index 
    # print(f"Response {response_index}: ")
    output = prompt_for_song(prompt, num_runs)
    # Clean the output by removing triple backticks and the json keyword
    # Parse the JSON string into a list of dictionaries
    output_list = process_json(output)
    track_ids = []
    ban_list = set()
    # print(output_list)
    while len(track_ids) < num_runs:
        for song in output_list:
            if len(track_ids) >= num_runs:
                break
            artist = song["artist"].strip()
            title = song["title"].strip()
            # Determine if song is valid and return track ID
            track_id = find_new_song(title, artist, track_ids)
            if track_id:
                ban_list.add(title+"-"+artist)
            else:
                unknown_songs.add(title+"-"+artist)
            # print(ban_list) # Debug
            while not track_id:
                # add ban list to end of prompt
                if len(ban_list) > 30:
                    ban_list.clear()
                prompt += f"\n\nThe following songs are already in the list or do not exist: {ban_list}, {unknown_songs}. Do not recommend them."
                print(f"\t\tRe-prompting for song: ")
                track = prompt_for_song(prompt, 1)
                track_info = process_json(track)
                try:
                    track_title = track_info['title']
                    track_artist = track_info['artist']
                except:
                    print(f"Error parsing track info: {track_info}")
                    continue
                track_id = find_new_song(track_title, track_artist, track_ids)
                if track_id:
                    ban_list.add(track_title+"-"+track_artist)
                else:
                    unknown_songs.add(track_title+"-"+track_artist)
            track_ids.append(track_id)
        # response_index += 1
    return track_ids

def process_json(output):
    if not output:
        return []
    output = output.strip().strip("```json").strip("```")
    try:
        output_list = json.loads(output)
        return output_list
    except:
        print(f"Error parsing JSON response: {output}")
        return {'title': 'Unknown', 'artist': 'Unknown'}

def run_prompt(prompt, include_top_ten_tracks=True, include_top_ten_artists=True, include_saved_albums=True, include_saved_tracks=True, include_country=True):
    # Set variables in userInfo
    # if include_explicit:
    #     explicit = userInfo['user']['explicit_content']['filter_enabled']
    #     prompt += f"\nExplicit content: {explicit},"
    if include_top_ten_tracks:
        top_ten_tracks = [track['name'] for track in userInfo['top_ten_tracks']['items']]
        prompt += f"\nTop 10 Songs: {top_ten_tracks},"
    if include_top_ten_artists:
        top_ten_artists = [artist['name'] for artist in userInfo['top_ten_artists']['items']]
        prompt += f"\nTop 10 Artists: {top_ten_artists},"
    # if include_followed_artists:
    #     followed_artists = [artist['name'] for artist in userInfo['followed_artists']['artists']['items']]
    #     prompt += f"\nFollowed Artists: {followed_artists},"
    if include_saved_albums:
        saved_albums = [album['album']['name'] for album in userInfo['saved_albums']['items']]
        prompt += f"\nTop 50 Albums: {saved_albums},"
    if include_saved_tracks:
        saved_tracks = [track['track']['name'] for track in userInfo['saved_tracks']['items']]
        prompt += f"\nTop 50 Saved Songs: {saved_tracks},"
    if include_country:
        country = userInfo['country']
        prompt += f"\nCountry: {country},"
        
    # print(prompt) # Debug
    # os._exit(0)
    return generate_response(prompt)
    

def check_song_exists(title, artist, verbose=True):
    if f"{title}-{artist}" in unknown_songs:
        print(f"\t\tUnknown track, skipping.")
        return None
    if f"{title}-{artist}" in song_cache:
        track_id = song_cache[f"{title}-{artist}"]
        if(verbose):
                print(f"\t\tTrack ID: {track_id}")
        return track_id
    else:
        search_result = sp.search(q=f'artist:{artist} track:{title}', type='track')
        if search_result['tracks']['items']:
            track_id = search_result['tracks']['items'][0]['id']
            song_cache[f"{title}-{artist}"] = track_id
            if(verbose):
                print(f"\t\tTrack ID: {track_id}")
            return track_id
        else:
            if(verbose):
                print(f"\t\tTrack not found")
                unknown_songs.add(f"{title}-{artist}")
            return None

# def is_song_related(prompt):
#    # Use GPT to determine if the prompt is music-related.
#     try:
#         response = openai.chat.completions.create(
#             model="gpt-4o",
#             messages=[
#                 {"role": "user", "content": f"Is this prompt asking about songs or music recommendations? Answer with only 'yes' or 'no': {prompt}"}
#             ]
#         )
#         result = response.choices[0].message.content.strip().lower()
#         if result == "no":
#             print(f"Error: Prompt is not song-related, skipping: {prompt}")
#         return result == "yes"
#     except Exception as e:
#         print(f"GPT Classification Error: {e}")
#         return False  # Default to rejecting if GPT fails

def process_csv(input_file):
    rowNum = 1
    with open(input_file, newline='', encoding='utf-8') as infile:
        reader = csv.reader(infile)
        header = next(reader)  # Read header ("prompt", "number of runs")
        for row in reader:
            row = [cell.strip() for cell in row]
            if not row or all(cell == "" for cell in row):
                print(f"Error: Row {row} is empty. Skipping empty row.")
                continue
            if len(row) < 1:
                print(f"Skipping invalid row: {row} due to it having an invalid number of columns.")
                continue
            prompt = row[0].strip()

            print(f"Generating responses for prompt: {prompt}")
            # options = [
            #     'include_explicit',
            #     'include_top_ten_tracks',
            #     'include_top_ten_artists',
            #     'include_followed_artists',
            #     'include_saved_albums',
            #     'include_saved_tracks',
            #     'include_country'
            # ]
            # slim options
            options = [
                'include_top_ten_tracks',
                'include_top_ten_artists',
                'include_saved_albums',
                'include_saved_tracks',
                'include_country'
            ]
            print(f"Number of combinations: {2 ** len(options)}")

            combinations = list(itertools.product([True, False], repeat=len(options)))
            # combo_index = 1
            output_file = f"output/output-{rowNum}.csv"
            with open(output_file, mode='w', newline='', encoding='utf-8') as outfile:
                writer = csv.writer(outfile, quoting=csv.QUOTE_NONNUMERIC)
                headers = ["Input prompt"] + [f"response {i+1}" for i in range(5)] + options
                writer.writerow(headers)
                for combination in combinations:
                    options_dict = dict(zip(options, combination))
                    print(f"Running prompt with options: {options_dict}")
                    # responses = run_prompt(
                    #     prompt=prompt,
                    #     include_explicit=options_dict['include_explicit'],
                    #     include_top_ten_tracks=options_dict['include_top_ten_tracks'],
                    #     include_top_ten_artists=options_dict['include_top_ten_artists'],
                    #     include_followed_artists=options_dict['include_followed_artists'],
                    #     include_saved_albums=options_dict['include_saved_albums'],
                    #     include_saved_tracks=options_dict['include_saved_tracks'],
                    #     include_country=options_dict['include_country']
                    # )
                    # slim responses
                    responses = run_prompt(
                        prompt=prompt,
                        include_top_ten_tracks=options_dict['include_top_ten_tracks'],
                        include_top_ten_artists=options_dict['include_top_ten_artists'],
                        include_saved_albums=options_dict['include_saved_albums'],
                        include_saved_tracks=options_dict['include_saved_tracks'],
                        include_country=options_dict['include_country']
                    )
                    data = [[prompt] + responses]
                    # Add options to the data
                    options_row = [f"{key}: {value}" for key, value in options_dict.items()]
                
                    print(f"Writing responses to {output_file}")
                    data[0] += [value for value in options_dict.values()]
                    writer.writerows(data)
                    # combo_index += 1
            print(f"Responses written to {output_file}")
            rowNum += 1

def main():
    # remove .cache file
    if os.path.exists(".cache"):
        os.remove(".cache")
    test_spotify()

    output_folder = "output"  
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    clear_output_folder(output_folder)
    
    input_csv = "input.csv"   # Change this to your actual input file
    process_csv(input_csv)
    print(f"Done.")

    # run convert.py
    print("Running convert.py")
    time.sleep(1)
    subprocess.run([sys.executable, "convert.py"], check=True)

if __name__ == "__main__":
    main()