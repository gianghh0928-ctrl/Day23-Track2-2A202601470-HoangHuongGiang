# RTO/RPO Evidence — Lab 23

Quy tắc duy nhất: mỗi con số ở đây phải trỏ được về **một dòng log thật**
(`đường/dẫn.jsonl:số_dòng`). `pytest tests/test_rto_evidence.py` sẽ mở từng file ra kiểm tra.
Con số không có evidence = trượt, bất kể các phần khác.

## 1. Drill 1 — không có DR (baseline)

| Chỉ số | Giá trị | Cách đo | Evidence |
|---|---|---|---|
| t_outage | 2026-08-25T09:54:16 | chaos kill | `chaos/chaos-events.jsonl:1` |
| Request fail đầu tiên | +2.0s | dòng `ok:false` đầu tiên sau t_outage | `reports/drill-1-nodr.jsonl:17` |
| Request thành công sau đó | không có | không có dòng `ok:true` nào sau t_outage | `reports/measure-drill-1.json` |
| RTO | `NO_RECOVERY` | `tools/measure_rto.py` | `reports/measure-drill-1.json` |

## 2. Drill 2 — có DR

| Mốc | +giây từ t_outage | Cách đo | Evidence |
|---|---|---|---|
| t_outage (mốc 0) | 0 | `action:kill` | `chaos/chaos-events.jsonl:5` |
| User thấy lỗi đầu tiên | +2.4s | dòng `ok:false` đầu | `reports/drill-2-withdr.jsonl:26` |
| Health check phát hiện | +14.8s | `to:UNHEALTHY, region:a` | `reports/health-events.jsonl:1` |
| Snapshot restore xong | +19.2s | `step:2_restore_snapshot` | `reports/failover-events.jsonl:2` |
| Region phụ ready | +19.5s | `step:4_wait_ready` | `reports/failover-events.jsonl:4` |
| DNS cutover | +19.5s | `step:5_dns_cutover` | `reports/failover-events.jsonl:5` |
| **RTO đo được** | +25.9s | dòng `ok:true` đầu sau lỗi | `reports/drill-2-withdr.jsonl:36` |

| Chỉ số | Đo được | Mục tiêu (slide §1) | Verdict |
|---|---|---|---|
| RTO — Inference API | 25.9s | 300s (5 phút) | PASS |
| RPO — Vector DB | 6.01s / 3 doc | 300s (5 phút) | PASS |

## 3. RTO của tôi gồm những gì (bắt buộc — đây là phần chấm điểm hiểu bài)

| Thành phần | Giây | Nó đến từ đâu | Giảm được bằng cách nào |
|---|---|---|---|
| Health-check detect floor | 15.0s | `interval_s × threshold` (5s × 3) trong `reports/health-events.jsonl:1` | Giảm `interval_s` xuống 2s hoặc `threshold` xuống 2 (tăng nguy cơ flapping khi mạng chập chờn) |
| Snapshot restore | 0.0s | `2_restore_snapshot` → `3_scale_pool` trong `reports/failover-events.jsonl:2` | Dùng kho lưu trữ nhị phân tốc độ cao / RAM disk hoặc replication chủ động continuous stream |
| GPU pool warm-up | 0.3s | `waited_s` ở `4_wait_ready` trong `reports/failover-events.jsonl:4` | Giữ sẵn warm pool ở Region phụ (Standby/Active-Active) để loại bỏ hoàn toàn thời gian nạp weights/warmup |
| DNS/LB TTL cache | 6.4s | `t_recovered − t_cutover` (25.9s - 19.5s) trong `reports/drill-2-withdr.jsonl:36` | Giảm DNS TTL xuống 1s hoặc dùng Global Anycast / Anycast Load Balancer có health probe trực tiếp |
