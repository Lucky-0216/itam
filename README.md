# ITAM · IT 资产管理系统

基于 FastAPI + Vue 3 的企业 IT 资产全生命周期管理系统，覆盖资产入库、库存、领用/借用/归还、调拨、维修、报废、盘点、合同、审批、到期提醒、报表分析与审计，前后端分离，支持 Docker Compose 一键部署。

> GitHub 仓库：<https://github.com/Lucky-0216/itam>（默认分支 `main`）
>
> **干净系统**：仓库不包含数据库文件、上传文件或任何业务数据。按本文部署后，系统仅初始化管理员、角色、菜单与审批基础配置；部门、资产分类、型号、资产、单据、合同等业务数据全部为空，需要由管理员按实际情况创建。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 前端 | Vue 3 + TypeScript + Element Plus + Pinia + Vue Router + ECharts |
| 后端 | FastAPI + SQLAlchemy 2.0（async）+ Pydantic V2 + Alembic |
| 数据库 | MySQL 8.0（InnoDB / utf8mb4） |
| 缓存与队列 | Redis 7 + Celery（Worker / Beat） |
| 认证与权限 | JWT 双令牌 + RBAC（菜单 / 操作 / 数据范围 / 字段） |
| 部署 | Docker Compose（命名 Volume 持久化） |

## 功能模块

### 1. 认证与权限

- 账号密码登录、刷新令牌、退出登录
- Access Token 30 分钟、Refresh Token 7 天；刷新令牌单次使用并自动轮换，退出或改密后旧令牌立即失效
- 登录成功、登录失败（含停用账号）均写入审计日志
- 个人修改密码；管理员重置密码后，用户下次登录会被强制跳转到修改密码页
- 角色管理：内置超级管理员、资产管理员、部门管理员、普通员工、审计员、维修人员 6 个角色
- 角色授权：菜单与按钮权限、数据范围（全部 / 本部门及下级 / 本部门 / 自定义部门 / 仅本人）、资产字段可见性
- 动态菜单与按钮权限：后端接口逐个校验权限码，前端菜单和按钮仅作展示控制

### 2. 组织与人员

- 部门树的新增、编辑、删除，支持层级关系
- 用户列表、详情、新增、编辑、启用/停用、重置密码、软删除；列表按部门与数据范围过滤
- 用户 Excel 批量导入（下载模板、逐行校验、返回失败行与原因）
- AD / LDAP 域控同步：服务器地址、端口、SSL、StartTLS、Base DN、绑定账号、用户/部门过滤器、属性映射、默认角色、同步周期
- 域控连接测试、手动同步、定时同步、同步日志（部门/用户新增、更新、停用数量）
- 域账号登录；域控连接异常时可回退到本地密码校验（需账号已设置本地密码）

### 3. 资产主数据

- 资产分类树：支持多层级、安全库存、启用/停用；分类由管理员按需创建（如硬件、软件、配件、耗材）
- 分类自定义字段：文本、数字、日期、下拉选项，支持必填与选项配置
- 资产型号：所属分类、品牌、规格、单位、折旧月数、残值率
- 资产分类 Excel 批量导入

### 4. 资产台账

- 资产新增、编辑、软删除，自动生成资产编号（`ASSET_NO_PREFIX` / `ASSET_NO_PATTERN` 可配置）
- 台账新增的资产初始为「待入库」；通过台账的「入库」操作确认后进入「在库」，之后才可发起领用或借用
- 台账字段：序列号、MAC 地址、所属部门、责任人、存放位置、供应商、购置日期、采购价格、保修到期、自定义字段、备注
- 资产附件上传、下载、删除
- 资产操作时间线、状态变更历史
- 勾选资产批量编辑
- 资产台账 Excel 导出；资产 Excel 批量导入
- 全局搜索：资产编号、序列号；有组织查看权限时还可搜索人员与部门
- 数据范围过滤与字段级可见性控制；编辑使用 `version` 乐观锁防止并发覆盖

### 5. 资产入库与库存

- 采购入库与其他入库单
- 单张入库单支持多行、每行数量、单价、保修到期、供应商、部门、存放位置
- 资产编码自动生成或手工指定；支持预览下一批编码、单行内查重与全局重复校验
- 确认入库后按数量生成资产台账记录（直接进入「在库」）；支持取消未确认的入库单
- 库存总览、低库存预警（按分类安全库存）、在库资产明细与分类筛选

### 6. 领用 / 借用 / 归还

- 发起领用或借用申请，按「分类 → 型号 → 具体资产」逐级选择，只展示可领用资产
- 申请审批：未配置审批流程时默认走「部门审批 → 资产审批」，也可使用可配置审批流程
- 审批通过后由资产管理员确认出库并分配具体资产
- 归还申请与归还确认
- 我的资产、我的申请与审批进度查看
- 申请撤销、审批驳回
- 借用到期提醒

### 7. 调拨 / 维修 / 报废

- **调拨**：发起、审批、驳回、撤销、确认，确认后变更资产所属部门与责任人
- **维修**：提交报修、审批并指派维修人、开始维修、登记维修/费用记录、完成维修、验收、驳回、取消
- **报废**：发起报废（含残值）、审批、驳回、撤销、确认处置

### 8. 资产盘点

- 按部门范围（含/不含下级）和分类范围（含/不含下级）创建盘点任务
- 扫码或输入资产编码盘点，更新盘点明细
- 盘盈资产登记与删除
- 盘盈盘亏处理单提交、审批通过、驳回
- 盘点报告查看与 Excel 导出

### 9. 审批流程配置

- 按部门绑定审批流程，同一部门只能绑定一个流程；支持设置默认流程
- 多级审批（最多 10 级）
- 每级审批人支持：部门负责人（可指定层级）、指定用户、指定角色
- 审批模式支持或签、会签
- 审批人缺失时支持兜底：转资产管理员、转部门管理员、转超级管理员、自动跳过
- 流程启用/停用；申请详情展示当前步骤、审批人与完整审批进度
- 部门无可用流程时按默认流程执行；仍无可用流程时回退到系统默认审批规则

### 10. 合同管理

- 合同类型：采购合同、维保合同、租赁合同
- 合同状态：生效中、即将到期、已到期、已终止
- 新建、编辑、详情、概览统计
- 合同续签、终止
- 关联资产
- 合同到期提醒

### 11. 工作台与报表分析

- 工作台指标：资产总数、资产总值、待入库、在库、在用、闲置、维修中、待报废、已报废、30 天内保修到期、本月入库、本月领用、合同到期、闲置率
- 图表：资产状态分布、分类分布、部门分布、购置趋势（近 3 / 6 / 12 个月）、保修临期清单、最近入库
- 工作台支持期间筛选、部门筛选，并展示「我的待办」
- 报表分析：资产概览、资产清单、闲置资产、合规检查
- 合规检查覆盖：缺少责任人、缺少存放位置、缺少采购价格、缺少购置日期、缺少序列号、缺少所属部门
- 报表导出：XLSX、PDF

### 12. 待办、通知与到期提醒

- 统一待办中心，按「待我审批、待我确认、待我处理、我发起的、即将到期」分组
- 待办类型覆盖：业务申请审批、调拨审批、报废审批、维修审批、盘点盈亏审批、出库确认、归还确认、调拨确认、报废处置确认、入库确认、维修处理、维修验收、盘点执行、进行中的我的单据、借用到期提醒
- 顶部待办角标，点击可直达对应页面
- 通知中心：保修临期/已过期、合同到期、借用到期、盘点等提醒
- 到期提醒页面：汇总、明细、手动扫描
- 定时任务：每日扫描借用、合同与综合到期提醒；LDAP 定时同步；Celery 心跳
- 邮件提醒：配置 SMTP 后可发送提醒邮件，默认关闭

### 13. 审计日志

- 审计日志列表、筛选、详情
- 记录操作人、模块、动作、结果、请求上下文与变更前后值
- 登录、退出、改密及关键业务写操作均写入审计

### 14. 界面与通用能力

- 响应式布局，支持浅色 / 深色主题切换
- 动态菜单、按钮级权限控制
- 顶部全局搜索、通知中心、待办角标、修改密码入口
- 资产台账、入库、领用、库存、合同、审计等列表支持筛选条件记忆、表单草稿与列宽记忆
- Excel 模板下载与导入结果反馈

## 快速部署（Docker Compose）

### 前置要求

- Linux 服务器（推荐）或已安装 Docker 的环境
- Docker Engine 24+
- Docker Compose v2
- 服务器可访问 Docker Hub、PyPI 与 npm（或已在 `.env` 中配置可用镜像源）

### 1. 获取代码

```bash
git clone https://github.com/Lucky-0216/itam.git
cd itam
```

### 2. 配置 `.env`

```bash
cp .env.example .env
```

以下变量为必填，未配置时容器会启动失败或初始化失败：

| 变量 | 说明 |
| --- | --- |
| `SECRET_KEY` | JWT 签名密钥，必须替换为随机值 |
| `DB_PASSWORD` | 业务数据库用户密码 |
| `DB_ROOT_PASSWORD` | MySQL root 密码 |
| `DEFAULT_ADMIN_PASSWORD` | 初始管理员密码，必须自行设置 |

`DEFAULT_USER_PASSWORD` 为可选项：批量导入用户时，若导入行未逐行填写初始密码，则使用该值；未配置时必须逐行填写。

生成随机密钥与数据库密码：

```bash
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" .env
sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$(openssl rand -hex 16)|" .env
sed -i "s|^DB_ROOT_PASSWORD=.*|DB_ROOT_PASSWORD=$(openssl rand -hex 16)|" .env
```

然后编辑 `.env`，把 `DEFAULT_ADMIN_PASSWORD` 改为你自己的管理员密码（至少 8 位，且同时包含字母和数字），不要保留示例占位值：

```bash
# 示例：使用编辑器修改
vi .env
```

如服务器 80 端口已被占用，同时修改 `HTTP_PORT`（例如 `HTTP_PORT=8080`）。

### 3. 启动服务

```bash
docker compose up -d --build
docker compose ps
```

首次启动会自动完成：

1. 创建数据库、缓存、附件与日志数据卷
2. 等待数据库健康检查通过
3. 后端执行 `alembic upgrade head` 建表
4. 执行 `python -m app.initial_data` 写入初始管理员、角色、菜单与审批基础配置
5. 启动前端 Nginx、后端 API、Celery Worker 与 Celery Beat

`docker compose ps` 中所有服务应为 `running`，`backend` 与 `mysql` 应显示 `healthy`。

### 4. 访问系统

- 系统地址：`http://<服务器IP>`；若修改了 `HTTP_PORT`，则为 `http://<服务器IP>:<HTTP_PORT>`
- API 文档：`http://<服务器IP>/api/docs`（修改端口后同样需带端口）

### 5. 初始管理员

| 项目 | 值 |
| --- | --- |
| 用户名 | `admin`（可通过 `.env` 的 `DEFAULT_ADMIN_USERNAME` 修改） |
| 密码 | `.env` 中的 `DEFAULT_ADMIN_PASSWORD`（仓库不提供内置默认密码） |
| 姓名 | `.env` 中的 `DEFAULT_ADMIN_NAME`，默认「系统管理员」 |

> 首次登录后请立即通过右上角「修改密码」更换管理员密码。`DEFAULT_ADMIN_PASSWORD` 仅在首次创建管理员账号时生效，后续修改 `.env` 不会覆盖已有密码。

### 6. 首次使用顺序

部署完成后系统没有任何业务数据，请按以下顺序初始化：

1. 系统管理 → 组织架构：创建部门、用户
2. 基础数据 → 资产分类：创建分类与自定义字段
3. 基础数据 → 型号管理：创建资产型号
4. 资产生命周期 → 资产入库：创建入库单并确认入库，系统自动生成资产台账
5. 按需配置角色权限、审批流程、合同与提醒参数

## 服务组成

| 服务 | 作用 | 端口 |
| --- | --- | --- |
| `mysql` | MySQL 8.0 数据库 | 仅容器网络内 `3306` |
| `redis` | 令牌存储、Celery Broker | 仅容器网络内 `6379` |
| `backend` | FastAPI API、迁移与初始化 | 仅容器网络内 `8000` |
| `celery-worker` | 异步任务执行 | 无对外端口 |
| `celery-beat` | 定时任务调度 | 无对外端口 |
| `frontend` | Nginx 静态站点与 `/api` 反向代理 | 宿主机 `${HTTP_PORT:-80}` → 容器 `80` |

所有服务位于 `itam-net` 网络，仅前端端口对外暴露。

## 数据库迁移与初始化

后端容器每次启动都会自动执行迁移和初始化，通常无需手工操作。

```bash
# 查看当前迁移版本
docker compose exec backend alembic current

# 手动升级到最新版本
docker compose exec backend alembic upgrade head

# 重新执行幂等初始化（只补齐管理员、角色、菜单与基础配置）
docker compose exec backend python -m app.initial_data
```

默认配置下，初始化脚本不会创建部门、分类、型号、资产、入库单、申请单、审批实例、合同等业务数据；重复执行也不会重复插入已有配置。

## 常用运维

```bash
# 服务状态与日志
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f celery-worker

# 重启单个服务
docker compose restart backend

# 更新代码后重建并启动
git pull
docker compose up -d --build

# 备份数据库
docker compose exec mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction "$MYSQL_DATABASE"' > itam-backup.sql

# 停止服务（保留数据卷）
docker compose down

# 危险：停止并删除所有数据卷，仅在确认丢弃全部数据时使用
docker compose down -v
```

数据卷：

| 卷名 | 内容 |
| --- | --- |
| `mysql_data` | MySQL 数据文件 |
| `redis_data` | Redis AOF 数据 |
| `uploads_data` | 资产附件 |
| `app_logs` | 应用日志与 Celery Beat 调度文件 |

## 关键配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | 无（必填） | JWT 签名密钥 |
| `DB_NAME` / `DB_USER` | `itam` / `itam` | 数据库名与业务用户 |
| `DB_PASSWORD` | 无（必填） | 业务数据库密码 |
| `DB_ROOT_PASSWORD` | 无（必填） | MySQL root 密码 |
| `DEFAULT_ADMIN_USERNAME` | `admin` | 初始管理员用户名 |
| `DEFAULT_ADMIN_PASSWORD` | 无（必填） | 初始管理员密码 |
| `DEFAULT_ADMIN_NAME` | `系统管理员` | 初始管理员姓名 |
| `DEFAULT_USER_PASSWORD` | 空 | 批量导入用户的默认初始密码；为空时必须逐行填写 |
| `HTTP_PORT` | `80` | 前端对外端口 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access Token 有效期（分钟） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh Token 有效期（天） |
| `CORS_ORIGINS` | `http://localhost,http://127.0.0.1:5173` | 允许的跨域来源，多个用逗号分隔 |
| `ASSET_NO_PREFIX` | `ITAM` | 资产编号前缀 |
| `ASSET_NO_PATTERN` | `{prefix}-{year}{month}-{seq:04d}` | 资产编号规则，支持 `{prefix}` `{year}` `{month}` `{seq}` |
| `SEED_SAMPLE_DATA` | `false` | 仅本地演示用；为 `true` 时写入示例部门、分类、型号，不会写入资产、单据或审批实例 |
| `WARRANTY_REMINDER_DAYS` | `30` | 保修到期提醒窗口（天） |
| `CONTRACT_REMINDER_DAYS` | `30` | 合同到期提醒窗口（天） |
| `BORROW_REMINDER_DAYS` | `3` | 借用到期提醒窗口（天） |
| `INVENTORY_REMINDER_DAYS` | `3` | 盘点到期提醒窗口（天） |
| `REMINDER_EMAIL_ENABLED` | `false` | 是否启用邮件提醒 |
| `SMTP_HOST` / `SMTP_PORT` | 空 / `587` | SMTP 服务器配置 |
| `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | 空 | SMTP 认证与发件人 |
| `SMTP_USE_TLS` | `true` | 是否使用 STARTTLS |
| `REMINDER_EMAIL_TO` | 空 | 提醒收件人，多个用逗号分隔 |
| `PIP_INDEX_URL` | 清华 PyPI 镜像 | 后端构建镜像源 |
| `NPM_REGISTRY` | npmmirror | 前端构建镜像源 |

## 本地开发

推荐 Python 3.12、Node.js 20.19+ / 22.12+。

后端（SQLite + 内存令牌存储，适合脱离 MySQL 调试）：

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Windows Git Bash / Linux: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

export DATABASE_URL="sqlite+aiosqlite:///./dev.db"
export TOKEN_STORE=memory
export SECRET_KEY="local-dev-secret-key-change-me-0123456789"
export DEFAULT_ADMIN_PASSWORD="LocalDevPass2026"

# Alembic 迁移以 MySQL 为目标；SQLite 本地调试直接按模型建表
python - <<'PY'
import asyncio

from app.core.database import engine
from app.models import Base


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(main())
PY

python -m app.initial_data
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`，Vite 已将 `/api` 代理到 `http://127.0.0.1:8000`。

## 目录结构

```
itam/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # 认证、组织、权限、资产、业务、报表等接口
│   │   ├── core/            # 配置、安全、状态机、枚举、权限常量
│   │   ├── models/          # SQLAlchemy 模型
│   │   ├── schemas/         # Pydantic 请求与响应模型
│   │   ├── services/        # 业务服务
│   │   ├── repositories/    # 数据访问
│   │   └── tasks/           # Celery 定时任务
│   ├── alembic/versions/    # 数据库迁移
│   ├── entrypoint.sh        # 迁移、初始化、启动 API
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/             # 接口封装
│   │   ├── components/      # 布局与通用组件
│   │   ├── views/           # 业务页面
│   │   ├── stores/          # Pinia 状态
│   │   ├── router/          # 路由与权限守卫
│   │   └── types/           # TypeScript 类型
│   ├── nginx.conf
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## 安全与一致性约束

- 权限判断只在后端可信：接口校验权限码，查询层按数据范围过滤；隐藏菜单不等于接口不可访问。
- 令牌安全：Refresh Token 单次使用并轮换；退出、改密、重置密码会使旧令牌立即失效。
- 审计：关键操作与业务写入在同一事务内记录操作人与变更前后值。
- 资产业务：状态只能由业务动作驱动；关键操作使用数据库事务与 `version` 乐观锁；历史记录只追加，不做物理覆盖。
- 敏感配置：`.env` 已被 `.gitignore` 排除，请勿提交真实密码、密钥或域控地址。

## 部署后自检

```bash
# 1. 管理员登录
curl -s -X POST http://<服务器IP>/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<你设置的密码>"}'

# 2. 业务数据应为空（使用登录返回的 access_token）
curl -s http://<服务器IP>/api/v1/assets \
  -H "Authorization: Bearer <access_token>"

curl -s http://<服务器IP>/api/v1/asset-requests/review \
  -H "Authorization: Bearer <access_token>"

# 3. 工作台指标应为 0
curl -s http://<服务器IP>/api/v1/dashboard/summary \
  -H "Authorization: Bearer <access_token>"
```
