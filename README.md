# 公交文旅潮汐客流预测与弹性调度智能体

基于原型界面的可运行版本：前端保持原型的布局、视觉和交互，业务计算改由 FastAPI 提供，推演、指令、执行日志和导出记录持久化到 SQLite。

## 启动

```powershell
cd "G:\规划院\科研立项及比赛\比赛\A超”交通创新大赛\文档\bus-agent-fastapi"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。接口文档位于 <http://127.0.0.1:8000/api/docs>。

当前机器已经具备兼容版本的 FastAPI 和 Uvicorn 时，也可以不创建虚拟环境，直接执行最后一条启动命令。

## 已实现的实际功能

- 按场景、时刻查询实时拥堵预警和线路满载率
- 按景区查询 24 小时潮汐客流预测
- 运行感知—预测—决策三阶段推演，并生成可解释调度方案
- 一键下发调度指令，记录执行状态和工具调用轨迹
- 完成效果回测，形成执行—评估闭环
- 打印/导出调度指令单并记录导出次数
- 查询历史推演：`GET /api/simulations`

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
