# 面向企业 IT 与网络运维的 RAG 系统

本项目提供一套默认只读的网络运维知识检索与辅助分析系统，支持带来源引用的查询、配置差异比较、索引版本管理、REST API、Streamlit 控制台和受限 MCP stdio 入口。

系统通过 profile 组合不同的存储与检索实现：

- demo-lite：Chroma + SQLite FTS5 + SQLite，适合快速启动。
- local-milvus：Milvus + BM25 + PostgreSQL，适合完整本地运行。
- test：内存实现，用于自动化测试。
- cloud-milvus：外部 Milvus/PostgreSQL 环境的配置档案。

项目不提供设备配置写入或变更执行能力，运行时以检索证据、只读上下文和可追溯结果为主。

## 快速开始

### 完整本地运行

完整部署需要 Python 3.11、uv、Docker Desktop/Docker Engine，以及 Embedding/LLM 服务配置：

~~~powershell
uv sync --all-groups --extra local-milvus
docker compose up -d
uv run --extra local-milvus netops-copilot index-build --profile local-milvus
uv run --extra local-milvus --with uvicorn python tools/run_local_milvus_api.py
~~~

另开一个终端启动 Streamlit：

~~~powershell
uv run --extra local-milvus python -m streamlit run tools/run_local_milvus_streamlit.py --server.port 8502
~~~

- API 文档：http://127.0.0.1:8000/docs
- 就绪检查：http://127.0.0.1:8000/health/ready
- Streamlit：http://127.0.0.1:8502

### 快速运行

不启动 Docker 时，可以使用 demo-lite：

~~~powershell
uv sync --all-groups --extra demo-index
uv run --extra demo-index netops-copilot demo-lite
uv run --extra demo-index netops-copilot index-build --profile demo-lite
uv run --extra demo-index --with uvicorn python tools/run_demo_api.py
~~~

部署、环境变量、索引构建、API 调用、Streamlit 使用、MCP 和测试命令见[《部署与操作手册》](部署与操作手册.md)。

## 系统架构

~~~text
数据源与知识文档
        │
        ▼
解析 → 规范化 → 敏感字段处理 → 分块 → 版本化索引
        │                         │
        │                         ├─ Dense：Milvus / Chroma
        │                         └─ Lexical：BM25 / SQLite FTS5
        ▼
授权过滤 → 混合召回 → 重排 → 证据引用 → 查询结果/回答
        │                       │
        ├─ FastAPI REST           ├─ Streamlit
        ├─ CLI                    └─ MCP stdio
        └─ PostgreSQL/SQLite 元数据与追踪
~~~

代码按层组织：

- domain/：库存、知识、配置、观察和事故等领域模型。
- application/：检索、问答、索引、摄取、授权、证据、降级、追踪和评测用例。
- infrastructure/：Milvus、Chroma、PostgreSQL、SQLite、模型服务和只读连接器适配器。
- interfaces/：CLI、FastAPI、Streamlit 和 MCP 传输层。
- config/profiles/：运行时依赖和 provider 组合。
- datasets/demo/：索引输入、知识文档、库存、拓扑、观察、工单和评测集合。

索引采用先构建、后校验、再激活的版本流程。Dense 和 Lexical 两类索引的数量与样本回读均通过后，才会切换活动索引；构建失败不会让不完整版本进入查询路径。

## 可实现功能

- 混合、语义、关键词检索及确定性重排。
- 基于来源定位、分块和摘要的证据引用。
- 按站点、设备、厂商、系统版本和安全级别过滤。
- 配置快照差异比较和风险提示。
- 事故场景回放、设备上下文读取、来源列表和追踪摘要。
- REST API 与自动生成的 Swagger UI。
- Streamlit 运维控制台，包含知识检索、配置比较和评测页面。
- MCP stdio 受限工具注册，只暴露命名的业务操作。
- Embedding/LLM 服务不可用时的状态识别和降级提示。
- 只读连接器、授权过滤、敏感字段处理和安全错误响应。

## 接口入口

启动 API 后可以访问：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | /health/live | 进程存活检查 |
| GET | /health/ready | 依赖与活动索引检查 |
| POST | /api/v1/query | 知识检索 |
| POST | /api/v1/incidents/diagnose | 事故研判 |
| POST | /api/v1/configs/diff | 配置差异比较 |
| GET | /api/v1/devices/{device_id}/context | 设备上下文 |
| GET | /api/v1/sources | 知识来源 |
| POST | /api/v1/ingestion | 数据摄取请求 |
| GET | /api/v1/evaluation | 评测摘要 |
| GET | /api/v1/traces/{trace_id} | 调用追踪 |

以 /docs 页面中的 OpenAPI 定义和实际运行 profile 的就绪状态为准。

## 开发检查

~~~powershell
uv run python -m unittest discover -s tests
uv run ruff check src tests tools
uv run python tools/check_architecture.py
uv run python tools/check_repository_assets.py
uv run python tools/generate_demo_dataset.py --check
~~~

## 许可证与外部服务

运行所需的 Python 包、Docker 镜像和外部模型服务分别受其各自许可证与服务条款约束。部署到其他环境前，请确认依赖版本、镜像来源、模型服务配额和数据访问权限满足使用要求。
