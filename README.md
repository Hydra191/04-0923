# 载流量校正服务

按环境温度、敷设方式、回路并列数对基准载流量进行校正。Python 3.14 标准库实现，基于 `http.server`，无第三方依赖。

## 校正规则

对每条回路依次计算三个系数（**每个系数先四舍五入到两位小数**，再参与连乘）：

| 系数 | 公式 |
|---|---|
| 温度系数 | `1 - K × (ambient_c - 30)`，70 级 K=0.0089，90 级 K=0.0071 |
| 敷设系数 | 明敷 `1.00`，穿管 `0.90` |
| 并列系数 | `1 - 0.03 × (parallel - 1)`，parallel 含本回路 |

校正值 = `base_amp × 温度系数 × 敷设系数 × 并列系数`，结果**向下取整**。

## 校验规则（非法条目返回下标与原因，不影响其余条目）

- `parallel < 1`（且必须为整数）
- `ambient_c < -5` 或 `ambient_c > rating_c - 15`（70 级上限 55℃，90 级上限 75℃）
- `rating_c` 不在 `70 / 90` 枚举内
- `layout` 不在 `明敷 / 穿管` 枚举内
- 缺少必填字段或类型错误

## 启动

需要 Python 3.14（仅用标准库，更低版本通常也可运行）。

```bash
python3 main.py            # 默认监听 8000 端口
python3 main.py --port 9000
PORT=9000 python3 main.py  # 或用环境变量
```

## 接口

`POST /api/v1/ampacity/adjust`

请求体为回路清单数组（也可包在 `{"circuits": [...]}` 中）。每条回路字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `base_amp` | number | 基准载流量 |
| `ambient_c` | number | 环境温度（℃） |
| `rating_c` | int | 绝缘等级，`70` 或 `90` |
| `layout` | string | 敷设方式，`明敷` 或 `穿管` |
| `parallel` | int | 并列回路数（含本回路），≥ 1 |

### 示例请求

```bash
curl -s -X POST http://localhost:8000/api/v1/ampacity/adjust \
  -H 'Content-Type: application/json' \
  -d '[
    {"base_amp": 100, "ambient_c": 40, "rating_c": 70, "layout": "明敷", "parallel": 1},
    {"base_amp": 200, "ambient_c": 35, "rating_c": 90, "layout": "穿管", "parallel": 3},
    {"base_amp": 100, "ambient_c": 60, "rating_c": 70, "layout": "明敷", "parallel": 1}
  ]'
```

### 示例响应

```json
{
  "results": [
    {
      "index": 0,
      "base_amp": 100.0,
      "adjusted_amp": 91,
      "factors": {"temperature": 0.91, "layout": 1.0, "parallel": 1.0}
    },
    {
      "index": 1,
      "base_amp": 200.0,
      "adjusted_amp": 162,
      "factors": {"temperature": 0.96, "layout": 0.9, "parallel": 0.94}
    },
    {
      "index": 2,
      "error": "环境温度 60 超出允许范围（-5 至 55，对应 70 级）"
    }
  ]
}
```

合法条目返回 `index`、`adjusted_amp` 及三个已舍入系数；非法条目仅返回 `index` 与 `error` 原因。
