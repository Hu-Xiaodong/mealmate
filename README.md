# MealMate

MealMate 是帮助人们决定这一餐吃什么的工具：用附近真实饭帖、热榜和 AI 选餐，把“随便看看”缩小到“就吃这个”，吃完还能把这一餐发布出去，帮助下一个人做决定。


## 核心功能

### 1. 附近、首页与热榜

- 首页按发布时间展示今日饭帖，支持“全部 / 附近”切换；热榜按有效赞排序，每天最多 20 条，业务日按 `Asia/Shanghai` 自然日计算。
- 饭帖详情展示图集、菜名、评价、作者和来源；外卖展示店家名称，到店展示店铺地址，有作者做法时直接展开。


### 2. 发布自己的这一餐

- 来源三选一：到店吃、外卖、自己做。到店和外卖是常见来源；自己做是补充
- 到店来源必须填店铺地址；外卖来源必须填店家名称；自己做可以补充完整的食材和步骤，作为“作者做法”优先展示给其他饭友。


### 3. 问 AI：在已有内容里缩小选择范围

- 当前版本的候选来自平台菜谱，回答“吃什么菜、怎么搭配一餐”，不直接推荐附近商家；“选店”仍由附近饭帖和热榜承担。下一阶段应把已公开的附近饭帖纳入 AI 候选，并增加距离、预算、人数等约束。


### 4. 菜谱

- 按推荐、15 分钟、一锅、少食材等分类浏览，服务于有厨房条件时“想自己做”的需求，不是决策的主路径。
- 菜谱包含用料、步骤、总耗时、所需厨具和前置条件（例如“需要提前煮好米饭”）。
- 作者做法与平台参考做法严格区分：作者提供食材和步骤时优先展示作者做法；否则展示明确关联或严格同名的平台菜谱，并标注“来自平台菜谱·参考做法”。

### 5. 管理后台

- 饭帖审核：通过、拒绝、下架，拒绝和下架必须填原因。
- 用户管理：列表、详情、封禁、解封；封禁会撤销该用户全部未注销会话。
- 审计日志：只追加，不修改、不删除；拒绝、下架、封禁与日志在同一个数据库事务中提交。

## 技术栈

| 层 | 选型 | 原因 |
| --- | --- | --- |
| 后端 | Python 3.12 + FastAPI + Pydantic v2 | 与 PRD 的强类型接口契约贴合，自动生成 OpenAPI，异步 IO 适合图片与配额逻辑 |
| 数据 | PostgreSQL（本地与生产）/ SQLite（仅自动化测试与未配置时的兜底） | 同一套 SQLAlchemy 2.0 async 模型；本地与生产统一使用 PostgreSQL，减少数据库方言差异 |
| 缓存 | Redis 7（可选） | 热榜短缓存与配额计数，未配置时自动降级为数据库实现 |
| Android / iOS | Flutter 3 | 一套 Dart 代码同时覆盖两端，原生性能与一致的交互体验 |
| 微信小程序 / H5 | uni-app + Vue 3 + TypeScript + Vite + Pinia | 小程序与 H5 共享一套代码，同时保留独立的发布节奏 |
| 管理后台 | Vue 3 + TypeScript + Element Plus + Pinia | 内部系统以表格、表单和权限控制为主，组件库成熟；独立工程不打包进用户端 |
| 媒体 | 本地磁盘 + 可替换存储适配器 | 本地开发简单，生产可平滑替换为 OSS/CDN |
| AI | 大模型网关 + 平台内容检索（当前为菜谱，计划纳入附近饭帖；本地规则推荐器 `AI_PROVIDER=mock`） | 先从平台真实内容检索候选，再让模型解释和组合，避免编造；配额、上下文、来源标识和真实内容 ID 校验统一放在网关层 |
| 部署 | Docker Compose | API、PostgreSQL、Redis 一条命令起齐 |

两套客户端是刻意分开的：Flutter 负责原生体验，uni-app 负责微信生态与 H5 分享，二者共用同一套 HTTP 契约。

## 目录结构

```
docs/                    PRD、待确认项与工程验收稿
mealmate/               移动端交互原型（MealMate）
server/                  FastAPI 后端
  app/api/               路由与依赖注入
  app/services/          业务服务（认证、内容流、热榜、菜谱、互动、媒体、AI）
  app/db/                模型、会话与演示数据
  tests/                 API 级 pytest
app_mini/                uni-app（微信小程序 + H5）
app_admin/               管理后台（Vue 3 + Element Plus）
app_flutter/             Flutter（Android + iOS）
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
- 第一阶段页面：登录、饭帖审核（通过、拒绝、下架）、用户管理（列表、详情、封禁、解封）、审计日志。
- 登录状态 2 小时失效；同一用户名与来源地址 10 分钟内失败 5 次，锁定 15 分钟。

### Flutter

```powershell
cd app_flutter
flutter pub get
flutter run --dart-define=API_BASE=http://10.0.2.2:8000
```

- Android 模拟器访问宿主机 API 用 `10.0.2.2`；iOS 模拟器用 `127.0.0.1`；真机用局域网 IP。
- Android 需要 `android.permission.INTERNET`，iOS 调试直连 HTTP 需在 Info.plist 放行 ATS。
- 本机已解压 Flutter SDK 到 `tools/flutter`（该目录被 `.gitignore` 忽略）。未加入 PATH 时先设置：

```powershell
$env:PUB_CACHE='E:\项目\mealmate\tools\pub-cache'
$env:APPDATA='E:\项目\mealmate\tools\appdata'
$env:USERPROFILE='E:\项目\mealmate\tools\home'
$env:HOME='E:\项目\mealmate\tools\home'
& 'E:\项目\mealmate\tools\flutter\bin\flutter' pub get
```

## 测试与检查

```powershell
cd server
pytest
ruff check .
```

当前 20 条测试覆盖登录限流与错误码、分页游标、附近筛选、热榜排序、菜谱与作者做法优先、点赞/收藏、发布幂等、图片校验、AI 游客配额，以及管理后台登录锁定、角色权限、审核状态流转、下架缓存失效、封禁撤销会话与审计日志。

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

## 接口速览

统一响应：`{ requestId, code, message, data }`，`code=0` 表示成功；分页为 `{ items, nextCursor, hasMore }`。

| 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/sms-codes` | 发送登录验证码 | 否 |
| POST | `/api/v1/auth/login` | 验证码登录/注册 | 否 |
| GET | `/api/v1/auth/me` | 当前账号 | 是 |
| POST | `/api/v1/auth/logout` | 注销会话 | 是 |
| GET | `/api/v1/feed` | 今日内容流，支持 `filter=near` | 可选 |
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
| POST | `/api/v1/ai/chat` | 上下文选餐与一餐菜单，游客也可用 | 可选 |

### 管理后台接口（前缀 `/api/v1/admin`）

| 方法 | 路径 | 说明 | 权限点 |
| --- | --- | --- | --- |
| POST | `/auth/login` | 管理员用户名密码登录 | 无 |
| POST | `/auth/logout` | 注销当前会话 | 已登录 |
| GET | `/auth/me` | 当前管理员与权限点 | 已登录 |
| GET | `/posts` | 饭帖列表，可按状态筛选 | `post.review` |
| GET | `/posts/{id}` | 饭帖详情 | `post.review` |
| POST | `/posts/{id}/approve` | 审核通过 | `post.review` |
| POST | `/posts/{id}/reject` | 审核拒绝，必须填原因 | `post.review` |
| POST | `/posts/{id}/unpublish` | 下架已公开饭帖，必须填原因 | `post.unpublish` |
| GET | `/users` | 用户列表与搜索 | `user.read` |
| GET | `/users/{id}` | 用户详情 | `user.read` |
| POST | `/users/{id}/ban` | 封禁并撤销会话 | `user.ban` |
| POST | `/users/{id}/unban` | 解封 | `user.ban` |
| GET | `/audit-logs` | 审计日志，只读 | `audit.read` |

## 关键业务约定

- 业务日按 `Asia/Shanghai` 自然日计算；热榜按有效赞降序、发布时间升序、ID 升序，最多 20 条。
- 点赞与收藏必须登录；登录前触发的操作会在登录成功后自动续做。
- 饭帖来源分 `self` / `takeaway` / `dine_in`，外卖必须填店家，到店必须填地址。
- 图片 1–9 张、单张不超过 5MB；服务端校验真实图片格式、去除 EXIF 并生成缩略图。
- 验证码 5 分钟有效、60 秒可重发、连续输错 5 次失效。
- AI 只引用平台真实菜谱 ID，硬性筛选条件为最长耗时、厨具、食材和忌口，支持一餐菜单组合；预算、人数等自然语言条件尚未结构化。游客每日 5 次、登录每日 20 次。当前 `AI_PROVIDER=mock`，接入真实模型前不会伪造外部结果。
- 手机号使用 Fernet 加密存储，检索走 HMAC 索引；会话令牌只存 SHA-256 摘要。
- 管理后台使用独立账号表、独立会话表与独立鉴权依赖，权限点在服务端校验；前端隐藏按钮不作为安全边界。
- 饭帖状态只允许 `pending_review -> published/rejected` 与 `published -> unpublished`，重复审核返回当前状态而不重复写入。
- 审计日志只追加、不修改、不删除；拒绝、下架、封禁必须填写原因，操作与日志在同一个数据库事务中提交。
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
- AI 当前为可验证的本地推荐器（`AI_PROVIDER=mock`），未接真实大模型；大模型网关、配额、上下文、来源标识和真实菜谱 ID 校验已就位，接入真实模型时替换生成步骤即可。
- 主场景的“选店”目前依赖附近饭帖和热榜；AI 只推荐平台菜谱，尚未把附近饭帖、距离和预算纳入候选，这是下一阶段的产品缺口。
- 媒体为本地磁盘存储，生产替换 OSS 需实现 `media_service` 的存储适配。
- 管理后台已完成第一阶段：饭帖审核、用户封禁、审计日志。举报、AI 调用日志、知识库管理与多级复核仍属于后续阶段。
