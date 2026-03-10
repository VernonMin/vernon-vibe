# Vernon Vibe - 类 Datadog 可观测系统（简化版）

这是一个单机可运行的可观测系统原型，提供：

- 日志（Logs）采集
- 指标（Metrics）采集
- 链路（Traces）采集
- 基础仪表盘（服务热点、Trace统计、RPS趋势、最近日志）

## 快速启动

```bash
python3 server.py
```

打开：`http://localhost:8000`

点击「生成演示数据」即可看到类似 Datadog 的观测面板。

## API 示例

### 写入日志

```bash
curl -X POST http://localhost:8000/ingest/logs \
  -H "Content-Type: application/json" \
  -d '{"service":"checkout","level":"INFO","message":"order created"}'
```

### 写入指标

```bash
curl -X POST http://localhost:8000/ingest/metrics \
  -H "Content-Type: application/json" \
  -d '{"service":"checkout","name":"request_per_second","value":72}'
```

### 写入Trace

```bash
curl -X POST http://localhost:8000/ingest/traces \
  -H "Content-Type: application/json" \
  -d '{"trace_id":"t-1","span_id":"s-1","service":"checkout","operation":"GET /api/order","duration_ms":83}'
```

## 架构说明

- `server.py`: HTTP API + SQLite 存储 + 静态文件服务
- `static/index.html`: 仪表盘页面
- `static/app.js`: 拉取数据并渲染表格/趋势图
- `static/styles.css`: 深色主题风格
