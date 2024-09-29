import requests
import os
import re
from bs4 import BeautifulSoup

def extract_js_libraries(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    scripts = soup.find_all('script', src=True)
    links = soup.find_all('link', rel='stylesheet', href=True)
    
    urls = []
    for script in scripts:
        if script['src'].startswith(('http://', 'https://')):
            urls.append(script['src'])
    
    for link in links:
        if link['href'].startswith(('http://', 'https://')):
            urls.append(link['href'])
    
    return urls

def download_libraries():
    forend_dir = '../forend'
    output_dir = '../forend/libs'
    os.makedirs(output_dir, exist_ok=True)

    for filename in os.listdir(forend_dir):
        if filename.endswith('.html'):
            with open(os.path.join(forend_dir, filename), 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            urls = extract_js_libraries(html_content)
            
            for url in urls:
                filename = url.split('/')[-1]
                if '?' in filename:
                    filename = filename.split('?')[0]
                
                response = requests.get(url)
                with open(os.path.join(output_dir, filename), 'wb') as f:
                    f.write(response.content)
                print(f"已下载: {filename}")

    print(f"所有文件已下载到 '{output_dir}' 文件夹")

if __name__ == "__main__":
    download_libraries()
