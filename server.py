from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from meilisearch import Client
from pydantic import BaseModel
import uvicorn
import os

app = FastAPI()

# 获取当前文件的目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化 Meilisearch 客户端
meili_client = Client('http://localhost:7700', 'your_master_key')
index = meili_client.index('test_cases')

# 修改静态文件目录的设置
app.mount("/static", StaticFiles(directory=os.path.join(current_dir, "static")), name="static")
app.mount("/node_modules", StaticFiles(directory=os.path.join(current_dir, "node_modules")), name="node_modules")

# 设置模板目录
templates = Jinja2Templates(directory=os.path.join(current_dir, "templates"))

class SearchQuery(BaseModel):
    query: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/search")
async def search(search_query: SearchQuery):
    results = index.search(search_query.query)
    return results

@app.get("/projects")
async def get_projects():
    # 获取所有文档
    documents = index.get_documents({'limit': 1000})  # 假设文档数量不超过1000
    # 提取所有不重复的项目名称
    project_names = list(set(doc['project_name'] for doc in documents['results'] if 'project_name' in doc))
    return {"projects": project_names}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
