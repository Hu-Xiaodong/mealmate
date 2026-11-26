# MealMate

MealMate 是帮助人们决定这一餐吃什么的工具：用附近真实饭帖、热榜和 AI 选餐，把“随便看看”缩小到“就吃这个”，吃完还能把这一餐发布出去，帮助下一个人做决定。


## 核心功能

### 1. 附近、首页与热榜

- 首页展示全部已发布饭帖，按发布时间倒序，新发布的排在最前，支持“全部 / 附近”切换；热榜按有效赞排序，每天最多 20 条，业务日按 `Asia/Shanghai` 自然日计算。
- 饭帖详情展示图集、菜名、评价、作者和来源；外卖展示店家名称，到店展示店铺地址，有作者做法时直接展开。


### 2. 发布自己的这一餐

- 来源三选一：到店吃、外卖、自己做。到店和外卖是常见来源；自己做是补充
- 到店来源必须填店铺地址；外卖来源必须填店家名称；自己做可以补充完整的食材和步骤，作为“作者做法”优先展示给其他饭友。


### 3. 问 AI：能聊、能推荐、还能接着追问

- 既能回答做饭方法、食材搭配、时间安排等一般问题，也能在需要选菜时从平台已发布菜谱里推荐，最多 3 道；不直接推荐附近商家，“选店”仍由附近饭帖和热榜承担。
- 支持多轮对话：服务端按 30 分钟会话保存历史，提示词只带最近 8 条；历史达到模型上下文窗口 60% 时把窗口外旧消息压缩成摘要，压缩失败回滚，窗口配置超限自动砍半重试并写醒目日志。游客记录保存在手机本地（7 天），登录后按消息编号合并上云；登录用户本地与云端均保留 30 天；提供“新聊天”，不提供删除历史入口，超期由每日清理任务删除。
- 支持流式输出：服务端按 SSE（服务器发送事件）边生成边推送，App 逐字显示，首字出现更快；流式失败且一个字都没收到时自动退回普通接口。
- 只允许推荐平台真实菜谱，编号、时间、器具、食材和忌口仍由后端二次校验；模型不可用时回退本地规则，不编造内容。
- 对话和嵌入两类模型分开配置：聊天只选用途为 `chat` 的供应商，嵌入只选 `embedding`，不会再拿嵌入模型去试聊天。
- 本地模型可直接接 Ollama，例如对话用 `qwen2.5:14b`、嵌入用 `bge-m3`，地址填 `http://127.0.0.1:11434/v1`。


### 4. 菜谱

- 按推荐、15 分钟、一锅、少食材等分类浏览，服务于有厨房条件时“想自己做”的需求，不是决策的主路径。
- 菜谱包含用料、步骤、总耗时、所需厨具和前置条件（例如“需要提前煮好米饭”）。
- 作者做法与平台参考做法严格区分：作者提供食材和步骤时优先展示作者做法；否则展示明确关联或严格同名的平台菜谱，并标注“来自平台菜谱·参考做法”。

### 5. 管理后台

- 数据看板：内容、用户、互动与 AI 调用统计。
- 饭帖审核：通过、拒绝、下架、批量审核、批量软删除（需独立删除权限并填写原因），拒绝、下架、删除必须填原因。
- 菜谱与口味标签：菜谱新增、编辑、单个下架，以及勾选后的批量上架、批量下架、批量删除；删除为物理删除，被饭帖引用的菜谱会跳过并提示原因，同时清理分类关联与用户收藏；口味标签启用、排序、删除限制。
- 模型配置与调用日志：对话/嵌入两类供应商分开配置，同一用途同时只能启用一个模型，调用时固定使用启用中的那个，启用新模型会自动停用同类型旧模型；对话模型新增“上下文窗口”与“输入/输出单价”（美元/千 token），窗口用于判断历史压缩阈值和长度兜底，单价用于成本统计；嵌入供应商必须支持 `/embeddings` 且输出 1024 维，“测试连接”会按用途调用对应接口；每次调用记录耗时、状态、Token、成本、提示词名称与版本、来源与执行明细，调用日志保留 180 天。
- AI 观测与提示词（本地优先）：提示词版本、调用指标、人工评分都保存在自己的 PostgreSQL，不依赖外部服务。后台“提示词管理”可发布新版本、查看发布人/变更说明/历史版本，未配置 Langfuse 也能正常使用；“AI 观测”默认聚合本地调用日志与评分，展示调用量、错误率、平均/P95 延迟、Token、成本、评分分布、每日趋势与按提示词版本对比。Langfuse 为可选增强：配置后额外上报调用链、Token、成本与错误级别，发布提示词时尽力镜像，AI 观测可切换为 Langfuse 数据源；镜像或上报失败不影响本地功能与问答。
- 知识库：上传 `.md` / `.txt` 并可选携带 Markdown 引用的图片，先切片、运营确认后再建立索引；按固定模板编写的菜谱文档可点「生成菜谱」或勾选后批量生成草稿，运营在菜谱管理里核对、补封面后发布；支持一次多选、整个文件夹或 ZIP 压缩包批量导入，后台逐篇解析并提供批次进度、失败清单与单文件重试；上传前会读取 Markdown 检测本地图片引用，未选择对应图片时给出提示并二次确认；可查看切片、重建、切换索引版本，并用“检索测试”查看相似度排名。
- 用户管理：列表、详情（含发布记录）、封禁、解封；封禁会撤销该用户全部未注销会话。
- 管理员与角色、审计日志：权限点服务端校验；审计日志只追加，不修改、不删除，操作与日志在同一个数据库事务中提交。
- 列表分页：饭帖审核、菜谱、用户、审计日志、AI 调用日志、用户详情发布记录统一使用页码分页，显示总数、每页条数、页码与跳页；筛选或修改每页条数自动回到第 1 页。

## 技术栈

| 层 | 选型 | 原因 |
| --- | --- | --- |
| 后端 | Python 3.12 + FastAPI + Pydantic v2 | 与 PRD 的强类型接口契约贴合，自动生成 OpenAPI，异步 IO 适合图片与配额逻辑 |
| 数据 | PostgreSQL 18 + pgvector（本地与生产）/ SQLite（仅自动化测试与未配置时的兜底） | 同一套 SQLAlchemy 2.0 async 模型；知识库向量在 PostgreSQL 用 `vector(1024)` 与 HNSW 索引，SQLite 退化为 JSON 文本并由 Python 计算余弦 |
| 缓存 | Redis 7（可选） | 热榜短缓存与配额计数，未配置时自动降级为数据库实现 |
| Android / iOS / Web | Flutter 3 | 一套 Dart 代码同时覆盖两端，Web 用于快速预览与演示 |
| 微信小程序 / H5 | uni-app + Vue 3 + TypeScript + Vite + Pinia | 小程序与 H5 共享一套代码，同时保留独立的发布节奏 |
| 管理后台 | Vue 3 + TypeScript + Element Plus + Pinia | 内部系统以表格、表单和权限控制为主，组件库成熟；独立工程不打包进用户端 |
| 媒体 | 本地磁盘 + 可替换存储适配器 | 本地开发简单，生产可平滑替换为 OSS/CDN |
| AI | LangChain 调用层 + 自研模型网关 + RAG 知识库 | LangChain 统一不同厂商的 OpenAI 兼容调用；网关层负责模型开关（同一用途只启用一个）、严格 JSON 与菜谱编号校验、可暂停的每日配额、调用日志和本地规则回退；知识库负责切片、1024 维嵌入与余弦检索，为后续问答提供可引用资料；嵌入模型不可用时检索自动降级为关键词匹配并提示 |
| AI 可观测 | 本地 PostgreSQL（默认）+ Langfuse（可选，直接调用 HTTP 接口） | 提示词版本、调用指标、人工评分以本地数据库为准，无外部依赖也能完整使用；Langfuse 只作可选增强，记录调用链并作为第二数据源，私钥留在服务端、页面自研；未配置或不可用时自动跳过，不影响问答 |
| 部署 | Docker Compose | API、PostgreSQL、Redis 一条命令起齐 |

两套客户端是刻意分开的：Flutter 负责原生体验，uni-app 负责微信生态与 H5 分享，二者共用同一套 HTTP 契约。

## 目录结构

```
docs/                    PRD、待确认项与工程验收稿
mealmate/               移动端交互原型（MealMate）
server/                  FastAPI 后端
  app/api/               路由与依赖注入
  app/services/          业务服务（认证、内容流、热榜、菜谱、互动、媒体、AI、知识库）
  app/db/                模型、会话与演示数据
  migrations/            手写数据库迁移脚本
  scripts/               数据导入试运行等运维脚本
  tests/                 API 级 pytest
app_mini/                uni-app（微信小程序 + H5）
app_admin/               管理后台（Vue 3 + Element Plus）
app_flutter/             Flutter（Android + iOS + Web）
docker-compose.yml       API + PostgreSQL + Redis 生产编排
```

## 本地启动

### 后端

```powershell
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

- 健康检查：`GET http://127.0.0.1:8000/healthz`
- 接口文档：`http://127.0.0.1:8000/docs`
- 开发环境验证码固定为 `123456`；获取验证码接口也会在 `devCode` 字段返回，客户端会自动填入。
- 首次启动会写入演示饭帖与菜谱（`SEED_DEMO_DATA=true`），可在首页、热榜与菜谱页直接联调。

### 小程序 / H5

```powershell
cd app_mini
npm install
npm run dev:h5          # 浏览器预览
npm run dev:mp-weixin   # 生成 dist/dev/mp-weixin，用微信开发者工具导入
npm run build:h5
npm run build:mp-weixin
```

接口地址默认 `http://127.0.0.1:8000`，可通过 `VITE_API_BASE` 覆盖。微信小程序正式发布前需在后台配置已备案的 HTTPS 合法域名。

### 管理后台

```powershell
cd app_admin
npm install
npm run dev      # http://127.0.0.1:5174
npm run build    # 类型检查并产出 dist
```

开发服务器会把 `/api` 与 `/media` 代理到 `http://127.0.0.1:8000`，所以不需要单独配置跨域。

- 首次启动时，后端从 `server/.env` 的 `ADMIN_INITIAL_USERNAME` 与 `ADMIN_INITIAL_PASSWORD` 创建超级管理员。本地示例为 `admin / Admin@123456`，只在本地使用，生产必须改成强密码。
- 未配置 `ADMIN_INITIAL_PASSWORD` 时不会创建任何管理员账号，代码中也没有默认密码。
- 页面：数据看板、饭帖审核（含批量）、菜谱管理、口味标签、模型配置、AI 调用日志、AI 观测、提示词管理、知识库、用户管理、管理员与角色、审计日志。
- 知识库使用前先在“模型配置”新增一个用途为“嵌入模型”的供应商（维度固定 1024），再上传 `.md` / `.txt` 文档；单篇上传时可以同时选择 Markdown 引用的 JPG/PNG/WebP 图片，后端按文件名匹配并改写为 `/media/...`，切片预览会直接显示图片。批量导入支持多选、文件夹与 ZIP，文件夹内图片按“同目录优先”匹配，未被引用的图片会计入统计并在批次详情里列出相对路径清单，便于排查文件名写错或多余素材；解析在后台执行，批次进度里能看到失败原因并单独重试。没有可用嵌入供应商时，文档会停在“待建索引”，建立索引时显示失败原因。文档列表支持勾选后批量删除。文档按固定菜谱模板编写时（一级标题 + 必备原料和工具 / 计算 / 操作 / 附加内容），点文档行的「生成菜谱」或勾选后批量生成，会得到一条状态为“草稿”的菜谱；到“菜谱管理”把状态筛选为“草稿”即可核对、补封面并发布，已发布的菜谱不会被覆盖。上传本身只存资料与切片，不会自动创建菜谱。文档列表按页码分页，每页可选 20 / 50 / 100 条。勾选文档后可批量重新切片、批量生成菜谱草稿、批量建立索引，逐篇执行并列出未完成项；这三个批量操作一次最多 20 篇。
- 登录状态 1 天失效；同一用户名与来源地址 10 分钟内失败 5 次，锁定 15 分钟。

### Flutter

```powershell
cd app_flutter
flutter pub get
flutter run --dart-define=API_BASE=http://10.0.2.2:8000
```

- Android 模拟器访问宿主机 API 用 `10.0.2.2`；iOS 模拟器用 `127.0.0.1`；真机用局域网 IP。
- 浏览器预览：`flutter run -d chrome --dart-define=API_BASE=http://127.0.0.1:8000`。
- Android 需要 `android.permission.INTERNET`，iOS 调试直连 HTTP 需在 Info.plist 放行 ATS。
- 本机已把 Flutter SDK 放在 `E:\tools\flutter`（ASCII 路径，避免 Gradle 读取中文路径时乱码）。未加入 PATH 时先设置：

```powershell
$env:PUB_CACHE='E:\项目\mealmate\tools\pub-cache'
$env:APPDATA='E:\项目\mealmate\tools\appdata'
$env:USERPROFILE='E:\项目\mealmate\tools\home'
$env:HOME='E:\项目\mealmate\tools\home'
& 'E:\tools\flutter\bin\flutter' pub get
```

## 测试与检查

```powershell
cd server
pytest
ruff check .
```

当前 115 条测试覆盖登录限流与错误码、分页游标、附近筛选、首页历史内容倒序、热榜排序、菜谱与作者做法优先、点赞/收藏、发布幂等、图片校验、AI 游客配额、管理后台登录锁定、角色权限、审核状态流转、下架缓存失效、批量删除与删除权限、封禁撤销会话与审计日志时间筛选、HowToCook 解析与导入模型，以及知识库切片与重叠、上传去重、图片保存与地址改写、非法图片拒绝、索引版本切换与重建、缺少嵌入供应商的失败分支、嵌入不可用时的关键词降级、检索排序与权限、AI 会话复用与 30 分钟新会话、历史压缩成功/失败/砍半兜底、Redis 快照复用、登录同步幂等、每日清理与删除账号保留日志，以及 Langfuse 调用事件与成本、指标解析、本地提示词发布与读取优先级、提示词变量优先级与缺失拦截、专属变量草稿语义、变量删除保护、版本回滚恢复专属变量、本地指标聚合、评分本地保存、模型单价字段回显。

## 生产部署

```powershell
# 根目录
Copy-Item .env.example .env
# 编辑 .env，至少替换 SECRET_KEY 与 POSTGRES_PASSWORD
docker compose up -d --build
```

生产配置由 Compose 强制为 `APP_ENV=prod`，因此：

- 固定验证码 `ALLOW_DEV_AUTH_CODE` 与演示数据 `SEED_DEMO_DATA` 会在启动时被配置校验直接拒绝；
- 新发布默认 `AUTO_PUBLISH_POSTS=false`，进入 `pending_review`；
- 媒体写入 `mealmate_media` 卷，PostgreSQL 数据写入 `mealmate_pgdata` 卷；
- 必须在根目录 `.env` 设置 `ADMIN_INITIAL_PASSWORD`，首次启动会创建超级管理员；创建完成后建议把该变量移除或改成空值，避免每次启动重复校验初始密码。

管理后台是独立前端工程，生产环境执行 `npm run build` 后，把 `app_admin/dist` 交给 Nginx 等静态服务器托管，并把 `/api` 反向代理到后端。后台入口建议只允许公司内网或虚拟专用网络访问。

对外服务建议在前置 Nginx/网关终止 TLS，并把 `PUBLIC_BASE_URL`、`CORS_ORIGINS` 改成线上域名。

AI 数据清理需要每天执行一次，建议由宿主机 cron 或 Windows 任务计划程序调用：

```powershell
cd server
python -m app.jobs.cleanup
```

Langfuse 为可选增强，不填写也能使用完整的提示词管理、本地指标与人工评分。生产环境需要时可在 `server/.env` 填写：

```dotenv
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

不填写时：调用事件不上报，发布提示词只保存在本地数据库，“AI 观测”默认展示本地统计且不显示 Langfuse 切换项；AI 问答仍按“本地 production → 代码默认值”正常读取提示词。填写后发布提示词会尽力镜像到 Langfuse，镜像失败只提示、不影响本地生效。涉及真实用户对话时，建议自建或只上报脱敏指标。

它会删除 30 天没有活动的会话与消息、所属用户已不存在的孤儿会话，以及 180 天前的 AI 调用日志与明细。Docker 部署可以写成 `docker compose exec api python -m app.jobs.cleanup`。

## 接口速览

统一响应：`{ requestId, code, message, data }`，`code=0` 表示成功；分页为 `{ items, nextCursor, hasMore }`。

| 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/sms-codes` | 发送登录验证码 | 否 |
| POST | `/api/v1/auth/login` | 验证码登录/注册 | 否 |
| GET | `/api/v1/auth/me` | 当前账号 | 是 |
| POST | `/api/v1/auth/logout` | 注销会话 | 是 |
| GET | `/api/v1/feed` | 已发布内容流（按发布时间倒序），支持 `filter=near` | 可选 |
| GET | `/api/v1/rank/today` | 今日热榜，最多 20 条 | 可选 |
| GET | `/api/v1/recipes` | 菜谱分类列表 | 可选 |
| GET | `/api/v1/recipes/{id}` | 菜谱详情 | 可选 |
| GET | `/api/v1/posts/{id}` | 饭帖详情 | 可选 |
| POST | `/api/v1/posts` | 发布饭帖，需 `Idempotency-Key` | 是 |
| PUT | `/api/v1/posts/{id}/like` | 点赞/取消点赞 | 是 |
| PUT | `/api/v1/favorites` | 收藏/取消收藏（饭帖或菜谱） | 是 |
| GET | `/api/v1/me/posts` | 我的发布 | 是 |
| GET | `/api/v1/me/favorites` | 我的收藏 | 是 |
| POST | `/api/v1/media` | 上传图片（multipart） | 是 |
| POST | `/api/v1/ai/chat` | 上下文选餐、一般做饭问答与多轮对话，游客也可用 | 可选 |
| POST | `/api/v1/ai/chat/stream` | 同一套问答能力，按 SSE 流式返回文字，最后再给推荐卡片 | 可选 |
| POST | `/api/v1/ai/conversations/sync` | 登录后把手机本地 AI 对话合并上云，按客户端编号幂等去重 | 是 |

### 管理后台接口（前缀 `/api/v1/admin`）

| 方法 | 路径 | 说明 | 权限点 |
| --- | --- | --- | --- |
| POST | `/auth/login` | 管理员用户名密码登录 | 无 |
| POST | `/auth/logout` | 注销当前会话 | 已登录 |
| GET | `/auth/me` | 当前管理员与权限点 | 已登录 |
| GET | `/posts` | 饭帖列表，可按状态筛选，页码分页（`page` / `pageSize`） | `post.review` |
| GET | `/posts/{id}` | 饭帖详情 | `post.review` |
| POST | `/posts/{id}/approve` | 审核通过 | `post.review` |
| POST | `/posts/{id}/reject` | 审核拒绝，必须填原因 | `post.review` |
| POST | `/posts/{id}/unpublish` | 下架已公开饭帖，必须填原因 | `post.unpublish` |
| POST | `/posts/batch-review` | 批量通过/拒绝，逐条返回结果 | `post.review` |
| POST | `/posts/batch-delete` | 批量软删除饭帖，必须填原因 | `post.delete` |
| GET | `/recipes` | 菜谱列表，支持关键词、状态筛选与页码分页 | `recipe.manage` |
| GET | `/recipes/{id}` | 菜谱详情 | `recipe.manage` |
| POST | `/recipes` | 新增菜谱，可直接发布或存草稿 | `recipe.manage` |
| PUT | `/recipes/{id}` | 编辑菜谱 | `recipe.manage` |
| POST | `/recipes/{id}/archive` | 单个下架（软下架），历史饭帖关联保留 | `recipe.manage` |
| POST | `/recipes/batch-publish` | 批量上架，已是上架状态的记为跳过 | `recipe.manage` |
| POST | `/recipes/batch-archive` | 批量下架，已是下架状态的记为跳过 | `recipe.manage` |
| POST | `/recipes/batch-delete` | 批量物理删除，被饭帖引用的菜谱跳过，一次最多 50 条 | `recipe.manage` |
| GET | `/users` | 用户列表与搜索，页码分页 | `user.read` |
| GET | `/users/{id}` | 用户详情 | `user.read` |
| POST | `/users/{id}/ban` | 封禁并撤销会话 | `user.ban` |
| POST | `/users/{id}/unban` | 解封 | `user.ban` |
| GET | `/audit-logs` | 审计日志，只读，页码分页 | `audit.read` |
| GET | `/ai-call-logs/{id}/scores` | 一次调用的人工评分列表 | `ai.log.read` |
| POST | `/ai-call-logs/{id}/scores` | 提交 1-5 分与评语，先存本地再尽力同步 Langfuse | `ai.eval.write` |
| GET | `/ai-metrics` | 本地指标：调用量、错误率、平均/P95 延迟、Token、成本、评分分布、趋势、按提示词版本对比 | `ai.log.read` |
| GET | `/prompts` | 本地提示词列表：带 `{{key}}` 的原文、变量替换后的预览、专属变量、线上版本与历史版本号 | `ai.log.read` |
| GET | `/prompts/{name}/versions` | 最近 20 个历史版本，含发布人、变更说明、专属变量快照与 Langfuse 版本 | `ai.log.read` |
| POST | `/prompts/{name}/preview` | 用编辑器正文和未保存的专属变量预览替换结果，返回缺失 Key 与取值来源 | `ai.log.read` |
| POST | `/prompts/{name}/publish` | 发布本地新版本、保存专属变量并把 production 指向它，随后尽力镜像 Langfuse | `ai.config.write` |
| POST | `/prompts/{name}/rollback` | 把指定历史版本的正文与专属变量一起恢复成新的线上版本 | `ai.config.write` |
| GET | `/prompt-variables` | 共用变量与专属变量列表，可按提示词筛选，含被引用提示词 | `ai.log.read` |
| POST | `/prompt-variables` | 新增或修改共用/专属变量，保存后立即清理提示词缓存 | `ai.config.write` |
| DELETE | `/prompt-variables/{id}` | 删除变量；会让已发布提示词缺值时返回 409 | `ai.config.write` |
| GET | `/langfuse/status` | Langfuse 配置与连接状态 | `ai.log.read` |
| GET | `/langfuse/metrics` | Langfuse 第二数据源指标（需已配置） | `ai.log.read` |
| GET | `/kb/documents` | 知识库文档列表，服务端分页（`page` / `pageSize`，返回 `total`），含待索引切片数量与参数 | `kb.document.manage` |
| POST | `/kb/documents/{id}/recipe-draft` | 按固定模板把文档解析成菜谱草稿（手动触发，已有草稿则更新，已发布菜谱不覆盖） | `kb.document.manage` |
| POST | `/kb/documents/batch-rechunk` | 批量重新切片，逐篇返回结果，一次最多 20 篇 | `kb.document.manage` |
| POST | `/kb/documents/batch-recipe-draft` | 批量生成菜谱草稿，已发布菜谱跳过 | `kb.document.manage` |
| POST | `/kb/documents/batch-index` | 批量建立索引，没有待索引切片的文档自动跳过 | `kb.document.manage` |
| POST | `/kb/import-batches` | 批量导入：多文件、整个文件夹或 ZIP 压缩包，后台逐篇解析切片 | `kb.document.manage` |
| GET | `/kb/import-batches/{id}` | 批次进度、每篇结果与失败清单 | `kb.document.manage` |
| POST | `/kb/import-batches/{id}/retry` | 只重试失败文件，已成功的文档不重复处理 | `kb.document.manage` |
| POST | `/kb/documents` | 上传 `.md` / `.txt` 与可选图片，只做解析与切片，等待建立索引 | `kb.document.manage` |
| GET | `/kb/documents/{id}` | 文档详情与状态 | `kb.document.manage` |
| POST | `/kb/documents/{id}/rechunk` | 按当前启用版本重新切片，替换待索引切片 | `kb.document.manage` |
| POST | `/kb/documents/{id}/index` | 把待索引切片建立成索引（生成向量） | `kb.document.manage` |
| DELETE | `/kb/documents/{id}` | 删除文档、已索引/待索引切片、原始文件与图片 | `kb.document.manage` |
| GET | `/kb/documents/{id}/chunks` | 切片分页；优先返回待索引切片 | `kb.document.manage` |
| GET | `/kb/index-versions` | 索引版本列表 | `kb.document.manage` |
| POST | `/kb/index-versions` | 新建索引版本（含切片长度与重叠） | `kb.document.manage` |
| POST | `/kb/index-versions/{id}/activate` | 启用版本，旧版本自动归档 | `kb.document.manage` |
| POST | `/kb/search-test` | 检索测试：返回片段、相似度与耗时 | `kb.search.test` |

## 关键业务约定

- 业务日按 `Asia/Shanghai` 自然日计算；热榜按有效赞降序、发布时间升序、ID 升序，最多 20 条。
- 点赞与收藏必须登录；登录前触发的操作会在登录成功后自动续做。
- 饭帖来源分 `self` / `takeaway` / `dine_in`，外卖必须填店家，到店必须填地址。
- 图片 1–9 张、单张不超过 5MB；服务端校验真实图片格式、去除 EXIF 并生成缩略图。
- 验证码 5 分钟有效、60 秒可重发、连续输错 5 次失效。
- AI 只引用平台真实菜谱 ID，硬性筛选条件为最长耗时、厨具、食材和忌口，支持一餐菜单组合；预算、人数等自然语言条件尚未结构化。游客每日 5 次、登录每日 20 次，可用 `AI_DAILY_LIMIT_ENABLED=false` 暂停限制（仍记录次数，App 隐藏剩余次数）。模型在后台“模型配置”维护，同一用途同时只启用一个，调用时使用启用中的那个；未启用或调用失败时回退本地规则推荐，不会伪造外部结果。
- AI 可观测以本地数据库为准：提示词版本存 `ai_prompt_versions`（版本不可修改，`production` 表示线上、`archived` 表示归档），提示词变量存 `ai_prompt_variables`（共用变量所有提示词可用，专属变量绑定单个提示词并随版本快照 `ai_prompt_versions.variables` 一起发布和回滚），调用日志记录提示词名称/版本/来源与调用时成本，指标直接聚合 `ai_call_logs` / `ai_call_scores`。Langfuse 是可选增强：三项配置为空时自动关闭，不产生网络请求；配置后调用事件先入内存队列再批量上报，发布提示词先本地提交再尽力镜像，失败只记日志。提示词运行时读取顺序为本地 production → Langfuse production → 代码默认值，缓存 5 分钟，发布后立即清缓存。变量按“专属值 → 共用值 → 专属默认值 → 共用默认值”解析，预览和真实发送共用同一函数，缺失 Key 阻止发布；删除变量前检查已发布提示词是否会缺值。人工评分始终先写本地 `ai_call_scores`，未同步时标记 `langfuseSynced=false`。评分随调用日志保留 180 天。
- 手机号使用 Fernet 加密存储，检索走 HMAC 索引；会话令牌只存 SHA-256 摘要。
- 管理后台使用独立账号表、独立会话表与独立鉴权依赖，权限点在服务端校验；前端隐藏按钮不作为安全边界。
- 后台会持续增长的业务列表（饭帖审核、菜谱、用户、审计日志、AI 调用日志、用户发布记录）统一使用页码分页，接口返回 `items`、`total`、`page`、`pageSize`；客户端信息流仍使用游标分页，因为它是无限滚动，不需要跳页。
- 菜谱批量上架/下架对已是目标状态的菜谱幂等跳过，不重复写审计日志；批量删除是物理删除，只允许删除没有饭帖引用的菜谱，被引用时跳过并提示改为下架，同时清理分类关联与用户收藏。客户端菜谱列表按分类关联表筛选，因此知识库草稿默认归入“推荐”，新增、编辑、批量上架时若菜谱已发布但没有任何分类，服务端会自动补“推荐”并同步关联表，避免“后台已发布、App 看不到”。
- 知识库切片默认目标 400 字、上限 800 字、相邻重叠 80 字，每片带“文档标题｜章节路径”上下文头；图片随文档上传后保存到 `kb/{文档编号}/images/`，正文改写为 `/media/...`，切片预览显示图片，生成向量前自动去掉图片标记；嵌入维度固定 1024，同一时间只有一个启用的索引版本；重建只影响当前文档，不自动切换版本。建立索引只使用用途为 `embedding` 且已启用的供应商，聊天配置不参与；失败信息会写出供应商名称、模型名与实际请求地址，HTTP 404 表示该供应商没有嵌入接口（例如 DeepSeek 只有对话接口），需换成支持 `/embeddings` 的供应商。
- 知识库批量导入一个批次最多 200 篇文档、300 张图片；ZIP 本体不超过 50 MB、解压后不超过 100 MB、条目不超过 1000；拒绝加密包、符号链接与包含 `..` 的路径；内容摘要相同的文档记为“已跳过”，不会重复入库；失败项单独重试，成功项不重复解析。
- 后台删除饭帖采用软删除：状态改为 `deleted` 并记录删除时间，公开列表和后台默认列表都不展示，记录仍保留供审计；批量删除需要 `post.delete` 权限，一次最多 20 条。
- 饭帖状态只允许 `pending_review -> published/rejected`、`published -> unpublished`，以及任意可见状态 `-> deleted`；重复操作返回当前状态而不重复写入。
- 审计日志只追加、不修改、不删除；拒绝、下架、删除、封禁必须填写原因，操作与日志在同一个数据库事务中提交。
- 封禁用户会撤销其全部未注销会话；后台列表中的手机号默认脱敏。
- 附近展示只保留约百米级坐标，且必须由用户明确同意公开。

## 设计令牌

| 名称 | 值 |
| --- | --- |
| 主色（番茄橙红） | `#CC462C` |
| 深主色 | `#9E2F1C` |
| 正文 | `#242424` |
| 辅助文字 | `#666666` |
| 浅灰底 | `#F6F7F8` |
| 浅桃底 | `#FFF0EB` |
| 危险 | `#B33226` |

## 当前边界

- 短信为控制台/开发码实现，未接真实供应商。
- AI 主流程已接通：后台可配置多个 OpenAI 兼容模型，同一用途同时只启用一个，调用时使用启用中的那个；未启用或调用失败时回退本地规则推荐。真实供应商需要在管理后台填入有效的接口地址、模型名与 API Key 后，用“测试连接”验证。
- 主场景的“选店”目前依赖附近饭帖和热榜；AI 只推荐平台菜谱，尚未把附近饭帖、距离和预算纳入候选，这是下一阶段的产品缺口。
- 媒体为本地磁盘存储，生产替换 OSS 需实现 `media_service` 的存储适配。
- 管理后台已完成：数据看板、饭帖审核（含批量）、菜谱、口味标签、模型配置、AI 调用日志、AI 观测、提示词管理、知识库、用户管理、管理员与角色、审计日志。举报、多级复核仍属于后续阶段。
- 知识库首版只支持 UTF-8 的 `.md` / `.txt`；单篇上传同步完成切片，批量导入使用进程内后台任务逐篇切片，接口先返回批次编号、前端轮询进度。PDF/Word 解析、独立任务队列进程、把检索结果接入 AI 问答与引用校验留待后续阶段。
- HowToCook 解析器与导入批次、后台任务两张表已完成，试运行覆盖 374 份菜谱；正式导入应用与后台页面尚未接入，目前菜谱数据仍以演示数据为主。
