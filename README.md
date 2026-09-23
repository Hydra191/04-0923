# 载流量校正服务（Ampacity Adjust）

基于 Python 标准库 `http.server` 的单接口 HTTP 服务，对回路清单逐条做载流量校正。
环境：Python 3.14（仅用标准库，无需安装依赖；3.10+ 亦可运行）。

## 启动

```bash
python3 main.py
```

默认监听 `0.0.0.0:8000`，可用环境变量覆盖：

```bash
HOST=127.0.0.1 PORT=9000 python3 main.py
```

## 接口

### `POST /api/v1/ampacity/adjust`

请求体为 JSON 对象，`circuits` 为回路清单，每条回路字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `base_amp` | number | 基准载流量，非负 |
| `ambient_c` | number | 环境温度（℃），允许范围 -5 ~ 等级温度 - 15 |
| `rating_c` | 70 或 90 | 绝缘耐温等级；70 级 K=0.0089，90 级 K=0.0071 |
| `layout` | `明敷` / `穿管` | 敷设方式；明敷系数 1.00，穿管系数 0.90 |
| `parallel` | int | 并列数（含本回路），必须 ≥ 1 |

校正规则：

- 温度系数 = `1 - K × (ambient_c - 30)`，**舍入两位小数**
- 敷设系数：明敷 `1.00`，穿管 `0.90`
- 并列系数 = `1 - 0.03 × (parallel - 1)`，**舍入两位小数**
- 校正值 = `三个（已舍入）系数相乘 × base_amp`，结果**向下取整**

非法条目（并列数 < 1、温度越界、等级/敷设方式枚举外、缺字段等）不影响其他条目，
在响应的 `errors` 中返回其下标与原因。

### 示例请求

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ampacity/adjust \
  -H 'Content-Type: application/json' \
  -d '{
    "circuits": [
      {"base_amp": 100, "ambient_c": 35, "rating_c": 70, "layout": "明敷", "parallel": 1},
      {"base_amp": 120, "ambient_c": 40, "rating_c": 90, "layout": "穿管", "parallel": 3},
      {"base_amp": 80,  "ambient_c": 60, "rating_c": 70, "layout": "明敷", "parallel": 2},
      {"base_amp": 50,  "ambient_c": 20, "rating_c": 90, "layout": "桥架", "parallel": 0}
    ]
  }'
```

示例响应：

```json
{
  "count": 4,
  "results": [
    {
      "index": 0,
      "base_amp": 100,
      "adjusted_amp": 96,
      "factors": {"temperature": 0.96, "layout": 1.0, "parallel": 1.0}
    },
    {
      "index": 1,
      "base_amp": 120,
      "adjusted_amp": 94,
      "factors": {"temperature": 0.93, "layout": 0.9, "parallel": 0.94}
    }
  ],
  "errors": [
    {"index": 2, "reason": "ambient_c 超出允许范围 [-5, 55]（等级 70）"},
    {"index": 3, "reason": "layout 枚举外，仅支持 明敷 或 穿管"}
  ]
}
```

> 下标 3 的条目同时存在两个问题（`parallel=0`、`layout` 非法），按校验顺序返回首个原因。

## 说明

- 系数使用 `Decimal` 计算并按四舍五入保留两位小数，避免浮点误差；最终校正值向下取整。
- 服务为多线程 `http.server`，仅建议用于内网/工具场景；`Ctrl+C` 停止。
