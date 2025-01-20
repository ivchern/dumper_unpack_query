import tempfile
from bs4 import BeautifulSoup
import os
import glob
import sqlite3
import json
from tqdm import tqdm
import rarfile
import shutil
import re
from concurrent.futures import ThreadPoolExecutor, as_completed


class MessageParser:
    def __init__(self):
        self.date_format = "%d.%m.%Y %H:%M"

    def parse_date_time(self, date_time_str):
        try:
            date_time_obj = datetime.strptime(date_time_str, self.date_format)
            date_only = date_time_obj.date()
            time_only = date_time_obj.time()
            return {"date": date_only, "time": time_only}
        except ValueError as e:
            return {"error": str(e)}
        
    def extract_number(self,file_path):
        try:
            return int(''.join(filter(str.isdigit, os.path.basename(file_path))))
        except ValueError:
            return float('inf')

class MessageExtractor(MessageParser):
    def __init__(self):
        super().__init__()

    def get_author_blocks(self, soup):
        try:
            return soup.find('div', class_='wrapped')
        except Exception as e:
            print(f'Ошибка при получении блоков: {e}')
            return None

    def get_im_in_blocks(self, soup):
        try:
            return soup.find_all('div', class_='im_in')
        except Exception as e:
            print(f'Ошибка при получении блоков: {e}')
            return []

    def get_name(self, block):
        try:
            return block.find('a', class_='mem_link').text.strip()
        except Exception as e:
            print(f'Ошибка при получении имени: {e}')
            return None

    def get_user_id(self, href_value):
        try:
            return href_value.replace('https://vk.com/id', '')
        except Exception as e:
            print(f'Ошибка при извлечении user_id: {e}')
            return None

    def get_message_date(self, block):
        try:
            date_element = block.find('div', class_='im_log_date').find('a', class_='im_date_link')
            message_date = date_element.text.strip() if date_element else None
            return message_date
        except Exception as e:
            print(f'Ошибка при извлечении message_date: {e}')
            return None

    def get_message(self, block):
        try:
            message_text = ''.join([str(item) for item in block.contents if isinstance(item, str)])
            message_text = message_text.strip()
            return message_text
        except Exception as e:
            print(f'Ошибка при получении сообщения: {e}')
            return None

    def get_attachment_links(self, block): 
        try: 
            gallery_attachments = block.find_all('div', class_='gallery attachment')
            attachment_links = [a['href'] for gallery_attachment in gallery_attachments for a in gallery_attachment.find_all('a', class_='download_photo_type')]
            return attachment_links
        except Exception as e:
            print(f'Ошибка при получении сообщения: {e}')
            return []

class DetailsChat(): 
    def __init__(self):
        super().__init__()

    def details(self, file_path):
        return {
            "chat_id": self._get_last_folder(file_path),  
            "file_chat": str(file_path)
        }
    
    @staticmethod
    def _get_last_folder(path):
        folder_name = os.path.basename(os.path.dirname(path))
        match = re.search(r'\(id(\d+)\)', folder_name)
        if match:
            return match.group(1)
        else:
            return None


class MessageProcessor(MessageExtractor):
    def __init__(self):
        super().__init__()

    def process_block(self, block):
        try:
            author_block = self.get_author_blocks(block)
            author_name = self.get_name(author_block)
            href_value = author_block.find('a', class_='mem_link')['href']
            author_link = self.get_user_id(href_value)
            message_text = self.get_message(author_block)
            message_date = self.get_message_date(block)
            attachment_links = self.get_attachment_links(block)
            # print(f'Имя: {author_name}\nСсылка: {author_link}\nСообщение: {message_text}\n\Дата: {message_date}\n{attachment_links}\n')
            return {
                "author_name": author_name,
                "author_link": author_link,
                "message_text": message_text,
                "message_date": message_date,
                "attachment_links": attachment_links
            }
        except Exception as e:
            print(f'Ошибка при обработке блока: {e}')

class MessageFileProcessor(MessageProcessor):
    def __init__(self):
        super().__init__()
        self.details = {}  
        self.for_append = []
        self.id_msg = 1

    def process_rar_file(self, rar_file, output_dir):
        try:
            rf = rarfile.RarFile(rar_file)
            rf.extractall(output_dir)
        except Exception as e:
            print(f'Ошибка при разархивации файла {rar_file}: {e}')

    def process_all_html_files(self, rar_file, output_dir):
        # Создаем временную папку для извлечения содержимого архива
        temp_dir = tempfile.mkdtemp()

        # Распаковываем архив
        self.process_rar_file(rar_file, temp_dir)

        # Получаем список всех файлов с расширением 'htm' во всех подкаталогах временной папки
        files = glob.glob(os.path.join(temp_dir, '**', '*.htm*'), recursive=True)

        util = MessageParser()
        sorted_files = sorted(files, key=lambda x: (os.path.dirname(x), util.extract_number(x)))

        # Используем ThreadPoolExecutor для многопоточной обработки файлов
        max_workers = min(256, (os.cpu_count() or 1) * 24)  # Ограничение до 32 потоков
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.process_file, file_path): file_path for file_path in sorted_files}

            for future in tqdm(as_completed(futures), total=len(sorted_files), desc="Processing files", unit="file"):
                file_path = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f'Ошибка при обработке файла {file_path}: {e}')

        # Удаляем временную папку после использования
        shutil.rmtree(temp_dir)

        return self.for_append

    def process_file(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()

                details_chat = DetailsChat()
                self.details.update(details_chat.details(file_path))

                soup = BeautifulSoup(content, 'html.parser')
                im_in_blocks = self.get_im_in_blocks(soup)
                for block in im_in_blocks:
                    self.id_msg = self.id_msg + 1
                    details_copy = self.details.copy()
                    details_copy.update({'id': self.id_msg})
                    details_copy.update(self.process_block(block))
                    self.for_append.append(details_copy)
        except Exception as e:
            print(f'Ошибка при обработке файла {file_path}: {e}')

class MessageDatabase:
    def __init__(self, db_name, table_name):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.table_name = table_name
        self.create_table()

    def create_table(self):
        self.cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {self.table_name} (
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

    def insert_data(self, json_data):
        for item in json_data:
            self.cursor.execute(f'''
                INSERT INTO {self.table_name} (
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
        self.conn.commit()
        self.conn.close()
