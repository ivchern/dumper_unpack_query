from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from werkzeug.utils import secure_filename
from parser_service import MessageFileProcessor
import re
import json

app = Flask(__name__)
DATABASE = 'messages.db'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'rar'}


class MessageDatabase:
    def __init__(self, db_name):
        self.db_name = db_name

    def create_table(self, table_name):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id INTEGER NOT NULL,  
                    chat_id TEXT,
                    file_chat TEXT,
                    author_name TEXT,
                    author_link TEXT,
                    message_text TEXT,
                    message_date TEXT,
                    attachment_links TEXT
                )
            ''')

    def insert_data(self, json_data, table_name):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            for item in json_data:
                cursor.execute(f'''
                    INSERT INTO {table_name} (
                        id, chat_id, file_chat, author_name, author_link, message_text, message_date, attachment_links
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id'],
                    item['chat_id'],
                    item['file_chat'],
                    item['author_name'],
                    item['author_link'],
                    item['message_text'],
                    item['message_date'],
                    json.dumps(item.get('attachment_links', []))
                ))

    def commit_and_close(self):
        pass  # You can keep this method empty since closing the connection after each operation

    def execute_query(self, query):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            results = cursor.fetchall()
        return results

db = MessageDatabase(DATABASE)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_valid_database_name(name):
    pattern = re.compile('^[0-9a-zA-Z$_]+$')
    return bool(pattern.match(name))


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'})

    file = request.files['file']
    name_table = str(file.filename).replace('.rar', '').lower()

    if file.filename == '':
        return jsonify({'error': 'No selected file'})

    if not is_valid_database_name(name_table):
        return jsonify({'error': 'Rename to database format'})

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        processor = MessageFileProcessor()
        json_data = processor.process_all_html_files(file_path, app.config['UPLOAD_FOLDER'])

        db.create_table(name_table)
        db.insert_data(json_data, name_table)

        return jsonify({'success': 'File uploaded and processed successfully'})

    return jsonify({'error': 'Invalid file extension'})


@app.route('/')
def index():
    table_list = get_table_list()

    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('index.html', table_list=table_list, upload_status='No file part')

        file = request.files['file']

        if file.filename == '':
            return render_template('index.html', table_list=table_list, upload_status='No selected file')

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            processor = MessageFileProcessor()
            json_data = processor.process_all_html_files(file_path, 'uploads')

            db.create_table(file.filename.replace('rar', '').lower())
            db.insert_data(json_data, file.filename.replace('rar', '').lower())
            db.commit_and_close()

            upload_status = 'File uploaded and processed successfully'
        else:
            upload_status = 'Invalid file extension'

        return render_template('index.html', table_list=table_list, upload_status=upload_status)

    return render_template('index.html', table_list=table_list, upload_status=None)


@app.route('/query', methods=['POST'])
def query():
    user_query = request.form['query']
    results = db.execute_query(user_query)
    table_name = extract_table_name(user_query)
    return render_template('result.html', results=results, my_table=table_name)

def extract_table_name(sql_query):
    match = re.search(r'FROM\s+(\w+)', sql_query, re.IGNORECASE)
    return match.group(1) if match else 'default_table'

@app.route('/details', methods=['GET'])
def details():
    id = request.args.get('id')
    table_name = request.args.get('my_table', 'default_table')  # Provide a default table name if not specified
    if id is not None:
        query = f"SELECT * FROM {table_name} WHERE ID > {int(id) - 200} AND ID <= {int(id) + 200}"
        result_data = db.execute_query(query)
        return render_template('messages.html', results=result_data, selected_id=id)

    return render_template('messages.html', results=[])

@app.route('/search_page', methods=['GET', 'POST'])
def search_page():
    if request.method == 'POST':
        search_text = request.form['search_text']
        search_results = search_all_tables(search_text)
        return render_template('search_page.html', search_results=search_results, search_text=search_text)
    
    return render_template('search_page.html', search_results=None)
def search_all_tables(search_text):
    tables = get_table_list()  # Получаем список всех таблиц
    search_results = []

    for table in tables:
        query = f"SELECT * FROM {table} WHERE message_text LIKE ?"
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (search_text,))
            results = cursor.fetchall()
            if results:
                search_results.append({'table': table, 'results': results})

    return search_results


def get_table_list():
    with sqlite3.connect(DATABASE) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
    return [table[0] for table in tables]


if __name__ == '__main__':
    app.run(debug=True)
