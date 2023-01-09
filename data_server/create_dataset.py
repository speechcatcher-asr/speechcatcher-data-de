# Create a dataset (Kaldi format) with the server.py API for podcasts.
# The dataset is divided into train/dev/test.
# Timestamps from the vtt files are used for the segments.

import requests
import random
import argparse
from utils import *

# This joins consecutive segments at random, up to a specified max length.
# The output segment list is shortened and the segments are longer. 
def join_consecutive_segments_randomly(segments, max_length=10):
    
    segments_copy = segments.copy()
    joined_segments = []

    i = 0
    max_i = len(segments_copy)
    while i < len(segments_copy):
        num_segments_to_merge = random.randint(2, max_length)

        if i+num_segments_to_merge > max_i:
          num_segments_to_merge = max_i - i

        if num_segments_to_merge == 0:
            break

        # Merge the chosen number of segments
        segment_text = ' '.join([segment['text'] for segment in segments_copy[i:i+num_segments_to_merge]])
        
        joined_segments.append({
            'start': segments_copy[i]['start'],
            'end': segments_copy[i+num_segments_to_merge-1]['end'],
            'text': segment_text
        })

        i += num_segments_to_merge

    return joined_segments

# Download the VTT file
def download_vtt_file(vtt_file_url):
    response = requests.get(vtt_file_url)
    vtt_content = response.text

    return vtt_content

# Parse a VTT file and extract timestamps and text
def parse_vtt_segments(vtt_content):
    lines = vtt_content.split('\n')
    segments = []

    # Iterate over the lines and parse the segments
    current_segment = None
    for line in lines:
        if line.startswith('WEB'):
            continue
        # This line indicates the start of a new segment and time stamp info
        if '-->' in line:
            if current_segment:
                segments.append(current_segment)
            a,b = line.split('-->')
            a,b = a.strip(), b.strip()
            current_segment = {'start': a, 'end': b, 'text':''}
        elif line.strip():
            if current_segment['text'] == '':
                current_segment['text'] = line
            else:
                current_segment['text'] += '\n' + line

    # Add the last segment
    if current_segment:
        segments.append(current_segment)

    return segments

# Process all episodes of a particular podcast
def process_podcast(server_api_url, api_secret_key, title):

    request_url = f"{server_api_url}/get_episode_list/{api_secret_key}"
    data = {'podcast_title': title}

    print('server_api_url:', request_url)

    response = requests.post(request_url, data=data)

    episode_list = response.json()

    print(episode_list)

    for episode in episode_list:
        print('parsing:', episode['episode_title'])
        vtt_content = download_vtt_file(episode['transcript_file_url'])
        segments = parse_vtt_segments(vtt_content) 
        segments_merged = join_consecutive_segments_randomly(segments)
        for segment in segments_merged:
            print(segment)

# Divide dataset into train/dev/test and start processing the podcasts
def process(server_api_url, api_secret_key, dev_n=10, test_n=10, test_dev_episodes_threshold=10):
    
    request_url = f"{server_api_url}/get_podcast_list/de/{api_secret_key}"
    response = requests.get(request_url)
    podcast_list = response.json()

    #print(podcast_list)

    podcast_list_test_dev_pool = [podcast for podcast in podcast_list if (podcast['count'] < test_dev_episodes_threshold)]

    dev_set = random.sample(podcast_list_test_dev_pool, 10)
    podcast_list_test_dev_pool = [x for x in podcast_list_test_dev_pool if x not in dev_set]

    test_set = random.sample(podcast_list_test_dev_pool, 10)

    train_set = [x for x in podcast_list if (x not in dev_set) and (x not in test_set)]

    print(dev_set)
    print(test_set)

    for elem in dev_set:
        process_podcast(server_api_url, api_secret_key, elem['title'])

    for elem in test_set:
        process_podcast(server_api_url, api_secret_key, elem['title'])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a dataset (Kaldi format) with the server.py API')
    parser.add_argument('-d', '--dev', default=10, dest='dev_n', help='Sample dev set from n speakers/podcasts', type=int)
    parser.add_argument('-t', '--test', default=10, dest='test_n', help='Sample test set from n speakers/podcasts', type=int)
    parser.add_argument('--debug', dest='debug', help='Start with debugging enabled',
                        action='store_true', default=False)

    args = parser.parse_args()

    random.seed(42)
    config = load_config()
    api_secret_key = config["secret_api_key"]
    # FIXME: move to yaml
    server_api_url = 'https://speechcatcher.net/apiv1/'
    process(server_api_url, api_secret_key, args.dev_n, args.test_n)