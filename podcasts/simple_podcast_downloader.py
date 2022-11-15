import feedparser
import wget
import json
import sys
import yaml
import psycopg2
import time
import os
import traceback

test_feed_url = "https://digitalkompakt.podigee.io/feed/mp3"
#test_feed_url = "https://logbuch-netzpolitik.de/feed/opus"

# TODO: make these configurable
language = 'de'
destination_folder = f'/var/www/speechcatcher.net/cache/podcasts/{language}'
destination_url = f'https://speechcatcher.net/cache/podcasts/{language}'

p_connection = None
p_cursor = None

def ensure_dir(f):
    d = os.path.dirname(f)
    if not os.path.exists(d):
        os.makedirs(d)


def load_config(config_filename='config.yaml'):
    with open("config.yaml", "r") as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
            sys.exit(-3)

def connect_to_db(database, user, password, host='127.0.0.1', port='5432'):
    # Connect to DB
    try:
        mct_connection = psycopg2.connect(user = user,
                                      password = password,
                                      host = host,
                                      port = port,
                                      database = database)

        mct_cursor = mct_connection.cursor()

        # Print PostgreSQL version
        mct_cursor.execute("SELECT version();")
        record = mct_cursor.fetchone()
        print("You are connected to Postgres - ", record,"\n")

        return mct_connection, mct_cursor

    except (Exception, psycopg2.Error) as error :
        print ("Error while connecting to PostgreSQL", error)
        sys.exit(-1)

def check_audio_url(cursor, episode_audio_url):
    cursor.execute('SELECT episode_audio_url, cache_audio_url, cache_audio_file,'\
                   'transcript_file from podcasts where episode_audio_url=%s', (episode_audio_url,) )
    record = cursor.fetchone()
    if record is not None and len(record) > 0:
        episode_audio_url, cache_audio_url, cache_audio_file, transcript_file = record
        print(f'Skipping, URL already in the database: {episode_audio_url} with {cache_audio_url=} {cache_audio_file=} {transcript_file=}')
        return True
    return False

def parse_and_download(feed_url):
    d = feedparser.parse(test_feed_url)

    podcast_title = d.feed['title']

    for episode in d.entries:

        episode_title = episode["title"]    
        desc = episode["description"]
        published = episode["published"]
        tags = []
        duration = -1
        link = ''
        audiolink = ''

        # find the audio link in the links section
        for elem in episode["links"]:
            if elem["type"].startswith("audio"):
                mytype = elem["type"]
                audiolink = elem["href"]
            elif elem["type"].startswith("text/html"):
                link = elem["href"]

        # add tags (keywords) to list if available
        if 'tags' in episode: 
            for tag in episode['tags']:
                tags.append(tag['term'])

        # get the duration, sometimes its in seconds sometimes hh:mm:ss.
        # we convert everything to seconds
        if 'itunes_duration' in episode:
            duration = episode['itunes_duration']

            if ':' in duration:
                dur_split = duration.split(':')
                assert(len(dur_split) == 3)
                duration = int(dur_split[0])*3600 + int(dur_split[1])*60 + int(dur_split[2])
            else:
                duration = int(duration)
        else:
            print('Warning: no itunes_duration in episode')
        
        authors = ' '.join(author["name"] for author in episode["authors"])
        joined_tags = ', '.join(tags)
        cache_url = ''
        cache_file = ''
        transcript_file = ''

        # Use default=str for delta timedelta objects (parsed dates), since the json.dumps function can't handle them otherwise
        episode_json = json.dumps(episode, default=str) 

        #print(episode_json)
        print(f"{mytype=}, {episode_title=}, {authors=}, {joined_tags}, {duration=}, {link=}, {audiolink=} {published=}")

        # Only insert into DB if audio URL doesn't already exist in the DB
        if not check_audio_url(p_cursor, episode_audio_url=audiolink):
            # Try to download audiolink and insert into db if succesful
            try:
                audiolink_split = audiolink.split('?')
                assert(len(audiolink_split) == 2)
                audio_filename = audiolink_split[0].split('/')[-1]
                assert(len(audio_filename) > 0)
                # insert unixtime to guarantee that the link is unique
                retrieval_time = time.time()
                unixtime = str(int(retrieval_time))
                cache_file = destination_folder  + '/' + unixtime + '_' + audio_filename
                cache_url = destination_url + '/' + unixtime + '_' + audio_filename 
                
                print('Downloading to:', cache_file)
                print('Cache file will be available at:', cache_url)
                wget.download(audiolink, out=cache_file, bar=wget.bar_thermometer)
                print()

                sql = "INSERT INTO podcasts(podcast_title, episode_title, published_date, retrieval_time, authors, language, description, keywords, episode_url, episode_audio_url," \
                  " cache_audio_url, cache_audio_file, transcript_file, duration, type, episode_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                p_cursor.execute(sql, (podcast_title, episode_title, published, str(retrieval_time), authors, language, desc, joined_tags, link, audiolink, cache_url, cache_file, transcript_file, str(duration), mytype, episode_json))
            except:
                print('Error occured while trying to download:', audiolink)
                traceback.print_exc()

    p_connection.commit()

if __name__ == "__main__":
    config = load_config()
    ensure_dir(destination_folder)
    p_connection, p_cursor = connect_to_db(database=config["database"], user=config["user"], password=config["password"], host=config["host"], port=config["port"])
    parse_and_download(test_feed_url)
