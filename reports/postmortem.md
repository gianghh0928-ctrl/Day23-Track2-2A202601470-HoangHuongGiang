# Postmortem — DR Drill Lab 23

Theo đúng template §4 "Sau Failover: Blameless Postmortem". Blameless: câu hỏi là
"hệ thống/process nào cho phép chuyện này", không phải "ai làm sai".

## 1. Timeline (mọi dòng phải có evidence path:line)

| ISO time | Sự kiện | Evidence |
|---|---|---|
| 2026-08-25T09:59:28 | Outage bắt đầu (Region A bị netblock) | `chaos/chaos-events.jsonl:5` |
| 2026-08-25T09:59:30 | User đầu tiên bị ảnh hưởng (ReadTimeout) | `reports/drill-2-withdr.jsonl:26` |
| 2026-08-25T09:59:43 | Health check alert (Region A UNHEALTHY) | `reports/health-events.jsonl:1` |
| 2026-08-25T09:59:47 | Operator confirm cutover & bắt đầu runbook | `reports/runbook-run.jsonl:2` |
| 2026-08-25T09:59:54 | Resolved (request đầu tiên OK từ Region B) | `reports/drill-2-withdr.jsonl:36` |

## 2. RTO/RPO đo được vs mục tiêu — gap ở bước nào?

- RTO mục tiêu: 300s · đo được: 25.9s · gap: 0s (đạt mục tiêu, nhanh hơn 274.1s)
- RPO mục tiêu: 300s · đo được: 6.01s (3 doc bị mất) · gap: 0s (đạt mục tiêu, nhanh hơn 293.99s)
- **Bước tốn nhiều giây nhất:** `Health-check detect floor` (15.0s, chiếm ~58% tổng RTO) — vì phải chờ kiểm tra 3 lần liên tiếp để đảm bảo không báo động nhầm.

## 3. Root cause (5 whys)

1. **Why 1**: Tại sao khách hàng gặp lỗi ReadTimeout?
   - Do Region A bị netblock khiến tiến trình serving ngưng phản hồi HTTP request.
2. **Why 2**: Tại sao mất 15 giây hệ thống mới phát hiện ra outage?
   - Do sau khi Region A xảy ra bất thường, để đảm bảo không bị nhầm, hệ thống phải chạy kiểm tra 3 lần mới chắc chắn.
3. **Why 3**: Tại sao không hạ thời gian kiểm tra xuống 1 giây để phát hiện nhanh hơn?
   - Vì nếu hạ xuống 1s sẽ rất rủi ro nếu mạng gặp vấn đề nhỏ như lag nhẹ hay nghẽn vài giây, dẫn tới chuyển vùng không cần thiết.
4. **Why 4**: Tại sao Region B phục hồi được dữ liệu chỉ trong 0.3s?
   - Do tiến trình replication ngầm đã định kỳ sao lưu snapshot Vector DB và weights lên kho lưu trữ trước thời điểm sự cố.
5. **Why 5**: Nguyên nhân cốt lõi (Root Cause):
   - Hệ thống chưa hỗ trợ đồng bộ dữ liệu thời gian thực (CDC) và chưa giữ sẵn GPU warm pool ở Region phụ, dẫn tới khoảng trễ kiểm tra và mất 3 tài liệu chưa kịp sao lưu.

## 4. Action items (có owner + deadline)

| # | Action | Owner | Deadline | Giảm RTO/RPO bao nhiêu giây |
|---|---|---|---|---|
| 1 | Giảm thời gian Health Check (tối ưu interval/threshold) | Team SRE | 1 tuần | Giảm RTO khoảng 6s |
| 2 | Giảm thời gian Replication dữ liệu | Team Data | 2 tuần | Giảm RPO khoảng 3s |
| 3 | Bật GPU Warm Pool sẵn ở Region B | Team Infra | 2 tuần | Giảm RTO warm-up 0.3s |

## 5. Ba câu hỏi bắt buộc trả lời

1. **`interval × threshold` của bạn là bao nhiêu giây? Nó chiếm bao nhiêu % RTO?**
   - `interval × threshold = 5s × 3 = 15.0 giây`.
   - Nó chiếm `15.0 / 25.9 ≈ 57.9%` tổng RTO đo được.

2. **Nếu hạ interval xuống 1s, RTO giảm mấy giây — và bạn trả giá gì (§4 flapping)?**
   - Nếu hạ xuống 1s thì phát hiện nhanh hơn (giảm được 12s RTO), nhưng lại rủi ro nếu mạng chỉ gặp vấn đề nhỏ như lag nhẹ, nghẽn vài giây. Lúc này hệ thống phát hiện 1s coi luôn là sập rồi chuyển vùng, tốn tài nguyên và gây rủi ro lớn hơn (hiện tượng flapping).

3. **Nếu outage kéo dài 6 giờ và region chính mất dữ liệu vĩnh viễn, `docs_lost` của bạn có nghĩa gì với khách hàng?**
   - `docs_lost = 3` nghĩa là do file chưa kịp sao lưu nên bị mất, người dùng sẽ phải upload lên lần nữa.
