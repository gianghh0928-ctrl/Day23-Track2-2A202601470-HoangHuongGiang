# Runbook 1 trang — Region chính down

Runbook phải chạy được lúc 3h sáng bởi người KHÔNG viết nó. Mỗi bước: lệnh copy-paste
được + cách biết bước đó xong.

| # | Bước | Lệnh | Biết là xong khi | Ai làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `python chaos/kill_region.py status` | `a.alive=false` hoặc `a.ready=false` 3 lần liên tiếp | SRE On-call |
| 2 | Mở incident + bấm giờ RTO | `python dr/runbook.py --primary a --target b --backend fs` | Ghi timestamp bắt đầu vào `reports/runbook-run.jsonl` | Incident Commander / On-call |
| 3 | Restore state ở region phụ | `python state/snapshot.py get --region b --backend fs` | Thông tin restore và `MANIFEST.json` ghi nhận thành công | SRE On-call |
| 4 | Scale pool warm→full | `echo full > state/region-b/pool_state` | `/readyz` của Region B trả về HTTP 200 `ready=true` | SRE On-call |
| 5 | DNS/LB cutover | `echo b > edge/active_region` | `curl localhost:8088/edge/state` trả về `active_region=b` | Infrastructure Engineer |
| 6 | Verify golden signals | `python -c "import httpx; [httpx.get('http://127.0.0.1:8088/v1/infer') for _ in range(10)]"` | P95 latency < 500ms, error rate = 0% | QA / On-call |
| 7 | Đo RTO + postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Kết quả đo RTO trả về `"rto_verdict": "PASS"` | Incident Commander |

**Rollback (failover ngược):**
- **Điều kiện Rollback**: Khi Region A sống ổn định trở lại, health check OK, và đã sync dữ liệu mới từ B về.
- **Người quyết định**: Con người quyết định, trực tiếp là trưởng nhóm (Incident Commander / Lead SRE).
- **Không bật tự động**: Không bật tự động để tránh việc Region A chưa ổn định mà đã hoạt động, rất dễ sập tiếp.
