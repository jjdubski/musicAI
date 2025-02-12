import os
import sys
import subprocess
import spotipy
import requests
import json
import time
from ollama import chat
from ollama import ChatResponse
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

# Setup DeepSeek connection
inputModel = "deepseek-r1:1.5b"
num_ctx = 4096
headers = {
    'Content-Type': 'application/json'
}

def setup_deepseek():
    # Stop the existing container if running
    print("\033[34m Stopping the existing container... \033[0m")
    try:
        subprocess.run(["docker", "stop", "ollama"], check=True)
    except subprocess.CalledProcessError as e:
        print("\033[33m No existing container to stop. \033[0m") 

    # Remove the existing container
    print("\033[34m Removing the existing container... \033[0m")
    try:
        subprocess.run(["docker", "rm", "ollama"], check=True)
    except subprocess.CalledProcessError as e:
        print("\033[33m No existing container to remove. \033[0m")

    # Run a new container
    print("\033[34m Starting a new container... \033[0m")
    try:
        subprocess.run([
        "docker", "run", "-d", "-v", "ollama:/root/.ollama", 
        "-p", "11434:11434", "--name", "ollama", "ollama/ollama"
        ], check=True)
    except subprocess.CalledProcessError as e:
        sys.exit("\033[31m Failed to start the container. Ensure Docker is running. \033[0m")

    # Pull the model
    print(f"Pulling the model {inputModel}...")
    try:
        subprocess.run(["docker", "exec", "ollama", "ollama", "pull", inputModel], check=True)
    except:
        sys.exit(f"\033[31m Failed to pull the model: \t{inputModel} \n\033[0m Make sure you have the correct model name.")

def test_deepseek():
    # Check if ollama container is running
    print("\033[34m Checking if the container is running... \033[0m")
    try:
        subprocess.run(["docker", "logs", "ollama"], check=True)
    except subprocess.CalledProcessError as e:
        sys.exit("\033[31m Container is not running. \033[0m")

    # Notfiy the user that the container has started successfully
    print("\033[32m Container started successfully! \033[0m")
    print("\033[34m Connecting to the container... \033[0m")

    # Wait for the container to start
    time.sleep(3)

    # Check connection to ollama container
    try:
        response = requests.get('http://localhost:11434/api/version')
        if response.status_code == 200:
            version_info = json.loads(response.text)
    except:
        sys.exit('\033[31m Failed to connect to ollama. \033[0m')
    print("\033[32m Connected to ollama successfully! \n\033[0m")

    # Check the if a model is available
    print(" Checking available models...")    
    try:
        response = requests.get('http://localhost:11434/api/tags')
        if response.status_code == 200:
            # Debug
            # models = json.loads(response.text)
            # print("Available models:")
            # for model in models['models']:
            #     print(f"Name: {model['name']}")
            #     print(f"Model: {model['model']}")
            #     print(f"Modified At: {model['modified_at']}")
            #     print(f"Size: {model['size']} bytes")
            #     print(f"Digest: {model['digest']}")
            #     print("Details:")
            #     for key, value in model['details'].items():
            #         print(f"  {key}: {value}")
            models = json.loads(response.text)
            print(" Available models:")
            for model in models['models']:
                print(f"\033[0mName:\033[35m {model['name']} \033[0m")
                print(f"Model:\033[35m {model['model']} \033[0m")
                print(f"Size:\033[35m {model['size']} bytes \n\033[0m")
    except:
        sys.exit('\033[31m No models found. Try to pull manually. \033[0m')

    print("\033[36m Running a test prompt with your model... \n\033[0m")  
    start_time = time.time()
    try:
        response = requests.post(
                'http://localhost:11434/api/generate',
                headers=headers,
                data=json.dumps({
                    'model': inputModel,
                    'prompt': ' ',
                })
            )
    except:
        sys.exit('\033[31m Your model is not functioning or missing. Try to remove it and pull manually. \033[0m')
    end_time = time.time()
    print(f"\033[32m Test prompt completed in \033[0m{end_time - start_time:.2f} seconds")
    print("\033[32m All tests passed successfully. \033[0m")    
    print(f"\033[33m Using model:\t{inputModel} \033[0m\n")

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
            response = requests.post(
            'http://localhost:11434/api/generate',
            headers=headers,
            data=json.dumps({
                'model': inputModel,
                'prompt': prompt+"Only JSON format as output, follow this template {title: '', artist: '', album: ''}",
                "options": {"num_ctx": num_ctx}
                })
            )
            time.sleep(1)
            if response.status_code == 200:
                thinking = True
                # i = 1
                for line in response.text.splitlines():
                    try:
                        data = json.loads(line)
                        if 'response' in data:
                            # print(i,". ", data['response'], end='') # Debug
                            if '<think>' in data['response']:
                                thinking = True
                            elif'</think>' in data['response']:
                                thinking = False
                            else:
                                response = data['response']
                                if not thinking:
                                    print(response, end='')
                    except json.JSONDecodeError:
                        continue
                    # i += 1
            else:
                print(f"\nRequest failed with status code {response.status_code}")
                print(f"Response: {response.text}")
            if not response.strip():
                raise ValueError("Received empty response from GPT")
            return response
        except Exception as e:
            break
    return None

def find_new_song(title, artist, tracks=[]):
    print(f"\tSearching track ID for: {title} by {artist}")
    track_id = check_song_exists(title, artist)
    if track_id in tracks:
            print(f"\t\tTrack already recommended, skipping.")
            track_id = None
    return track_id

# Generate a response 
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
    if output is None:
        print("Error: Received None as output.")
        return 
    output = output.strip().strip("```json").strip("```")
    try:
        output_list = json.loads(output)
        return output_list
    except:
        print(f"Error parsing JSON response: {output}")
        return 

def run_prompt(prompt, userInfo, include_top_ten_tracks=True, include_top_ten_artists=True, include_saved_albums=True, include_saved_tracks=True, include_country=True):
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
    if f"{title}-{artist}" in unknown_songs:
        if(verbose):
            print(f"\t\tUnknown track, skipping.")
        return None
    search_result = sp.search(q=f'artist:{artist} track:{title}', type='track')
    if search_result['tracks']['items']:
        track_id = search_result['tracks']['items'][0]['id']
        song_cache[track_id] = search_result['tracks']['items'][0]
        if(verbose):
            print(f"\t\tTrack ID: {track_id}")
        return track_id
    else:
        if(verbose):
            print(f"\t\tTrack not found")
            unknown_songs.add(f"{title}-{artist}")
        return None

def main():
    # Setup DeepSeek
    setup_deepseek()
    test_deepseek()
    # remove .cache file
    if os.path.exists(".cache"):
        os.remove(".cache")
    userInfo = get_user_info()
    prompt = input("Topic or genre: ")
    options = [
        'include_top_ten_tracks',
        'include_top_ten_artists',
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
        userInfo=userInfo,
        include_top_ten_tracks=options_dict['include_top_ten_tracks'],
        include_top_ten_artists=options_dict['include_top_ten_artists'],
        include_saved_albums=options_dict['include_saved_albums'],
        include_saved_tracks=options_dict['include_saved_tracks'],
        include_country=options_dict['include_country']
    )
    # print(f"Track IDs: {tracks}\n") # Debug
    print(f"\nBased on '{prompt}'")
    print("🎶 Here are the recommended songs:\n")
    index = 1
    for track in tracks:
        track_info = song_cache[track]
        print(f"{index}. {track_info['name']}")
        print(f"\tArtist: {track_info['artists'][0]['name']}")
        print(f"\tAlbum: {track_info['album']['name']}")
        print(f"\tURL: {track_info['external_urls']['spotify']}\n")
        index += 1

if __name__ == "__main__":
    main()