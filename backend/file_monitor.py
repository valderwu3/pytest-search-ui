import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, DirModifiedEvent
import ast
import sqlite3
import logging
import threading
import hashlib
from meilisearch import Client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 添加全局开关
# ！！！ 谨慎使用，设置为True,会删除所有数据 ！！！
RECREATE_TABLE = True

class TestCaseInfo:
    def __init__(self, project_name, project_description, case_name, case_description, file_path, case_code):
        self.project_name = project_name
        self.project_description = project_description
        self.case_name = case_name
        self.case_description = case_description
        self.file_path = file_path
        self.case_code = case_code

class TestFileHandler(FileSystemEventHandler):
    def __init__(self, db_path, meili_client, root_path):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.meili_client = meili_client
        self.index = self.meili_client.index('test_cases')
        self.root_path = root_path

    def on_created(self, event):
        if event.is_directory:
            return
        if self._is_valid_test_file(event.src_path):
            self._update_file_info(event.src_path)
            self.print_database_content()

    def on_modified(self, event):
        if isinstance(event, DirModifiedEvent):
            self._handle_directory_change(event.src_path)
        elif self._is_valid_test_file(event.src_path):
            self._update_file_info(event.src_path)
            self.print_database_content()

    def on_deleted(self, event):
        if event.is_directory:
            return
        if self._is_valid_test_file(event.src_path):
            self.delete_file_info(event.src_path)
            self.print_database_content()

    def on_moved(self, event):
        if event.is_directory:
            self._handle_directory_change(event.dest_path)
        elif self._is_valid_test_file(event.src_path):
            self.delete_file_info(event.src_path)
            self._update_file_info(event.dest_path)
            self.print_database_content()

    def _handle_directory_change(self, dir_path):
        logging.info(f"检测到目录变化: {dir_path}")
        self._rescan_directory(self.root_path)

    def _rescan_directory(self, path):
        logging.info("开始重新扫描目录...")
        self._clear_all_data()
        scan_existing_files(path, self)
        logging.info("目录重新扫描完成")

    def _clear_all_data(self):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM test_cases')
            conn.commit()
            conn.close()
            self.index.delete_all_documents()
        logging.info("已清空所有数据")

    def _is_valid_test_file(self, file_path):
        file_name = os.path.basename(file_path)
        return file_name.startswith('test_') and file_name.endswith('.py')

    def _retry_process_file(self, file_path, max_retries=5, delay=1):
        for attempt in range(max_retries):
            try:
                self._update_file_info(file_path)
                return
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    logging.error(f"无法访问文件 {file_path}，已达到最大重试次数")

    def process_file(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                file_content = file.read()
                tree = ast.parse(file_content)
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='gbk') as file:
                file_content = file.read()
                tree = ast.parse(file_content)
        except Exception as e:
            logging.error(f"解析文件 {file_path} 时发生错误: {str(e)}")
            return []

        test_cases = []
        print("process_file", file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                project_name = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
                class_name = node.name
                project_description = ast.get_docstring(node)

                for sub_node in node.body:
                    if isinstance(sub_node, ast.FunctionDef) and sub_node.name.startswith('test_'):
                        case_name = sub_node.name
                        case_description = ast.get_docstring(sub_node)
                        case_code = ast.get_source_segment(file_content, sub_node)
                        test_case = TestCaseInfo(project_name, project_description, case_name, case_description, file_path, case_code)
                        test_cases.append(test_case)
        print("test_cases", test_cases)
        return test_cases

    def _update_file_info(self, file_path):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            try:
                # 开始事务
                cursor.execute('BEGIN TRANSACTION')
                
                # 删除当前文件所有用例
                cursor.execute('DELETE FROM test_cases WHERE file_path = ?', (file_path,))
                
                # 从Meilisearch中删除
                normalized_file_path = file_path.replace('\\', '/')
                self.index.delete_documents(filter=f'file_path="{normalized_file_path}"')
                
                # 获取并添加当前文件的所有用例
                current_test_cases = self.process_file(file_path)
                for test_case in current_test_cases:
                    cursor.execute('''
                        INSERT INTO test_cases 
                        (project_name, project_description, case_name, case_description, file_path, case_code) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (test_case.project_name, test_case.project_description, test_case.case_name, test_case.case_description, test_case.file_path, test_case.case_code))
                    
                    # 同步到Meilisearch
                    id_string = f"{normalized_file_path}_{test_case.case_name}"
                    id_hash = hashlib.md5(id_string.encode()).hexdigest()
                    document = {
                        'id': id_hash,
                        'project_name': test_case.project_name,
                        'project_description': test_case.project_description,
                        'case_name': test_case.case_name,
                        'case_description': test_case.case_description,
                        'file_path': normalized_file_path,
                        'case_code': test_case.case_code,
                    }
                    self.index.add_documents([document])
                
                # 提交事务
                conn.commit()
                logging.info(f"已更新文件 {file_path} 的测试用例信息")
            
            except Exception as e:
                # 发生错误时回滚
                conn.rollback()
                logging.error(f"更新文件 {file_path} 的测试用例信息时发生错误: {str(e)}")
            
            finally:
                conn.close()

    def delete_file_info(self, file_path):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM test_cases WHERE file_path = ?', (file_path,))
            conn.commit()
            conn.close()

            # 从Meilisearch中删除
            normalized_file_path = file_path.replace('\\', '/')
            self.index.delete_documents(filter=f'file_path="{normalized_file_path}"')
            logging.info(f"已从数据库和Meilisearch中删除文件 {normalized_file_path} 的相关数据")

    def print_database_content(self):
        print("print_database_content")
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM test_cases')
            rows = cursor.fetchall()
            logging.info("数据库当前内容：")
            for row in rows:
                logging.info(f"项目名称: {row[1]}, 项目描述: {row[2]}, 用例名称: {row[3]}, 用例描述: {row[4]}, 文件路径: {row[5]}, 用例代码: {row[6][:50]}...")
            conn.close()

def setup_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if RECREATE_TABLE:
        cursor.execute("DROP TABLE IF EXISTS test_cases")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            project_description TEXT,
            case_name TEXT,
            case_description TEXT,
            file_path TEXT,
            case_code TEXT,
            UNIQUE(project_name, case_name, file_path)
        )
    ''')
    conn.commit()
    conn.close()

def scan_existing_files(path, event_handler):
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.startswith('test_') and file.endswith('.py'):
                file_path = os.path.join(root, file)
                print("scan_existing_files", file_path)
                event_handler._update_file_info(file_path)

def monitor_directory(path):
    db_path = 'test_cases.db'
    setup_database(db_path)
    
    # 初始化Meilisearch客户端
    meili_client = Client('http://localhost:7700', 'your_master_key')
    
    # 配置Meilisearch索引
    index = meili_client.index('test_cases')
    index.update_filterable_attributes(['case_name', 'file_path'])
    
    # 如果RECREATE_TABLE为True，则删除Meilisearch中的所有文档
    if RECREATE_TABLE:
        index.delete_all_documents()
        logging.info("已清空Meilisearch索引中的所有文档")
    
    event_handler = TestFileHandler(db_path, meili_client, path)
    
    # 首次启动时进行全面扫描
    logging.info("开始进行初始文件扫描...")
    scan_existing_files(path, event_handler)
    event_handler.print_database_content()
    logging.info("初始文件扫描完成")
    
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()

    logging.info(f"开始监控目录: {path}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    monitor_directory("../automation_code")
