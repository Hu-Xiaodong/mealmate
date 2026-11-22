# 今天吃啥 · 管理后台与 RAG 知识库方案 V1.0.0

| 项目 | 内容 |
| --- | --- |
| 文档状态 | 方案待评审，尚未写代码 |
| 适用阶段 | V1 内测之后、公开社区上线之前 |
| 依据 | PRD `E-03`（审核、举报、下架、审计）、`A-03`（AI 供应商与配额）、`A-04`（菜谱来源与授权） |
| 代码基线 | `server/`（FastAPI）、`app_mini/`（uni-app）、`app_flutter/`（Flutter） |
| 目标读者 | 产品、后端、前端、测试、运营 |

---

## 1. 为什么要做

### 1.1 当前代码已经存在的缺口

生产环境通过 `docker-compose.yml` 强制 `AUTO_PUBLISH_POSTS=false`，也就是新发布的饭帖不会直接公开，而是写入 `pending_review` 状态。但项目里目前**没有任何接口能把它改成 `published`**。

这意味着上线后会出现这样的结果：

1. 用户发布成功，客户端提示“已提交审核”；
2. 内容进入数据库，状态是 `pending_review`；
3. 首页、热榜、菜谱页都查不到它；
4. 没有任何人或工具能审核它。

这不是“以后再加”的功能，而是**当前生产链路没有闭合**。管理后台的第一优先级就是补上这个出口。

### 1.2 后期接入 RAG 的需要

`RAG`（Retrieval-Augmented Generation，检索增强生成）的做法是：先把平台自己的资料切成小段存起来，用户提问时先检索出最相关的几段，再连同问题一起交给大模型作答。这样模型回答的是“我们资料里的内容”，而不是凭空编造。

资料需要有人上传、解析、检查切片质量、重建索引，这些操作不可能靠改数据库完成，必须有后台界面。

### 1.3 本方案要解决的问题

| 编号 | 问题 | 目标 |
| --- | --- | --- |
| G-01 | 待审核内容没有出口 | 提供审核、拒绝、下架能力 |
| G-02 | 违规用户无法处置 | 提供封禁、解封能力 |
| G-03 | 后台操作无法追责 | 提供只追加的审计日志 |
| G-04 | AI 调用不可观测 | 记录调用日志、可调配额 |
| G-05 | 平台资料无法被 AI 使用 | 提供知识库上传、切片、索引与召回测试 |

### 1.4 本方案不做什么

- 不做面向消费者的新 Tab，后台只服务内部人员。
- 不做复杂的工单、审批流、多级复核，首版是单人操作即可完成。
- 不做举报入口的完整产品化（PRD 中仍为待确认项），但数据表预留字段。
- 不替代对象存储迁移，RAG 上线前必须先完成媒体存储改造。

---

## 2. 名词解释

| 名词 | 解释 |
| --- | --- |
| 管理后台 | 只给内部人员使用的网页系统，用来管理内容、用户和配置，普通用户看不到入口 |
| RBAC | Role-Based Access Control，基于角色的访问控制。权限不直接分配给某个人，而是先定义角色拥有哪些权限，再把角色分配给账号 |
| 权限点 | 一个最小操作单位的字符串标识，例如 `post.review` 表示“审核饭帖” |
| 审计日志 | 只追加、不修改、不删除的操作流水，记录谁在什么时间对什么数据做了什么 |
| 会话 | 用户登录后服务端签发的一段凭证，客户端每次请求都带上它证明身份 |
| 令牌摘要 | 不保存令牌原文，只保存它的哈希值。即使数据库泄露，也无法反推出可用令牌 |
| RAG | 检索增强生成，先从自有资料检索，再让大模型基于检索结果回答 |
| 切片 | 把长文档按固定长度切成小段，每段单独存储和检索，也叫分块 |
| 嵌入 | Embedding，把一段文字转换成一串数字（向量），语义相近的文字向量距离更近 |
| 向量 | 一组浮点数组成的数组，例如 1024 个数字，用来表示文本的语义特征 |
| 向量检索 | 计算问题向量与资料向量的距离，取距离最近的前几条，即语义最相关的内容 |
| pgvector | PostgreSQL 的一个扩展插件，让数据库可以直接存储向量并做相似度查询 |
| 索引版本 | 一次完整的“切片加嵌入”产物的编号。换模型或换切片规则时必须整体重建，不能新旧混用 |
| 召回 | 检索阶段把相关资料找出来的过程。召回测试就是输入问题，看能否找到正确片段 |
| 对象存储 | 专门存文件的云服务，例如阿里云对象存储服务、腾讯云对象存储、自建 MinIO |
| 幂等 | 同一个请求重复执行多次，结果与执行一次相同，不会产生重复数据 |
| 密码哈希 | 把密码经过不可逆算法转换成密文存储。数据库泄露也无法直接得到原始密码 |
| Argon2id | 一种密码哈希算法，故意消耗内存和计算时间，让暴力破解成本极高，是目前推荐的选择 |
| 二次验证 | 密码之外再增加一步验证，例如短信验证码或动态口令 |

---

## 3. 总体架构

```
                    ┌─────────────────────────────┐
   普通用户 ────────▶│ Flutter（Android/iOS）      │
                    │ uni-app（小程序/H5）        │
                    └──────────────┬──────────────┘
                                   │ HTTPS /api/v1
                    ┌──────────────▼──────────────┐
   内部人员 ────────▶│ 管理后台 Web（Vue 3）       │
                    │ 独立登录 / 独立权限          │
                    └──────────────┬──────────────┘
                                   │ HTTPS /api/v1/admin
                    ┌──────────────▼──────────────┐
                    │ FastAPI（同一个服务）        │
                    │ C 端路由 + 后台路由 + RAG    │
                    └───────┬──────────┬──────────┘
                            │          │
                  ┌─────────▼───┐  ┌───▼──────────────┐
                  │ PostgreSQL  │  │ 对象存储（后期）  │
                  │ + pgvector  │  │ 原始文档与图片    │
                  └─────────────┘  └──────────────────┘
```

关键决策：

1. **不新建后端服务**。后台接口挂在同一个 FastAPI 下，前缀 `/api/v1/admin`。理由：当前规模不需要微服务，拆开只会增加部署和联调成本。等后台流量独立到需要单独扩容时再拆。
2. **管理后台是第三套前端**，使用 Vue 3 + Element Plus，独立于 uni-app。理由见 7.1。
3. **数据库仍是 PostgreSQL**，RAG 通过 pgvector 扩展实现，不引入独立向量数据库。

---

## 4. 权限模型

### 4.1 为什么不能复用普通用户登录

普通用户注册无门槛、数量大、令牌有效期 60 天（产品要求两个月免登录）。管理员权限极高，一旦令牌泄露影响的是全平台，因此管理员会话只保留 1 天。两者混用会让任何一个客户端漏洞升级为后台入侵。

因此后台使用**独立的账号表、独立的会话表、独立的登录入口、独立的鉴权依赖**。

### 4.2 账号与密码

后台不使用手机号验证码登录，改用“用户名 + 密码”。原因：

- 验证码依赖短信供应商，后台人员少，不需要承担短信成本和延迟；
- 密码可以配合二次验证，更适合高权限场景；
- 避免管理员账号与普通用户手机号体系耦合。

密码使用 **Argon2id** 哈希后存储，数据库只保存 `password_hash`，永远不保存明文，也无法解密还原。登录失败次数限制为同一用户名加同一来源地址 10 分钟内 5 次，超出后锁定 15 分钟。

### 4.3 角色与权限点

首版四个角色：

| 角色代码 | 名称 | 能做什么 |
| --- | --- | --- |
| `super_admin` | 超级管理员 | 全部权限，包含管理员账号管理 |
| `content_operator` | 内容运营 | 审核饭帖、下架内容、管理菜谱、查看用户 |
| `ai_operator` | AI 运营 | 查看 AI 日志、调整配额、管理知识库 |
| `auditor` | 审计员 | 只读，可查看审计日志和各类列表，不能修改任何数据 |

权限点清单：

| 权限点 | 含义 |
| --- | --- |
| `post.review` | 通过或拒绝待审饭帖 |
| `post.unpublish` | 下架已公开饭帖 |
| `user.read` | 查看用户列表与详情 |
| `user.ban` | 封禁、解封账号 |
| `recipe.manage` | 新建、编辑、发布菜谱 |
| `ai.log.read` | 查看 AI 调用日志 |
| `ai.config.write` | 修改 AI 配额与供应商配置 |
| `kb.document.manage` | 上传、删除知识库文档，重建索引 |
| `kb.search.test` | 使用召回测试 |
| `audit.read` | 查看审计日志 |
| `admin.manage` | 管理管理员账号与角色 |

**权限校验必须在服务端完成**。前端隐藏按钮只是体验优化，不能作为安全边界。后端提供 `require_permission("post.review")` 依赖，未授权直接返回 403。

---

## 5. 数据库设计

### 5.1 新增表：管理员与权限

```text
admin_users
  id              String(40)   主键，前缀 adm_
  username        String(40)   登录名，唯一索引
  password_hash   String(255)  Argon2id 哈希
  display_name    String(40)   显示名称
  status          String(20)   active / disabled
  last_login_at   DateTime     最后登录时间，可空
  created_at      DateTime     创建时间

admin_roles
  id              String(40)   主键，前缀 role_
  code            String(40)   角色代码，唯一
  name            String(40)   角色名称

admin_user_roles
  id              String(40)   主键
  admin_id        String(40)   外键 admin_users.id
  role_id         String(40)   外键 admin_roles.id
  唯一约束        (admin_id, role_id)

admin_role_permissions
  id              String(40)   主键
  role_id         String(40)   外键 admin_roles.id
  permission_code String(60)   权限点，例如 post.review
  唯一约束        (role_id, permission_code)

admin_sessions
  id              String(40)   主键
  admin_id        String(40)   外键 admin_users.id，索引
  token_digest    String(64)   令牌的 SHA-256 摘要，唯一索引
  expires_at      DateTime     过期时间，登录后 1 天
  revoked_at      DateTime     主动注销时间，可空
  ip              String(64)   登录来源地址
  created_at      DateTime     创建时间
```

### 5.2 新增表：审计日志

```text
audit_logs
  id              String(40)   主键
  actor_id        String(40)   操作人标识
  actor_name      String(40)   操作人名称快照
  action          String(60)   动作，例如 post.approve
  target_type     String(40)   对象类型，例如 meal_post
  target_id       String(40)   对象标识
  reason          String(200)  操作原因，拒绝和下架时必填
  before_json     JSON         变更前快照，可空
  after_json      JSON         变更后快照，可空
  ip              String(64)   来源地址
  request_id      String(64)   请求标识，与接口响应头一致
  created_at      DateTime     操作时间，索引
```

约束：这张表**只允许插入**。应用层不提供修改和删除接口；数据库层面建议单独使用一个只有插入权限的账号写入。

### 5.3 修改表：饭帖

在 `meal_posts` 上增加三个字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `reviewed_by` | String(40) | 审核人标识，外键 `admin_users.id`，可空 |
| `reviewed_at` | DateTime | 审核时间，可空 |
| `review_reason` | String(200) | 拒绝或下架原因，可空 |

状态取值固定为四种：

| 状态 | 含义 | 是否出现在公开列表 |
| --- | --- | --- |
| `pending_review` | 待审核 | 否 |
| `published` | 已公开 | 是 |
| `rejected` | 审核拒绝 | 否 |
| `unpublished` | 已下架 | 否 |

状态流转只允许以下路径，其他组合一律拒绝：

```text
pending_review ──通过──▶ published
pending_review ──拒绝──▶ rejected
published      ──下架──▶ unpublished
```

### 5.4 新增表：AI 调用日志

```text
ai_call_logs
  id                String(40)   主键
  subject_ref       String(80)   调用主体，user:xxx 或 guest:xxx
  user_id           String(40)   登录用户标识，可空
  provider          String(40)   供应商标识
  model             String(60)   模型名称
  context_type      String(20)   home / post / recipe
  request_chars     Integer     输入字符数
  response_chars    Integer     输出字符数
  prompt_tokens     Integer     输入令牌数，可空
  completion_tokens Integer     输出令牌数，可空
  latency_ms        Integer     耗时毫秒
  status            String(20)   success / failed
  error_code        String(40)   失败时的错误码，可空
  created_at        DateTime     创建时间，索引
```

说明：**不记录完整对话原文**，只记录长度和统计信息，避免日志中堆积个人信息。需要排查问题时再按 `request_id` 临时开启详细日志。

### 5.5 新增表：知识库

```text
kb_index_versions
  id              String(40)   主键
  name            String(80)   版本名称
  embed_provider  String(40)   嵌入服务供应商标识
  embed_model     String(60)   嵌入模型名称
  dimensions      Integer      向量维度，例如 1024
  chunk_size      Integer      每段字符数
  chunk_overlap   Integer      相邻段重叠字符数
  status          String(20)   building / active / archived
  created_at      DateTime     创建时间
  activated_at    DateTime     启用时间，可空

kb_documents
  id              String(40)   主键
  title           String(120)  文档标题
  source_type     String(20)   pdf / docx / markdown / text
  storage_key     String(255)  对象存储中的路径
  mime            String(80)   文件类型
  bytes           Integer      文件大小
  checksum        String(64)   内容摘要，用于去重
  status          String(20)   uploaded / parsing / chunking / indexing / ready / failed
  error_message   String(500)  失败原因，可空
  index_version_id String(40)  最近一次索引版本，可空
  uploaded_by     String(40)   上传人
  created_at      DateTime     创建时间
  updated_at      DateTime     更新时间

kb_chunks
  id              String(40)   主键
  document_id     String(40)   外键 kb_documents.id，索引
  index_version_id String(40)  外键 kb_index_versions.id，索引
  ordinal         Integer      在文档中的顺序号
  content         Text         切片原文
  token_count     Integer      令牌数量估算
  embedding       Vector(1024) 向量列，来自 pgvector 扩展
  metadata        JSON         附加信息，例如页码、章节
  created_at      DateTime     创建时间
  唯一约束        (document_id, index_version_id, ordinal)
```

关于向量维度：维度由所选嵌入模型决定，必须在建表前确定，建表后不能随意修改。首版建议固定一个模型和一个维度，换模型时新建索引版本并整体重建。

**SQLite 兼容策略**：`pgvector` 的向量类型只有 PostgreSQL 支持。从 RAG 阶段开始，本地开发也改用 `docker compose` 里的 PostgreSQL，不再使用 SQLite。RAG 相关模型单独放在 `app/db/rag_models.py`，仅在数据库方言为 PostgreSQL 时导入和建表；SQLite 环境下知识库接口统一返回 `RAG_UNAVAILABLE`。

---

## 6. 接口设计

所有后台接口前缀为 `/api/v1/admin`，响应格式与现有接口一致：`{ requestId, code, message, data }`，`code=0` 表示成功。

### 6.1 认证

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/admin/auth/login` | 无 | 用户名 + 密码登录，返回令牌与权限点列表 |
| POST | `/admin/auth/logout` | 已登录 | 注销当前会话 |
| GET | `/admin/auth/me` | 已登录 | 当前管理员信息与权限点 |

登录响应示例：

```json
{
  "requestId": "req_xxx",
  "code": 0,
  "message": "ok",
  "data": {
    "token": "adm_xxx",
    "expiresAt": "2026-11-18T16:00:00Z",
    "admin": { "id": "adm_xxx", "username": "ops", "displayName": "运营小张" },
    "permissions": ["post.review", "user.read", "post.unpublish"]
  }
}
```

### 6.2 内容审核

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/admin/posts` | `post.review` | 列表，支持 `status`、`cursor`、`limit` |
| GET | `/admin/posts/{id}` | `post.review` | 详情，含全部图片、作者、来源 |
| POST | `/admin/posts/{id}/approve` | `post.review` | 通过，状态改为 `published` 并写入发布时间 |
| POST | `/admin/posts/{id}/reject` | `post.review` | 拒绝，必须传 `reason` |
| POST | `/admin/posts/{id}/unpublish` | `post.unpublish` | 下架已公开内容，必须传 `reason` |

审核操作必须幂等：重复点击“通过”时，第二次请求返回当前状态而不是报错或重复写入。

### 6.3 用户管理

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/admin/users` | `user.read` | 列表，支持昵称、手机号后四位搜索 |
| GET | `/admin/users/{id}` | `user.read` | 详情，含发布数、点赞数、收藏数 |
| POST | `/admin/users/{id}/ban` | `user.ban` | 封禁，必须传 `reason` |
| POST | `/admin/users/{id}/unban` | `user.ban` | 解封 |

手机号列表默认脱敏显示为 `138****0009`。查看完整号码需要额外权限并在审计日志中记录。

封禁只把 `users.status` 改为 `disabled`，同时撤销该用户全部会话，不删除数据。

### 6.4 菜谱管理

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/admin/recipes` | `recipe.manage` | 列表，含草稿与已发布 |
| POST | `/admin/recipes` | `recipe.manage` | 新建草稿 |
| PUT | `/admin/recipes/{id}` | `recipe.manage` | 编辑 |
| POST | `/admin/recipes/{id}/publish` | `recipe.manage` | 发布，要求 `validation_status=tested` |

### 6.5 AI 管理

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/admin/ai/logs` | `ai.log.read` | 日志列表，支持状态、时间范围、主体筛选 |
| GET | `/admin/ai/settings` | `ai.log.read` | 当前配额与供应商标识，密钥只返回“已配置/未配置” |
| PUT | `/admin/ai/settings` | `ai.config.write` | 修改游客与登录用户每日配额、模型名称 |
| POST | `/admin/ai/settings/test` | `ai.config.write` | 发送一条测试消息，验证供应商连通性 |

密钥不允许通过接口读取；写入后只保存在服务端环境变量或密钥管理服务中。

### 6.6 知识库与 RAG

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/admin/kb/documents` | `kb.document.manage` | 文档列表与状态 |
| POST | `/admin/kb/documents` | `kb.document.manage` | 上传文档，表单上传 |
| GET | `/admin/kb/documents/{id}` | `kb.document.manage` | 文档详情与解析错误 |
| DELETE | `/admin/kb/documents/{id}` | `kb.document.manage` | 删除文档及其切片 |
| POST | `/admin/kb/documents/{id}/reindex` | `kb.document.manage` | 重新解析并生成切片 |
| GET | `/admin/kb/documents/{id}/chunks` | `kb.document.manage` | 查看切片，分页 |
| POST | `/admin/kb/index-versions` | `kb.document.manage` | 新建索引版本 |
| POST | `/admin/kb/index-versions/{id}/activate` | `kb.document.manage` | 启用某个版本，其他版本归档 |
| POST | `/admin/kb/search-test` | `kb.search.test` | 输入问题，返回命中的切片与相似度 |

`search-test` 响应示例：

```json
{
  "requestId": "req_xxx",
  "code": 0,
  "message": "ok",
  "data": {
    "query": "微波炉能做哪些菜",
    "indexVersionId": "kbv_xxx",
    "chunks": [
      {
        "chunkId": "kbc_xxx",
        "documentId": "kbd_xxx",
        "documentTitle": "快手菜谱手册",
        "ordinal": 12,
        "content": "……",
        "score": 0.87
      }
    ]
  }
}
```

### 6.7 审计日志

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/admin/audit-logs` | `audit.read` | 按操作人、动作、时间范围筛选，只读 |

---

## 7. 管理后台前端

### 7.1 技术选型

| 层 | 选型 | 理由 | 同类的其他方案 |
| --- | --- | --- | --- |
| 框架 | Vue 3 + TypeScript + Vite | 与现有 uni-app 技术栈一致，学习成本最低 | React（生态更大，但团队要换心智） |
| 组件库 | Element Plus | 表格、表单、弹窗、分页开箱即用，国内后台最常用 | Ant Design Vue（同样成熟，风格更偏企业）、Naive UI（更轻但组件少） |
| 状态管理 | Pinia | 与现有项目一致 | Vuex（已进入维护状态） |
| 请求 | 复用同一套统一响应解析逻辑 | 契约一致，减少重复代码 | Axios 拦截器封装 |

不建议把后台塞进 uni-app：后台是桌面宽屏、表格密集、批量操作多的场景，和小程序的单列卡片流是两种交互模型，强行共用会让两端都变形。

### 7.2 目录结构

```text
app_admin/
  package.json
  vite.config.ts
  index.html
  src/
    main.ts
    App.vue
    router/index.ts          路由与登录守卫
    stores/admin.ts          管理员会话与权限点
    api/client.ts            统一请求与错误处理
    api/types.ts             接口类型
    layouts/AdminLayout.vue  左侧菜单 + 顶部账号
    views/
      login/LoginView.vue
      posts/ReviewListView.vue
      posts/PostDetailDrawer.vue
      users/UserListView.vue
      recipes/RecipeListView.vue
      ai/AiLogView.vue
      ai/AiSettingsView.vue
      kb/DocumentListView.vue
      kb/DocumentDetailView.vue
      kb/SearchTestView.vue
      audit/AuditLogView.vue
```

### 7.3 页面与交互要点

| 页面 | 关键交互 |
| --- | --- |
| 登录 | 用户名密码、错误提示、登录失败次数提示 |
| 待审列表 | 状态筛选、图片缩略图、批量通过、单条拒绝并填写原因 |
| 内容详情 | 图片大图、来源、作者、定位、审核记录 |
| 用户列表 | 昵称与手机号后四位搜索、封禁/解封、查看发布 |
| AI 日志 | 时间范围、成功/失败筛选、耗时排序 |
| AI 配置 | 配额输入、供应商状态、测试按钮 |
| 知识库列表 | 上传、状态轮询、失败原因、重建索引 |
| 文档详情 | 切片列表、切片内容预览、重新解析 |
| 召回测试 | 输入问题、展示命中片段与相似度、可跳转文档 |
| 审计日志 | 只读表格、操作前后值对比 |

权限控制：路由守卫检查是否登录；菜单和按钮根据权限点显示或隐藏；所有判断只是体验层，服务端仍会校验。

---

## 8. RAG 链路设计

### 8.1 写入链路

```text
上传文档
  → 校验类型与大小
  → 存入对象存储，记录 kb_documents
  → 解析出纯文本（PDF / Word / Markdown）
  → 清洗（去页眉页脚、合并断行、去除空段）
  → 切片（按字符数 + 重叠）
  → 调用嵌入服务，得到每段的向量
  → 写入 kb_chunks，绑定当前索引版本
  → 建立向量索引
  → 版本状态改为 active
```

状态机：

```text
uploaded → parsing → chunking → indexing → ready
                                  └──────▶ failed
```

每一步失败都写入 `error_message`，前端可看到具体原因并重试。

### 8.2 查询链路

```text
用户问题
  → 问题转成向量
  → 在 active 版本中按余弦距离取前 K 条
  → 过滤低于相似度阈值的片段
  → 拼接提示词：资料片段 + 用户问题 + 回答约束
  → 调用大模型
  → 返回答案与引用片段标识
```

### 8.3 防幻觉约束

1. 提示词中明确要求“只能依据下列资料回答；资料不足时直接说明不知道”。
2. 模型返回的引用标识必须来自本次检索结果，不在结果内的直接丢弃。
3. 没有片段超过相似度阈值时，不调用模型，直接返回“知识库暂无相关内容”。
4. 响应中带上引用来源，前端展示“依据：某文档第几段”。

### 8.4 索引版本化

换嵌入模型、换切片长度都会让新旧向量不在同一个语义空间，不能混用。做法：

1. 新建 `kb_index_versions`，状态为 `building`；
2. 后台任务把所有文档重新切片、重新嵌入，写入新版本；
3. 抽样做召回测试，确认效果；
4. 点击“启用”，新版本变 `active`，旧版本变 `archived`；
5. 保留旧版本一段时间，出问题可切回。

### 8.5 嵌入模型选择

| 方案 | 优点 | 缺点 | 适用 |
| --- | --- | --- | --- |
| 云厂商嵌入接口 | 无需显卡，按量计费，效果好 | 数据要出网，按调用付费 | 首版推荐 |
| 本地开源嵌入模型 | 数据不出内网，无调用费 | 需要显卡或较强处理器，运维复杂 | 有合规要求时 |

首版建议先用云厂商接口，固定一个模型和维度，降低工程量。具体供应商属于 PRD `A-03` 待确认项，需产品和预算共同确认。

---

## 9. 安全与合规

| 项目 | 措施 |
| --- | --- |
| 密码 | Argon2id 哈希，永不明文存储，永不出现在日志 |
| 登录防护 | 同用户名加来源地址 10 分钟 5 次失败锁定 15 分钟 |
| 会话 | 1 天过期，注销立即失效，令牌只存摘要 |
| 权限 | 服务端依赖逐接口校验，前端隐藏不作为安全边界 |
| 审计 | 只追加；记录操作前后值、原因、来源地址、请求标识 |
| 密钥 | 只存环境变量或密钥管理服务，接口不回显 |
| 个人信息 | 列表脱敏；查看完整手机号需单独权限并留审计 |
| 文件上传 | 限制类型与大小；对象存储使用私有桶，禁止公开读 |
| 后台入口 | 建议限制来源地址或走内部网络，不直接暴露公网 |
| 接口文档 | 生产环境已关闭 `/docs`，后台接口同样不公开 |

审计日志保留期限：PRD 建议 180 天，最终以合规要求为准。

---

## 10. 分阶段实施

### 第一阶段：最小审核闭环（P0）

范围：管理员登录、RBAC 基础、饭帖审核、用户封禁、审计日志。

改动清单：

| 位置 | 改动 |
| --- | --- |
| `server/app/db/models.py` | 新增管理员、角色、会话、审计表；饭帖增加审核字段 |
| `server/app/services/admin_auth_service.py` | 登录、密码校验、会话签发与撤销 |
| `server/app/services/review_service.py` | 审核状态流转与幂等 |
| `server/app/services/admin_user_service.py` | 用户列表、封禁、解封 |
| `server/app/services/audit_service.py` | 统一写审计日志 |
| `server/app/api/admin_deps.py` | `get_current_admin`、`require_permission` |
| `server/app/api/routes/admin/` | auth / posts / users / audit |
| `server/app/api/router.py` | 注册后台路由 |
| `server/app/db/seed.py` | 初始化角色与权限点，创建首个管理员 |
| `app_admin/` | 登录、审核列表、用户列表、审计日志 |

验收标准：

1. 生产模式下新发布饭帖进入 `pending_review`，后台可通过后出现在首页与热榜；
2. 拒绝时必须填写原因，本人“我的发布”能看到状态与原因；
3. 下架后公开列表立即不可见，热榜重新计算；
4. 封禁用户后其所有会话立即失效；
5. 每次审核、封禁都产生一条审计日志；
6. 没有对应权限点的账号调用接口返回 403。

### 第二阶段：AI 可观测与配置（P1）

范围：AI 调用日志、配额配置、连通性测试、菜谱后台管理。

验收标准：

1. 每次 AI 调用产生一条日志，含耗时与状态；
2. 后台修改配额后立即生效；
3. 密钥不可通过接口读取；
4. 供应商不可用时接口返回明确错误码，不阻塞浏览。

### 第三阶段：RAG 知识库（P2）

前置条件：对象存储已接入、本地开发切换到 PostgreSQL、`pgvector` 扩展可用。

范围：文档上传、解析、切片、索引版本、召回测试、AI 回答带引用。

验收标准：

1. 上传文档后能看到状态从 `uploaded` 到 `ready`；
2. 切片列表可查看原文与顺序；
3. 召回测试能返回相关片段及相似度；
4. 新建索引版本并启用后，旧版本自动归档；
5. AI 回答只引用检索结果中的片段；
6. 知识库无相关内容时明确说明，不编造。

---

## 11. 与现有代码的衔接

| 现有实现 | 衔接方式 |
| --- | --- |
| 统一响应 `{requestId, code, message, data}` | 后台接口直接复用 `core/responses.py` |
| 错误处理 `AppError` | 后台复用同一套错误码与处理器 |
| 会话鉴权 `resolve_session` | 后台另写管理员会话解析，不复用用户令牌 |
| 媒体上传 `media_service` | 后台复用图片校验逻辑；知识库文档另写文档解析服务 |
| 热榜缓存 | 审核通过、下架后主动清除当日热榜缓存键 |
| 种子数据 | 首次启动创建角色、权限点和默认管理员，密码从环境变量读取 |
| Docker Compose | 后台构建为静态文件，由 Nginx 托管；API 增加后台路由即可 |

默认管理员的初始化必须安全：首次启动时从 `ADMIN_INITIAL_USERNAME` 与 `ADMIN_INITIAL_PASSWORD` 读取，若未配置则不创建，并在日志中提示。禁止在代码里写死默认密码。

---

## 12. 风险与待确认项

| 编号 | 事项 | 影响 | 建议 |
| --- | --- | --- | --- |
| Q-01 | 后台是否允许公网访问 | 安全风险 | 默认只允许内网或固定来源地址 |
| Q-02 | 是否需要二次验证 | 安全等级 | 首版可只做密码，上线前评审 |
| Q-03 | 嵌入模型与供应商 | RAG 效果与成本 | 先用云厂商，固定维度 |
| Q-04 | 知识库文档来源与版权 | 合规 | 只上传有授权或自建内容 |
| Q-05 | 对象存储选型 | RAG 前置条件 | 阿里云对象存储服务或自建 MinIO |
| Q-06 | 举报入口是否首版上线 | 治理闭环 | PRD 待确认，表结构预留 |
| Q-07 | 审计日志保留期限 | 合规 | 暂按 180 天设计，可配置 |
| Q-08 | 本地开发是否放弃 SQLite | 开发体验 | RAG 阶段起改用 PostgreSQL 容器 |

---

## 13. 面试讲法

### 问题一：为什么管理后台要独立鉴权？

**总结版**：权限等级不同、攻击面不同、会话策略不同。混用会让一个客户端漏洞升级为后台入侵。

**详细版**：普通用户注册无门槛、数量大、令牌有效期长；管理员数量少但权限极高，需要短会话、可随时撤销、可绑定来源地址。如果共用一套令牌体系，任何越权漏洞都可能被用来调用后台接口。正确做法是独立账号表、独立会话表、独立路由前缀、独立鉴权依赖，服务端逐接口校验权限点，前端隐藏按钮只作为体验优化。

### 问题二：为什么 RAG 需要索引版本？

**总结版**：换嵌入模型或切片规则后，新旧向量不在同一语义空间，混用会导致检索结果失真，所以必须整体重建并原子切换。

**详细版**：向量由特定嵌入模型生成，不同模型的维度与语义分布不同，不能直接比较相似度；切片长度变化也会让同一文档产生完全不同的向量集合。因此每次重建写入新的版本记录，验证召回效果后再切换为启用状态，旧版本保留用于回滚。这和后端做数据库迁移时“先写新表、再切读流量”是同一个思路。

### 问题三：怎么保证 AI 不编造知识库没有的内容？

**总结版**：先检索后回答，引用必须来自检索结果，没有命中就明确说不知道。

**详细版**：流程是先按问题做向量检索，取相似度最高的若干片段；如果全部低于阈值，直接返回“暂无相关内容”，不调用模型；如果有命中，把片段和问题一起交给模型，并要求只能依据片段作答、必须返回片段标识；服务端再校验返回的标识是否在本次检索结果内，不在就丢弃。这样模型只负责组织语言，不负责提供事实来源。

---

## 14. 参考资料

- FastAPI 官方文档：https://fastapi.tiangolo.com/
- SQLAlchemy 2.0 异步文档：https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- pgvector 项目主页：https://github.com/pgvector/pgvector
- Element Plus 文档：https://element-plus.org/zh-CN/
- Argon2 密码哈希规范：https://www.rfc-editor.org/rfc/rfc9106
- OWASP 应用安全验证标准：https://owasp.org/www-project-application-security-verification-standard/
- 阿里云对象存储服务文档：https://help.aliyun.com/zh/oss/
