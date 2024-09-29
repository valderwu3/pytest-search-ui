from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from meilisearch import Client
from pydantic import BaseModel
import uvicorn

app = FastAPI()

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

class SearchQuery(BaseModel):
    query: str

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
