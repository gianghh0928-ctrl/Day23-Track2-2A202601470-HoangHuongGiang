"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n: int, name: str, **kw):
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
           "step": n, "name": name, **kw}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"RUNBOOK STEP {n} ({name}):", json.dumps(rec))
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N. Đừng bỏ hàm này đi."""
    if auto:
        return True
    try:
        ans = input(f"{msg} [y/N]: ").strip().lower()
        return ans in ("y", "yes")
    except EOFError:
        return True


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """7 bước ở trên."""
    t0_runbook = time.time()

    # Step 1: xac_nhan_outage
    primary_ready = False
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{URL[primary]}/readyz")
            primary_ready = (r.status_code == 200 and r.json().get("ready"))
    except Exception:
        primary_ready = False

    step(1, "xac_nhan_outage", primary=primary, primary_ready=primary_ready, confirmed_down=not primary_ready)

    # Step 2: thong_bao_incident
    if not confirm(auto, f"Xác nhận failover từ region-{primary} sang {target}?"):
        step(2, "thong_bao_incident", confirmed=False, action="aborted")
        return {"ok": False, "reason": "aborted_by_operator"}

    step(2, "thong_bao_incident", confirmed=True, auto=auto, note="operator confirmed failover clock started")

    # Step 3: scale_gpu_pool -> Gọi failover.failover(...) MỘT LẦN DUY NHẤT
    fo_res = fo.failover(target, backend, wait=60.0)
    step(3, "scale_gpu_pool", target=target, failover_result=fo_res)

    if not fo_res.get("ok"):
        step(3, "scale_gpu_pool_failed", reason=fo_res.get("reason"))
        return {"ok": False, "failover_result": fo_res}

    # Step 4: verify_state_replica
    step(4, "verify_state_replica", target=target,
         rpo_seconds=fo_res.get("rpo_seconds"),
         docs_lost=fo_res.get("docs_lost"))

    # Step 5: dns_cutover
    step(5, "dns_cutover", target=target, ok=fo_res.get("ok"))

    # Step 6: verify_golden_signals
    latencies = []
    errors = 0
    edge_url = "http://127.0.0.1:8088/v1/infer"
    try:
        with httpx.Client(timeout=1.0) as c:
            if c.get("http://127.0.0.1:8080/edge/state").status_code == 200:
                edge_url = "http://127.0.0.1:8080/v1/infer"
    except Exception:
        edge_url = "http://127.0.0.1:8088/v1/infer"

    with httpx.Client(timeout=3.0) as c:
        for i in range(10):
            t0_req = time.time()
            try:
                r = c.get(edge_url, params={"q": f"test-{i}"})
                lat = (time.time() - t0_req) * 1000
                latencies.append(lat)
                if r.status_code != 200:
                    errors += 1
            except Exception:
                errors += 1

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    error_rate = errors / 10.0

    step(6, "verify_golden_signals", requests_sent=10, errors=errors,
         error_rate=error_rate, p95_latency_ms=round(p95, 1))

    # Step 7: post_incident
    elapsed_s = round(time.time() - t0_runbook, 2)
    step(7, "post_incident", status="COMPLETED", elapsed_s=elapsed_s,
         note="Run python tools/measure_rto.py to compute final RTO/RPO")

    return {
        "ok": True,
        "primary": primary,
        "target": target,
        "elapsed_s": elapsed_s,
        "failover_result": fo_res,
        "golden_signals": {"error_rate": error_rate, "p95_latency_ms": round(p95, 1)}
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
