#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""载流量校正服务（Python 3.14 标准库，http.server 直起）。

启动: python3 main.py [--port 8000]
接口: POST /api/v1/ampacity/adjust
"""

import json
import os
import sys
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 温度校正系数 K：按绝缘等级取值
TEMPERATURE_K = {
    70: Decimal("0.0089"),
    90: Decimal("0.0071"),
}
# 敷设校正系数
LAYOUT_FACTOR = {
    "明敷": Decimal("1.00"),
    "穿管": Decimal("0.90"),
}
REFERENCE_TEMPERATURE = Decimal("30")
PARALLEL_STEP = Decimal("0.03")
TWO_PLACES = Decimal("0.01")
MIN_AMBIENT = Decimal("-5")


def round2(value: Decimal) -> Decimal:
    """舍入到两位小数（四舍五入）。"""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def as_decimal(value, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须为数字")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{field} 必须为数字")


def adjust_one(item):
    """计算单条回路。成功返回 dict，失败抛出 ValueError（原因）。"""
    if not isinstance(item, dict):
        raise ValueError("回路条目必须为 JSON 对象")

    required = ("base_amp", "ambient_c", "rating_c", "layout", "parallel")
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError("缺少字段: " + ", ".join(missing))

    base_amp = as_decimal(item["base_amp"], "base_amp")
    ambient_c = as_decimal(item["ambient_c"], "ambient_c")

    rating_c = item["rating_c"]
    if rating_c not in TEMPERATURE_K:
        raise ValueError(f"未知的绝缘等级 rating_c={rating_c!r}（仅支持 70/90）")

    layout = item["layout"]
    if layout not in LAYOUT_FACTOR:
        raise ValueError(f"未知的敷设方式 layout={layout!r}（仅支持 明敷/穿管）")

    parallel = item["parallel"]
    if isinstance(parallel, bool) or not isinstance(parallel, int):
        raise ValueError("并列数 parallel 必须为不小于 1 的整数（含本回路）")
    if parallel < 1:
        raise ValueError("并列数 parallel 小于 1")

    max_ambient = rating_c - 15  # 70 级 -> 55，90 级 -> 75
    if ambient_c < MIN_AMBIENT or ambient_c > max_ambient:
        raise ValueError(
            f"环境温度 {ambient_c} 超出允许范围"
            f"（-5 至 {max_ambient}，对应 {rating_c} 级）"
        )

    # 三个系数各自先舍入到两位小数，再参与连乘
    temperature_factor = round2(
        Decimal("1") - TEMPERATURE_K[rating_c] * (ambient_c - REFERENCE_TEMPERATURE)
    )
    layout_factor = round2(LAYOUT_FACTOR[layout])
    parallel_factor = round2(
        Decimal("1") - PARALLEL_STEP * (parallel - 1)
    )

    product = base_amp * temperature_factor * layout_factor * parallel_factor
    adjusted_amp = int(product.to_integral_value(rounding=ROUND_FLOOR))

    return {
        "base_amp": float(base_amp),
        "adjusted_amp": adjusted_amp,
        "factors": {
            "temperature": float(temperature_factor),
            "layout": float(layout_factor),
            "parallel": float(parallel_factor),
        },
    }


def adjust_batch(payload):
    """处理整批回路，返回 results 列表（合法给校正值，非法给下标与原因）。"""
    if isinstance(payload, dict) and isinstance(payload.get("circuits"), list):
        circuits = payload["circuits"]
    elif isinstance(payload, list):
        circuits = payload
    else:
        raise ValueError("请求体必须为回路清单数组，或含 circuits 数组的对象")

    results = []
    for index, item in enumerate(circuits):
        try:
            result = adjust_one(item)
        except ValueError as exc:
            results.append({"index": index, "error": str(exc)})
        else:
            results.append({"index": index, **result})
    return results


class AmpacityHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path.split("?")[0] != "/api/v1/ampacity/adjust":
            self._send_json(404, {"error": "未找到该接口"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            payload = json.loads(raw.decode("utf-8"))
            results = adjust_batch(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(400, {"error": f"请求体不是合法 JSON: {exc}"})
            return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, {"results": results})

    def do_GET(self):
        if self.path.split("?")[0] == "/api/v1/ampacity/adjust":
            self._send_json(405, {"error": "仅支持 POST"})
        else:
            self._send_json(404, {"error": "未找到该接口"})

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    port = 8000
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    port = int(os.environ.get("PORT", port))

    server = ThreadingHTTPServer(("0.0.0.0", port), AmpacityHandler)
    print(f"载流量校正服务已启动: http://0.0.0.0:{port}/api/v1/ampacity/adjust")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
