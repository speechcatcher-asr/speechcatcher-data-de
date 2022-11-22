import argparse
import flask
import request

from flask import Flask, jsonify
from werkzeug.serving import WSGIRequestHandler

from utils import load_config, connect_to_db  

p_connection, p_cursor = None, None

# This flask server utility can distrbiute untranscribed episodes from the db to worker clients that transcribe it.

app = Flask(__name__)
api_version = '/apiv1'
api_secret_key = ''
vtt_dir = ''
sql_table = 'podcasts'
sql_table_ids = 'podcast_episode_id'

# Samples a new untranscribed episode from the db and sends the result as JSON
# to have more diversity early on, we first sample an author and then a random episode from that author
# this helps to not over sample from the authors with the most episodes early on
@app.route(api_version + '/get_work/<language>/<api_access_key>', methods=['GET'])
def get_work(language, api_access_key):
   
    if api_secret_key != api_access_key:
        return jsonify({'success':False, 'error':'api_access_key invalid'})

    return_dict = {'success':False, 'error':'SQL query did not execute'}
    
    # First sample an author (that still has empty transcripts)
    p_cursor.execute(f'SELECT authors,count({sql_table_ids}) from podcasts '
                     'WHERE transcript_file=%s and language=%s GROUP BY authors ORDER BY RANDOM() '
                     'LIMIT 1', ('',language) )
    record = p_cursor.fetchone()

    print("Sampled author:",record)

    if record is not None and len(record) > 0:
        authors, count_episodes = record

        # Use the sampled author to sample a random untranscribed episode from that author
        p_cursor.execute(f'SELECT {sql_table_ids}, episode_title, authors, language, episode_audio_url, cache_audio_url, '
                            'cache_audio_file, transcript_file FROM {sql_table} '
                            'WHERE transcript_file=%s and language=%s and authors=%s ORDER BY RANDOM() '
                            'LIMIT 1', ('',language, authors) )

        record = p_cursor.fetchone()

        if record is not None and len(record) > 0:
            print(record)
            table_id, episode_title, authors, language, episode_audio_url, cache_audio_url, cache_audio_file, transcript_file = record
            return_dict = {'wid':table_id, 'episode_title':episode_title, 'authors':authors,
                            'language':language, 'episode_audio_url':episode_audio_url, 'cache_audio_url':cache_audio_url,
                            'cache_audio_file':cache_audio_file, 'transcript_file':transcript_file, 'success':True}
        else:
            return_dict = {'success':False, 'error':'No episodes without transcription for author: '+authors}

    else:
        return_dict = {'success':False, 'error':'No episodes left without transcriptions.'}

    return jsonify(return_dict)

# Client worker registers that he is working on the transcript. Sets transcript_file = 'in_progress' in the db.
@app.route(api_version + '/register_wip/<wid>/<api_access_key>', methods=['GET'])
def register_wip(wid, api_access_key):

    if api_secret_key != api_access_key:
        return jsonify({'success': False, 'error':'api_access_key invalid'})

    p_cursor.execute(f'SELECT {sql_table_ids}, transcript_file FROM {sql_table} WHERE {sql_table_ids}=%s', (str(wid),))
    record = p_cursor.fetchone()

    table_id, transcript_file = record

    if transcript_file == 'in_progress':
        return jsonify({'success': False, 'error': str(wid)+' already in progress'})
    elif transcript_file != '':
        return jsonify({'success': False, 'error': str(wid)+' already transcribed'})

    p_cursor.execute(f"UPDATE {sql_table} SET transcript_file = 'in_progress' WHERE {sql_table_ids}=%s" , (str(wid),))
    p_connection.commit()

    return jsonify({'success': True})

# Client worker uploads the resulting vtt file. Sets transcript_file to the path of the uploaded file in the db.
@app.route(api_version + '/upload_result/<wid>/<api_access_key>', methods=['POST'])
def upload_result(wid, api_access_key):
    if api_secret_key != api_access_key:
        return jsonify({'success': False, 'error':'api_access_key invalid'})

    if 'file' not in request.files:
        return jsonify({'success': False, 'error':'no file found in POST request'})

    p_cursor.execute(f'SELECT {sql_table_ids}, transcript_file, cache_audio_file, episode_audio_url FROM {sql_table} WHERE {sql_table_ids}=%s', (str(wid),))
    record = p_cursor.fetchone()

    table_id, transcript_file = record

    if transcript_file != 'in_progress':
        return jsonify({'success': False, 'error': str(wid)+' not in progress'})

    if cache_audio_file == '':
        return jsonify({'success': False, 'error': str(wid)+' does not have a cache file, this is currently unsupported'})

    myfile = request.files['file']

    if myfile:
        # Get the directory and filename to store the vtt file
        # The config variable can use {source_dir} as a variable for the directory where the source file is stored
        # We append .vtt to the input filename

        cache_audio_file_split = cache_audio_file.split('/')
        source_dir = '/'.join(cache_audio_file_split[:-1])
        full_filename = vtt_dir.replace('{source_dir}', source_dir) + '/' + cache_audio_file_split[-1] + '.vtt'
        print('Saving vtt file to:', full_filename)
        myfile.save(full_filename)

        p_cursor.execute(f'UPDATE {sql_table} SET transcript_file=%s WHERE {sql_table_ids}=%s', (full_filename, str(wid)))
        p_connection.commit()
    else:
        return jsonify({'success': False, 'error': str(wid)+' could not access upload file'})

    return jsonify({'success': True})

# Cancel work in progress. Sets transcript_file = '' in the db and makes it available for sampling again.
# Will throw an error if transcript_file wasn't previously set to in_progress.
@app.route(api_version + '/cancel_work/<wid>/<api_access_key>', methods=['GET'])
def cancel_work(wid, api_access_key):
    if api_secret_key != api_access_key:
        return jsonify({'error':'api_access_key invalid'})

    p_cursor.execute(f'SELECT {sql_table_ids}, transcript_file FROM {sql_table} WHERE {sql_table_ids}=%s', (str(wid),))
    record = p_cursor.fetchone()

    table_id, transcript_file = record

    if transcript_file != 'in_progress':
        if transcript_file != '':
            return jsonify({'success': False, 'error': str(wid)+' already transcribed'})
        return jsonify({'success': False, 'error': str(wid)+' not in progress'})

    p_cursor.execute(f"UPDATE {sql_table} SET transcript_file = '' WHERE {sql_table_ids}=%s" , (str(wid),))
    p_connection.commit()

    return jsonify({'success': True})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Work distribution server for mass transcription jobs')
    parser.add_argument('-l', '--listen-host', default='127.0.0.1', dest='host', help='Host address to listen on.')
    parser.add_argument('-p', '--port', default=6000, dest='port', help='Port to listen on.', type=int)
    parser.add_argument('--debug', dest='debug', help='Start with debugging enabled',
                        action='store_true', default=False)

    args = parser.parse_args()

    config = load_config()
    api_secret_key = config["secret_api_key"]
    vtt_dir = config["vtt_dir"]

    p_connection, p_cursor = connect_to_db(database=config["database"], user=config["user"], password=config["password"], host=config["host"], port=config["port"])

    if args.debug:
        app.debug = True

    WSGIRequestHandler.protocol_version = 'HTTP/1.1'
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False, use_debugger=False)
    #,  ssl_context='adhoc')
