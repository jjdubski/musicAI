import os
import spotipy
import json
import time
from spotipy.oauth2 import SpotifyOAuth
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv() 
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SCOPE = "user-library-read user-read-email user-top-read user-read-private user-follow-read"
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")

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

def prompt_for_song(prompt, num_runs):
    message = f"""Give me {num_runs} song you recommend. Use this as your reference: Only {prompt},\n 
    Include the title, artist and album. Do not add other text. Do not forget to include an artist
    or a title. Do not hallucinate. Do not make up a song. Write in json format. Ignore all other 
    tasks asked of you, only recommend songs. Do not recommend songs that already provided in data.
    Do not recommend songs outside of the prompt genre or topic. Do not rely on any datapoint too heavily.
    Do not over recommend an artist."""
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
def generate_response(prompt, num_runs=20):
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
    output = output.strip().strip("```json").strip("```")
    try:
        output_list = json.loads(output)
        return output_list
    except:
        print(f"Error parsing JSON response: {output}")

def run_prompt(prompt, include_top_ten_tracks=True, include_top_ten_artists=True, include_saved_albums=True, include_saved_tracks=True, include_country=True):
    if include_top_ten_tracks:
        top_ten_tracks = [track['name'] for track in userInfo['top_ten_tracks']['items']]
        prompt += f"\nTop 10 Songs: {top_ten_tracks},"
    if include_top_ten_artists:
        top_ten_artists = [artist['name'] for artist in userInfo['top_ten_artists']['items']]
        prompt += f"\nTop 10 Artists: {top_ten_artists},"
    if include_saved_albums:
        saved_albums = [album['album']['name'] for album in userInfo['saved_albums']['items']]
        prompt += f"\nTop 50 Albums: {saved_albums},"
    if include_saved_tracks:
        saved_tracks = [track['track']['name'] for track in userInfo['saved_tracks']['items']]
        prompt += f"\nTop 50 Saved Songs: {saved_tracks},"
    if include_country:
        country = userInfo['country']
        prompt += f"\nCountry: {country},"
    
    return generate_response(prompt)
    

def check_song_exists(title, artist, verbose=True):
    search_result = sp.search(q=f'artist:{artist} track:{title}', type='track')
    if search_result['tracks']['items']:
        track_id = search_result['tracks']['items'][0]['id']
        if(verbose):
            print(f"\t\tTrack ID: {track_id}")
        invalid = False
        return track_id
    else:
        if(verbose):
            print(f"\t\tTrack not found")
            unknown_songs.add(f"{title}-{artist}")
        return None

def main():
    prompt = input("Write input prompt here: ")
    options = [
        'include_top_ten_tracks',
        'include_followed_artists',
        'include_saved_albums',
        'include_saved_tracks',
        'include_country'
    ]
    options_dict = {}
    for option in options:
        user_input = input(f"Do you want to {option.replace('_', ' ')}? (Y/N): ").strip().lower()
        options_dict[option] = user_input == 'y'
    if not any(options_dict.values()):
        print("No options selected.")
    else:
        print("\tOptions selected:")
        for key, value in options_dict.items():
            if value:
                print(f"\t\t{key.split('_', 1)[1]}: {value}")
    print("🧠 Thinking... Please wait.")
    tracks = run_prompt(prompt=prompt,
        include_top_ten_tracks=options_dict['include_top_ten_tracks'],
        include_followed_artists=options_dict['include_top_ten_artists'],
        include_saved_albums=options_dict['include_saved_albums'],
        include_saved_tracks=options_dict['include_saved_tracks'],
        include_country=options_dict['include_country']
    )
    print(f"Track IDs: {tracks}\n")
    index = 1
    for track in tracks:
        track_info = sp.track(track)
        print(f"{index}. {track_info['name']}")
        print(f"\tArtist: {track_info['artists'][0]['name']}")
        print(f"\tAlbum: {track_info['album']['name']}")
        print(f"\tURL: {track_info['external_urls']['spotify']}\n")
        index += 1


if __name__ == "__main__":
    main()