import requests
import time
import tracemalloc
import random
from datetime import datetime

# Cấu hình API
API_URL = "http://127.0.0.1:8000/predict/calories"
NUM_REQUESTS = 1000

base_request_5 = {
    "sex": "male",
    "age": random.uniform(18, 60),
    "height": random.uniform(150, 190),
    "weight": random.uniform(50, 100),
    "duration": random.uniform(10, 120),
}

base_request_7 = {
    "sex": "male",
    "age": random.uniform(18, 60),
    "height": random.uniform(150, 190),
    "weight": random.uniform(50, 100),
    "duration": random.uniform(10, 120),
    "heart_rate": random.uniform(60, 180),
    "body_temp": random.uniform(36.5, 37.5)
}

def generate_random_request(use_smartwatch=False):
    req = base_request_5.copy()
    if use_smartwatch:
        req["heart_rate"] = random.uniform(60, 180)
        req["body_temp"] = random.uniform(36.5, 37.5)
    return req

def stress_test():
    print(f"BẮT ĐẦU STRESS TEST: {NUM_REQUESTS} requests vào {API_URL}")
    print(f"Thời gian bắt đầu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    tracemalloc.start()
    
    start_time = time.time()
    latencies = []
    successful_requests = 0
    failed_requests = 0
    slow_requests = []
    # Sử dụng UTF-8 để đảm bảo tiếng Việt không bị lỗi
    log_filename = f"../logs/stress_test_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    for i in range(NUM_REQUESTS):
        use_smartwatch = random.choice([True, False])
        payload = generate_random_request(use_smartwatch)
        
        req_start = time.time()
        try:
            response = requests.post(API_URL, json=payload, timeout=5)
            req_latency = (time.time() - req_start) * 1000
            
            if response.status_code == 200:
                successful_requests += 1
                latencies.append(req_latency)
                if req_latency > 100:
                    slow_requests.append({"index": i, "latency_ms": round(req_latency, 2)})
            else:
                failed_requests += 1
                latencies.append(req_latency)
        except requests.exceptions.RequestException as e:
            failed_requests += 1
            latencies.append((time.time() - req_start) * 1000)
        
        if (i + 1) % 100 == 0:
            print(f"Đã xử lý: {i + 1}/{NUM_REQUESTS} requests...")
    
    end_time = time.time()
    total_time = end_time - start_time
    
    peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Tính toán thống kê
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] if len(latencies) > 100 else max_latency
    
    # Ghi log với encoding='utf-8'
    with open(log_filename, 'w', encoding='utf-8') as f:
        f.write(f"STRESS TEST LOG - {datetime.now()}\n")
        f.write(f"Total Requests: {NUM_REQUESTS}\n")
        f.write(f"Thành công: {successful_requests}\n")
        f.write(f"Thất bại: {failed_requests}\n")
        f.write(f"Thời gian tổng: {total_time:.2f} giây\n")
        f.write(f"Tốc độ trung bình: {avg_latency:.2f} ms/request\n")
        f.write(f"Tốc độ nhanh nhất: {min_latency:.2f} ms\n")
        f.write(f"Tốc độ chậm nhất: {max_latency:.2f} ms\n")
        f.write(f"P99 Latency: {p99_latency:.2f} ms\n")
        f.write(f"RAM đỉnh (Peak): {peak_mem / 1024 / 1024:.2f} MB\n")
        
        if slow_requests:
            f.write(f"Có {len(slow_requests)} requests chậm (>100ms):\n")
            for req in slow_requests[:5]:
                f.write(f"   - Request #{req['index']}: {req['latency_ms']:.2f}ms\n")

    print(f"\nHoàn tất! Kết quả đã lưu vào {log_filename}")
    print(f"Trung bình: {avg_latency:.2f} ms | P99: {p99_latency:.2f} ms | RAM đỉnh: {peak_mem / 1024 / 1024:.2f} MB")
    
    if failed_requests > 0:
        print(f"Cảnh báo: Có {failed_requests} request thất bại!")
    if slow_requests:
        print(f"Cảnh báo: Có {len(slow_requests)} request chậm (>100ms)!")

if __name__ == "__main__":
    stress_test()