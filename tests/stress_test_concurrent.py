import asyncio
import aiohttp
import time
import random
import tracemalloc
from datetime import datetime

# Cấu hình
API_URL = "http://127.0.0.1:8000/predict/calories"
TOTAL_REQUESTS = 3000  # 3 lần chạy, mỗi lần 1000 requests
CONCURRENCY_LEVELS = [100]  # Mức độ đồng thời để test

# Mẫu request (giống script trước)
base_request_5 = {
    "sex": "male",
    "age": 25.0,
    "height": 170.0,
    "weight": 70.0,
    "duration": 30.0,
}

base_request_7 = {
    "sex": "male",
    "age": 25.0,
    "height": 170.0,
    "weight": 70.0,
    "duration": 30.0,
    "heart_rate": 75.0,
    "body_temp": 36.8
}

def generate_payload(use_smartwatch=False):
    """Tạo payload ngẫu nhiên hợp lệ"""
    if use_smartwatch:
        payload = base_request_7.copy()
        payload["age"] = random.uniform(18, 60)
        payload["height"] = random.uniform(150, 190)
        payload["weight"] = random.uniform(50, 100)
        payload["duration"] = random.uniform(10, 120)
        payload["heart_rate"] = random.uniform(60, 180)
        payload["body_temp"] = random.uniform(36.5, 37.5)
    else:
        payload = base_request_5.copy()
        payload["age"] = random.uniform(18, 60)
        payload["height"] = random.uniform(150, 190)
        payload["weight"] = random.uniform(50, 100)
        payload["duration"] = random.uniform(10, 120)
    return payload

async def make_request(session, payload, request_id):
    """Gửi một request đơn lẻ và đo latency"""
    start = time.perf_counter()
    try:
        async with session.post(API_URL, json=payload, timeout=5.0) as response:
            latency = (time.perf_counter() - start) * 1000
            if response.status == 200:
                return {"id": request_id, "latency": latency, "status": "success"}
            else:
                return {"id": request_id, "latency": latency, "status": "error", "code": response.status}
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return {"id": request_id, "latency": latency, "status": "exception", "error": str(e)}

async def run_stress_test(concurrency, total_reqs):
    """Thực hiện stress test với mức concurrency cố định"""
    print(f"\n{'='*20} BẮT ĐẦU TEST: CONCURRENCY = {concurrency} {'='*20}")
    
    tracemalloc.start()
    start_total = time.perf_counter()
    
    results = []
    semaphore = asyncio.Semaphore(concurrency)  # Giới hạn số concurrent tasks
    
    async def worker(session, payload, req_id):
        async with semaphore:
            result = await make_request(session, payload, req_id)
            results.append(result)
    
    # Tạo danh sách payloads
    payloads = [generate_payload(random.choice([True, False])) for _ in range(total_reqs)]
    
    # Tạo và chạy tasks
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i, payload in enumerate(payloads):
            tasks.append(worker(session, payload, i))
        
        # Chạy tất cả tasks đồng thời (nhưng bị giới hạn bởi semaphore)
        await asyncio.gather(*tasks)
    
    end_total = time.perf_counter()
    total_time = end_total - start_total
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Xử lý kết quả
    successful = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] != "success"]
    latencies = [r["latency"] for r in results]
    
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    
    # Tính P99
    sorted_latencies = sorted(latencies)
    p99_idx = int(len(sorted_latencies) * 0.99)
    p99_latency = sorted_latencies[p99_idx] if sorted_latencies else 0
    
    throughput = len(results) / total_time
    
    # In ra màn hình
    print(f"Tổng Requests: {len(results)}")
    print(f"Thành công: {len(successful)}")
    print(f"Thất bại: {len(failed)}")
    print(f"Thời gian tổng: {total_time:.2f} giây")
    print(f"Throughput: {throughput:.2f} req/s")
    print(f"Avg Latency: {avg_latency:.2f} ms")
    print(f"P99 Latency: {p99_latency:.2f} ms")
    print(f"Max Latency: {max_latency:.2f} ms")
    print(f"RAM Peak: {peak_mem / 1024 / 1024:.2f} MB")
    
    if failed:
        print(f"Cảnh báo: Có {len(failed)} request thất bại!")
        # In 5 lỗi đầu tiên
        for i, f in enumerate(failed[:5]):
            print(f"   - ID {f['id']}: {f['status']} ({f.get('error', f.get('code', ''))})")
    
    # Ghi log file
    log_filename = f"../logs/stress_test_concurrent_{concurrency}x_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(log_filename, 'w', encoding='utf-8') as f:
        f.write(f"STRESS TEST CONCURRENT - CONCURRENCY: {concurrency}\n")
        f.write(f"Thời gian: {datetime.now()}\n")
        f.write(f"Total Requests: {len(results)}\n")
        f.write(f"Successful: {len(successful)}\n")
        f.write(f"Failed: {len(failed)}\n")
        f.write(f"Total Time: {total_time:.2f}s\n")
        f.write(f"Throughput: {throughput:.2f} req/s\n")
        f.write(f"Avg Latency: {avg_latency:.2f} ms\n")
        f.write(f"P99 Latency: {p99_latency:.2f} ms\n")
        f.write(f"Max Latency: {max_latency:.2f} ms\n")
        f.write(f"RAM Peak: {peak_mem / 1024 / 1024:.2f} MB\n")
        if failed:
            f.write(f"Failed Requests Details:\n")
            for r in failed:
                f.write(f"  ID {r['id']}: {r['status']} - {r.get('error', r.get('code', ''))}\n")
    
    print(f"Kết quả chi tiết đã lưu vào: {log_filename}")
    
    return {
        "concurrency": concurrency,
        "throughput": throughput,
        "p99_latency": p99_latency,
        "failed_count": len(failed),
        "avg_latency": avg_latency
    }

async def main():
    print("BẮT ĐẦU STRESS TEST ĐỒNG THỜI (CONCURRENT)")
    print(f"API URL: {API_URL}")
    print(f"Total Requests per test: {TOTAL_REQUESTS // len(CONCURRENCY_LEVELS)}")
    
    all_results = []
    for level in CONCURRENCY_LEVELS:
        reqs_per_test = TOTAL_REQUESTS // len(CONCURRENCY_LEVELS)
        result = await run_stress_test(level, reqs_per_test)
        all_results.append(result)
        
        # Ngủ 2 giây để server ổn định giữa các lần test
        await asyncio.sleep(2)
    
    # Tổng kết
    print("\n" + "="*40)
    print("BÁO CÁO TỔNG KẾT")
    print("="*40)
    print(f"{'Concurrency':<15} | {'Throughput (req/s)':<20} | {'P99 Latency (ms)':<20} | {'Failed':<10}")
    print("-" * 70)
    for r in all_results:
        print(f"{r['concurrency']:<15} | {r['throughput']:<20.2f} | {r['p99_latency']:<20.2f} | {r['failed_count']:<10}")
    print("="*40)

if __name__ == "__main__":
    # Đảm bảo cài aiohttp
    try:
        import aiohttp
    except ImportError:
        print("LỖI: Chưa cài aiohttp. Hãy chạy: pip install aiohttp")
        exit(1)
    
    asyncio.run(main())