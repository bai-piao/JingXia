# JingXia

JingXia（镜匣）是一个轻量级的边缘侧视觉知识库，核心目标是把图片归档、OCR、标签提取、搜索、Bot 交互和网页画廊串成一条低开销工作流。

当前仓库已经包含三部分：

- `jingxia-core`：FastAPI 后端，负责图片落盘、SQLite 元数据、AI 调用、搜索接口、删除接口
- `jingxia-bot`：Telegram Bot，负责上传、检索、问答、交互式画廊
- `jingxia-web`：Vite + Vue 3 + Tailwind 前端，负责图片画廊展示与搜索

## 1. 目录结构

```text
JingXia/
├── api/                  # FastAPI 路由
├── bot/                  # Telegram Bot
├── core/                 # 配置 / DB / env loader
├── models/               # SQLModel 表模型
├── schemas/              # Pydantic 响应模型
├── services/             # AI / 存储 / 搜索相关服务
├── src/                  # Vue 3 前端源码
├── storage/              # 本地开发图片目录
├── my_data/              # Docker 挂载后的宿主机图片目录
├── Dockerfile            # core 镜像
├── Dockerfile.bot        # bot 镜像
├── Dockerfile.web        # web 镜像
├── docker-compose.yml    # 全栈编排
├── nginx.conf            # web 反向代理配置
├── Makefile              # 常用 compose 命令
├── main.py               # core 启动入口
├── package.json          # 前端依赖
├── requirements.txt      # Python 依赖
└── README.md
```

## 2. 核心环境要求

- Python 3.10+
- Node.js 18+
- Docker + Docker Compose
- 一个 OpenAI 兼容的 AI 服务
  例如宿主机上的 `llama-cpp-python server`

## 3. 环境变量说明

项目采用根目录 `.env`。

- `jingxia-core` 会在启动时自动读取 `.env`
- `jingxia-bot` 会在启动时自动读取 `.env`
- `jingxia-web` 会由 Vite 自动读取 `VITE_` 前缀变量
- Docker Compose 也会读取根目录 `.env`

### 3.1 本地开发环境

```bash
cp .env.example .env
```

### 3.2 Docker 环境

```bash
cp .env.docker.example .env
```

## 4. 关键环境变量

### `jingxia-core`

| 变量名 | 说明 |
| --- | --- |
| `JINGXIA_APP_NAME` | 应用名 |
| `JINGXIA_APP_VERSION` | 版本号 |
| `JINGXIA_API_V1_PREFIX` | API 前缀，默认 `/api/v1` |
| `JINGXIA_DATABASE_FILENAME` | SQLite 文件名 |
| `JINGXIA_STORAGE_DIRNAME` | 图片根目录，本地常用 `storage`，Docker 常用 `/app/storage` |
| `JINGXIA_STORAGE_URL_PREFIX` | 图片 URL 前缀，默认 `/storage` |
| `PUBLIC_BASE_URL` | 对外公开可访问的根地址，用于生成图片直链 |
| `JINGXIA_CORS_ORIGINS` | CORS 白名单，逗号分隔 |
| `AI_API_BASE_URL` | AI 服务地址 |
| `AI_MODEL_NAME` | 调用的模型名 |
| `AI_API_TIMEOUT` | AI 请求超时秒数 |

### `jingxia-bot`

| 变量名 | 说明 |
| --- | --- |
| `TG_BOT_TOKEN` | Telegram Bot Token |
| `JINGXIA_API_BASE` | core API 地址 |

### `jingxia-web`

| 变量名 | 说明 |
| --- | --- |
| `VITE_CORE_API_BASE_URL` | 前端请求的 core API 地址 |

## 5. `PUBLIC_BASE_URL` 说明

这是目前部署里最重要的配置之一。

`jingxia-core` 返回给前端和 Bot 的图片 `url_path` 会基于它生成，例如：

```text
PUBLIC_BASE_URL=http://127.0.0.1:8000
=> http://127.0.0.1:8000/storage/2026/04/xxx.jpg
```

生产环境建议把它设置成最终用户真正能访问到的地址，例如：

- 局域网 IP：`http://192.168.1.20:8000`
- 域名：`https://jingxia.example.com`
- 反向代理入口：`http://127.0.0.1:8080`

注意：

- 本地直接跑 `core` 时，通常设为 `http://127.0.0.1:8000`
- Docker + Nginx 场景下，如果最终用户走前端入口访问图片，更推荐设为 `http://127.0.0.1:8080`

### 5.1 常见配置示例

#### 本机直接开发

```dotenv
PUBLIC_BASE_URL=http://127.0.0.1:8000
```

#### 局域网共享给手机或其他电脑访问

```dotenv
PUBLIC_BASE_URL=http://192.168.1.20:8000
```

#### Docker + Nginx 本机入口

```dotenv
PUBLIC_BASE_URL=http://127.0.0.1:8080
```

#### Docker + 局域网入口

```dotenv
PUBLIC_BASE_URL=http://192.168.1.20:8080
```

#### 公网域名部署

```dotenv
PUBLIC_BASE_URL=https://jingxia.example.com
```

## 6. 本地开发启动

### 6.1 安装 Python 依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 6.2 启动 AI 服务

`jingxia-core` 通过 HTTP 调用 AI，不在进程内加载模型。

建议使用模型：https://modelscope.cn/models/lmstudio-community/Qwen2.5-VL-3B-Instruct-GGUF

示例：

```bash
source venv/bin/activate
python3 -m llama_cpp.server \
  --host 127.0.0.1 \
  --port 8081 \
  --model /absolute/path/to/model.gguf \
  --clip_model_path /absolute/path/to/mmproj.gguf \
  --chat_format qwen2.5-vl
```

### 6.3 启动 `jingxia-core`

```bash
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

启动后：

- API：`http://127.0.0.1:8000/api/v1`
- Health：`http://127.0.0.1:8000/api/v1/health`
- Storage：`http://127.0.0.1:8000/storage/...`

### 6.4 启动 `jingxia-bot`

```bash
source venv/bin/activate
python -m bot.main
```

### 6.5 启动 `jingxia-web`

```bash
npm install
npm run dev
```

默认地址：

- `http://127.0.0.1:5173`

## 7. 本地开发快速自检

### 7.1 检查 core 健康状态

```bash
curl http://127.0.0.1:8000/api/v1/health
```

### 7.2 上传图片

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/upload" \
  -F "file=@/absolute/path/to/example.jpg"
```

### 7.3 查询图片

```bash
curl "http://127.0.0.1:8000/api/v1/images?page=1&page_size=24"
curl "http://127.0.0.1:8000/api/v1/images?keyword=发票"
```

## 8. 当前 API 概览

目前已经提供：

- `GET /api/v1/health`
- `GET /api/v1/images`
- `DELETE /api/v1/images/{image_id}`
- `POST /api/v1/upload`

## 9. Docker 启动

### 9.1 准备环境变量

```bash
cp .env.docker.example .env
```

至少确认：

- `AI_API_BASE_URL`
- `TG_BOT_TOKEN`
- `PUBLIC_BASE_URL`

### 9.2 启动整套服务

推荐：

```bash
make config
make up
```

后台运行：

```bash
make up-d
```

等价命令：

```bash
docker compose config
docker compose up --build
```

### 9.3 Docker 服务说明

#### `jingxia-core`

- 使用 `Dockerfile`
- 宿主机 `./my_data` 挂载到容器 `/app/storage`
- 通过 `PUBLIC_BASE_URL` 决定返回的图片公开地址

#### `jingxia-bot`

- 使用 `Dockerfile.bot`
- 通过内部网络访问 `http://jingxia-core:8000/api/v1`

#### `jingxia-web`

- 使用 `Dockerfile.web`
- 由 Nginx 托管静态资源
- `/api/` 反代到 `jingxia-core:8000/api/`
- `/storage/` 反代到 `jingxia-core:8000/storage/`

### 9.4 Docker 访问地址

- 前端：`http://127.0.0.1:8080`
- Core API：`http://127.0.0.1:8000/api/v1`
- Core Health：`http://127.0.0.1:8000/api/v1/health`

### 9.5 Docker 下 `PUBLIC_BASE_URL` 该怎么填


例子：

- 你只在本机访问 `jingxia-web`
  - 填：`http://127.0.0.1:8080`
- 你在同一局域网里用手机访问
  - 填：`http://192.168.1.20:8080`
- 你前面挂了域名和反向代理
  - 填：`https://jingxia.example.com`

不要填这些：

- `http://jingxia-core:8000`
  - 这是容器内部地址，外部用户不可见
- `http://host.docker.internal:8000`
  - 这主要用于容器访问宿主机，不适合作为对外图片直链
- 任何你自己能访问但外部用户/Bot 访问不到的本地私有地址

### 9.6 Docker 常用命令

```bash
make ps
make logs
make logs-core
make logs-bot
make logs-web
make rebuild-core
make rebuild-bot
make rebuild-web
make down
```

### 9.7 Linux / macOS / Windows 说明

当前 Compose 默认把 AI 服务地址写成：

```text
http://host.docker.internal:8081/v1
```

说明：

- macOS / Windows Docker Desktop 通常可以直接使用
- Linux 下通常依赖：
  - `extra_hosts: host.docker.internal:host-gateway`
- 如果你宿主机环境不同，直接改 `.env` 里的 `AI_API_BASE_URL`

## 10. 部署建议

生产环境建议至少做到：

1. 为 `PUBLIC_BASE_URL` 配置真实域名
2. 将 `./my_data` 换成真正的宿主机持久化目录或挂载点
3. 在宿主机层接入 rclone / NAS / 网盘挂载
4. 为 AI 服务单独做进程管理或容器编排
