# 公交文旅潮汐客流预测与弹性调度智能体

面向桂林—阳朔文旅公交场景的可运行全栈项目。前端延续比赛原型的布局与核心交互，FastAPI 提供客流预测、拥堵识别、弹性调度、指令下发和闭环评估接口，SQLite 保存推演、指令、智能体事件与导出记录。

当前版本：`1.2.0`

## 功能

- 桂林—阳朔真实地理底图、10 个文旅节点和 4 条调度线路
- 桂林 1、10、16、23、24 路真实道路几何，可切换线路并查看车辆轨迹变化
- 轨迹支持正反向、0.5/1/2 倍速、进度显示和动态尾迹
- 外部底图不可用时自动降级为原线网示意图
- 平日、高峰日、活动日、突发大客流四类场景
- 分景区 24 小时潮汐客流预测
- 随时刻变化的拥堵圈、线路满载率色阶和车辆运行效果
- 感知—预测—决策—执行—评估五阶段智能体闭环
- 可解释调度方案、一键下发、自动评估和打印/PDF 导出留痕
- SQLite 历史记录、状态筛选、分页和页面内推演详情
- 服务健康状态、数据时间、请求超时与离线提示
- API 参数校验、请求大小限制、统一错误响应和基础安全响应头
- 原子状态迁移：重复下发或重复评估不会写入重复事件

## 快速启动

要求 Python 3.10 或更高版本。

```powershell
git clone https://github.com/wojiushilyj/bus-agent-fastapi.git
cd bus-agent-fastapi
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Linux/macOS 激活虚拟环境：

```bash
source .venv/bin/activate
```

浏览器打开 <http://127.0.0.1:8000>，接口文档位于 <http://127.0.0.1:8000/api/docs>。

也可以安装为本地 Python 项目：

```powershell
python -m pip install -e .
```

## 配置

复制 `.env.example` 为 `.env`，按需修改，然后使用：

```powershell
python -m uvicorn app.main:app --reload --port 8000 --env-file .env
```

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BUS_AGENT_DB_PATH` | `data/bus_agent.db` | SQLite 路径；相对路径以项目根目录为基准 |
| `TRANSIT_ROUTE_DATA_PATH` | `app/data/guilin_bus_routes.json` | 桂林公交线路快照；相对路径以项目根目录为基准 |
| `MAP_TILE_URL` | OpenStreetMap 标准瓦片 | 必须包含 `{z}`、`{x}`、`{y}` |
| `MAP_TILE_ATTRIBUTION` | `© OpenStreetMap contributors` | 地图数据署名，服务端会进行 HTML 转义 |
| `MAP_MAX_ZOOM` | `19` | 最大缩放级别，允许 8—22 |
| `MAX_REQUEST_BYTES` | `65536` | 单次 HTTP 请求体上限，允许 1KB—1MB |

配置格式不合法时应用会在启动阶段直接报错，避免带着错误配置运行。

## 主要接口

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务、数据库、版本和检查时间 |
| `GET` | `/api/config` | 场景、景区、线路和地图配置 |
| `GET` | `/api/transit/routes` | 桂林公交线路列表；可重复使用 `ref` 参数筛选 |
| `GET` | `/api/transit/routes/{route_id}` | 单个 OSM 公交方向关系详情 |
| `GET` | `/api/snapshot?hour=11&scenario=peak` | 当前时刻拥堵与线路负载快照 |
| `GET` | `/api/forecast?spot_id=xs&scenario=peak` | 指定景区 24 小时预测 |
| `POST` | `/api/simulations` | 创建推演并生成调度方案 |
| `GET` | `/api/simulations` | 历史列表，支持 `limit`、`offset`、`scenario`、`status` |
| `GET` | `/api/simulations/{id}` | 推演、指令、事件和导出详情 |
| `POST` | `/api/simulations/{id}/dispatch` | 原子下发调度指令 |
| `POST` | `/api/simulations/{id}/evaluate` | 完成闭环评估；未下发时返回 409 |
| `POST` | `/api/simulations/{id}/exports` | 记录 `print` 或 `pdf` 导出 |

创建推演示例：

```json
{
  "scenario": "peak",
  "hour": 11,
  "spot_id": "xs"
}
```

输入模型禁止未知字段。参数错误统一返回 HTTP 422，并包含可定位字段的 `errors` 列表。

## 桂林公交线路与轨迹

项目内置的公交线路来自 OpenStreetMap 公交 `route` 关系，通过 Overpass API 获取并保存为本地快照。地图按真实道路折线绘制，车辆位置则在该折线上按里程进行等速推演，因此能离线稳定复现线路轨迹变化。

当前没有接入桂林公交官方实时定位接口。页面和接口都明确标注 `is_realtime_gps: false`：线路几何是真实开放地图数据，移动中的车辆位置是演示推演，不代表实际车辆 GPS 位置。

需要刷新开放地图线路快照时运行：

```powershell
python scripts/update_transit_routes.py
```

也可用 `--refs 1 10 16` 指定线路，或用 `--stdout` 只输出 JSON。更新脚本会忽略缺少可用道路几何的关系，避免用站点之间的直线冒充实际行驶路线。OpenStreetMap 数据按 ODbL 使用，地图中保留 `© OpenStreetMap contributors` 署名。

## 数据库

应用首次启动自动创建目录、表、索引并启用 WAL：

- `simulations`：推演场景、时刻、状态、预警、负载和评估指标
- `dispatch_actions`：调度指令与下发状态
- `agent_events`：五阶段智能体调用与执行轨迹
- `export_logs`：打印/PDF 导出记录

下发与评估使用 `BEGIN IMMEDIATE` 事务完成状态判断、状态更新和事件写入，可安全处理重复点击与并发请求。

## 测试

测试仅使用项目运行依赖和 Python 标准库：

```powershell
python -m compileall -q app tests scripts
python -m unittest discover -s tests -v
node --check app/static/api-client.js
```

测试覆盖规则引擎、配置边界、SQLite 表与索引、数据访问层幂等状态机、前端关键容错，以及通过真实 Uvicorn 进程执行的完整 HTTP 工作流。

## Docker

```powershell
docker build -t bus-agent-fastapi .
docker run --rm -p 8000:8000 -v bus-agent-data:/app/data bus-agent-fastapi
```

容器默认使用非 root 用户运行，数据库写入持久化卷。

## 项目结构

```text
app/
  database.py       SQLite 连接、建表和事务
  engine.py         预测、拥堵识别和调度规则
  main.py           FastAPI 路由、中间件和异常处理
  repository.py     推演持久化与原子状态迁移
  schemas.py        Pydantic 输入模型
  settings.py       环境配置解析与校验
  transit.py        桂林公交线路快照校验与查询
  data/             可随应用部署的公交线路几何快照
  static/           前端 API 与真实地图增强脚本
  templates/        调度指挥中心页面
scripts/            公交线路快照更新工具
tests/              单元测试与 HTTP 集成测试
```

## 数据与部署说明

当前预测和调度使用聚合样例数据与确定性规则模型，适合比赛展示、产品验证和接口联调；公交线路使用开放地图真实几何快照。生产接入可在 `app/engine.py` 外接景区预约、公交 GPS、刷卡、天气、活动、排班和车载终端系统。

公开部署前还应根据实际单位要求增加账号权限、操作审计、限流、HTTPS、数据库备份和正式地图服务。OpenStreetMap 标准瓦片适合低流量演示，生产环境应配置具有服务保障的地图供应商。

## 原型保护

源原型 `20260821/公交文旅智能体原型(2).html` 仅作为只读设计依据，没有修改。原文件 SHA-256：

`1DE7C1AA2A4EA1ADF5845050D51F32BCA080BCF8DCB696475575A7D84F0F9916`
