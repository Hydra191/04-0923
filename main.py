"""载流量校正服务：仅依赖 Python 标准库（Python 3.14 可直接运行）。

启动：python3 main.py
接口：POST /api/v1/ampacity/adjust
"""

import json
import os
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

K_BY_RATING = {70: Decimal("0.0089"), 90: Decimal("0.0071")}
LAYOUT_FACTOR = {"明敷": Decimal("1.00"), "穿管": Decimal("0.90")}
TEMPERATURE_LOWER = Decimal("-5")
CENT = Decimal("0.01")


def _q2(value: Decimal) -> Decimal:
    """舍入到两位小数（四舍五入）。"""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def adjust_circuit(item):
    """计算单条回路。返回 (结果 dict, None) 或 (None, 原因 str)。"""
    if not isinstance(item, dict):
        return None, "条目必须为对象"

    for field in ("base_amp", "ambient_c", "rating_c", "layout", "parallel"):
        if field not in item:
            return None, f"缺少字段: {field}"

    base_amp = item["base_amp"]
    ambient_c = item["ambient_c"]
    rating_c = item["rating_c"]
    layout = item["layout"]
    parallel = item["parallel"]

    if not _is_number(base_amp) or base_amp < 0:
        return None, "base_amp 必须为非负数字"
    if not _is_number(ambient_c):
        return None, "ambient_c 必须为数字"
    if rating_c not in K_BY_RATING:
        return None, "rating_c 枚举外，仅支持 70 或 90"
    if layout not in LAYOUT_FACTOR:
        return None, "layout 枚举外，仅支持 明敷 或 穿管"
    if not isinstance(parallel, int) or isinstance(parallel, bool):
        return None, "parallel 必须为整数"
    if parallel < 1:
        return None, "parallel 不能小于 1（并列数含本回路）"

    ambient = Decimal(str(ambient_c))
    upper = Decimal(rating_c) - Decimal(15)
    if ambient < TEMPERATURE_LOWER or ambient > upper:
        return (
            None,
            f"ambient_c 超出允许范围 [{TEMPERATURE_LOWER:f}, {upper:f}]（等级 {rating_c}）",
        )

    k = K_BY_RATING[rating_c]
    temp_factor = _q2(Decimal(1) - k * (ambient - Decimal(30)))
    layout_factor = LAYOUT_FACTOR[layout]
    parallel_factor = _q2(
        Decimal(1) - Decimal("0.03") * (parallel - 1)
    )

    adjusted = (
        Decimal(str(base_amp)) * temp_factor * layout_factor * parallel_factor
    ).to_integral_value(rounding=ROUND_FLOOR)

    return (
        {
            "base_amp": base_amp,
            "adjusted_amp": int(adjusted),
            "factors": {
                "temperature": float(temp_factor),
                "layout": float(layout_factor),
                "parallel": float(parallel_factor),
            },
        },
        None,
    )


class AmpacityHandler(BaseHTTPRequestHandler):
    server_version = "AmpacityAdjust/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?")[0] != "/api/v1/ampacity/adjust":
            self._send_json(404, {"error": "未找到该接口"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体不是合法的 JSON"})
            return

        if not isinstance(payload, dict) or not isinstance(payload.get("circuits"), list):
            self._send_json(400, {"error": "请求体必须为对象且含 circuits 列表"})
            return

        results, errors = [], []
        for index, item in enumerate(payload["circuits"]):
            result, reason = adjust_circuit(item)
            if reason is not None:
                errors.append({"index": index, "reason": reason})
            else:
                entry = {"index": index}
                entry.update(result)
                results.append(entry)

        self._send_json(
            200,
            {
                "count": len(payload["circuits"]),
                "results": results,
                "errors": errors,
            },
        )

    def do_GET(self):
        if self.path.split("?")[0] == "/api/v1/ampacity/adjust":
            self._send_json(405, {"error": "仅支持 POST"})
        else:
            self._send_json(404, {"error": "未找到该接口"})

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), AmpacityHandler)
    print(f"载流量校正服务已启动: http://{host}:{port}")
    print("接口: POST /api/v1/ampacity/adjust")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
