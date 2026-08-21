# 公交文旅潮汐客流预测与弹性调度智能体

基于原型界面的可运行版本：前端保持原型的布局与核心交互，业务计算由 FastAPI 提供，推演、指令、执行日志和导出记录持久化到 SQLite。地图采用 Leaflet + OpenStreetMap，并在底图不可用时自动降级为原线网示意图。

## 功能亮点

- 桂林—阳朔真实地理底图、10 个文旅节点和 4 条调度线路
- 场景与时刻联动的拥堵圈、线路满载率色阶和车辆运行效果
- 分景区 24 小时潮汐客流预测
- 感知—预测—决策—执行—评估五阶段智能体闭环
- 可解释调度指令、一键下发和打印导出
- SQLite 推演留痕与页面内近期记录查询
- 后端服务状态、数据更新时间和真实底图/示意图手动切换

## 启动

```powershell
git clone https://github.com/wojiushilyj/bus-agent-fastapi.git
cd bus-agent-fastapi
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。接口文档位于 <http://127.0.0.1:8000/api/docs>。

当前机器已经具备兼容版本的 FastAPI 和 Uvicorn 时，也可以不创建虚拟环境，直接执行最后一条启动命令。

Linux/macOS 可使用 `source .venv/bin/activate` 激活虚拟环境。

## 已实现的实际功能

- 按场景、时刻查询实时拥堵预警和线路满载率
- 按景区查询 24 小时潮汐客流预测
- 运行感知—预测—决策三阶段推演，并生成可解释调度方案
- 一键下发调度指令，记录执行状态和工具调用轨迹
- 完成效果回测，形成执行—评估闭环
- 打印/导出调度指令单并记录导出次数
- 查询历史推演：`GET /api/simulations`

## 地图配置

默认使用 OpenStreetMap 标准瓦片，并在地图右下角显示数据署名。可通过环境变量替换生产环境的瓦片服务：

```powershell
$env:MAP_TILE_URL="https://your-tile-service/{z}/{x}/{y}.png"
$env:MAP_TILE_ATTRIBUTION="地图数据提供方"
```

页面不会批量下载或预取地图瓦片；外部底图加载失败时会自动保留可交互的线网示意图。

## 数据库

默认数据库文件为 `data/bus_agent.db`，首次启动自动建表。可通过环境变量 `BUS_AGENT_DB_PATH` 指定其他位置。

核心表：

- `simulations`：每次推演的场景、时刻、预警、满载率和评估指标
- `dispatch_actions`：智能体生成及下发的调度指令
- `agent_events`：五阶段智能体工具调用与执行日志
- `export_logs`：调度指令单导出记录

## 原型保护

源原型 `20260821/公交文旅智能体原型(2).html` 仅作为只读设计依据，没有修改。复制前 SHA-256：

`1DE7C1AA2A4EA1ADF5845050D51F32BCA080BCF8DCB696475575A7D84F0F9916`

## 数据说明

当前仓库使用聚合样例数据与可解释规则模型，适合原型验证、比赛展示和接口联调。生产落地时可在 `app/engine.py` 外接景区预约、公交 GPS、刷卡、天气、活动和排班系统数据源，前端及 API 结构无需重做。
