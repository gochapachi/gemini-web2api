#!/usr/bin/env python3
"""
gemini_tunnel_client.py - Local Reverse Tunnel Worker for Gemini Web2API.

Bridges https://gemini.anagataitsolutions.in to local http://127.0.0.1:8081.
Requests arriving at the public domain are executed locally on this PC using your
residential broadband IP, completely bypassing Google's datacenter rate limits.
"""
import sys
import time
import json
import uuid
import threading
import httpx

REMOTE_SERVER = "https://gemini.anagataitsolutions.in"
LOCAL_TARGET = "http://127.0.0.1:8081"
TUNNEL_TOKEN = "anagata-sec-gemini-2026"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
NUM_WORKERS = 6

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

def check_local_server() -> bool:
    try:
        r = httpx.get(f"{LOCAL_TARGET}/", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False

def worker_loop(worker_id: str, stop_event: threading.Event):
    client = httpx.Client(timeout=45.0, headers={"User-Agent": USER_AGENT})
    while not stop_event.is_set():
        try:
            resp = client.post(
                f"{REMOTE_SERVER}/_tunnel/poll",
                headers={
                    "X-Tunnel-Token": TUNNEL_TOKEN,
                    "X-Worker-Id": worker_id,
                    "User-Agent": USER_AGENT,
                },
                content=b""
            )
            if resp.status_code == 401:
                sys.stderr.write(f"[{worker_id}] Auth Error: Invalid tunnel token. Check configuration.\n")
                time.sleep(5)
                continue
            if resp.status_code == 502 or resp.status_code == 503:
                # Server restarting
                time.sleep(2)
                continue
            if resp.status_code != 200:
                time.sleep(1)
                continue

            data = resp.json()
            if data.get("status") == "keepalive":
                continue

            job = data.get("job")
            if not job:
                continue

            job_id = job["job_id"]
            path = job.get("path", "")
            print(f"[{time.strftime('%H:%M:%S')}] [{worker_id}] >> Request received: {job.get('method')} {path} (id: {job_id[:8]})")

            def handle_job(j=job, j_id=job_id):
                try:
                    headers = dict(j.get("headers", {}))
                    # Remove hop-by-hop headers
                    for h in ["host", "content-length", "transfer-encoding", "connection"]:
                        headers.pop(h, None)
                        headers.pop(h.title(), None)

                    body = j.get("body", "")
                    content = body.encode("utf-8") if isinstance(body, str) else body

                    with httpx.Client(timeout=360.0) as local_cli:
                        with local_cli.stream(
                            method=j.get("method", "POST"),
                            url=f"{LOCAL_TARGET}{j.get('path', '')}",
                            headers=headers,
                            content=content
                        ) as local_resp:
                            reply_headers = {
                                "X-Tunnel-Token": TUNNEL_TOKEN,
                                "X-Reply-Status": str(local_resp.status_code),
                                "X-Reply-Content-Type": local_resp.headers.get("Content-Type", "application/json"),
                                "User-Agent": USER_AGENT
                            }
                            # Send chunked stream to remote server
                            with httpx.Client(timeout=360.0) as stream_cli:
                                stream_cli.post(
                                    f"{REMOTE_SERVER}/_tunnel/stream/{j_id}",
                                    headers=reply_headers,
                                    content=local_resp.iter_bytes()
                                )
                    print(f"[{time.strftime('%H:%M:%S')}] [{worker_id}] << Streamed response completed for {j_id[:8]}.")
                except Exception as ex:
                    sys.stderr.write(f"[{worker_id}] Error handling job {j_id[:8]}: {ex}\n")
                    try:
                        with httpx.Client(timeout=10.0) as stream_cli:
                            stream_cli.post(
                                f"{REMOTE_SERVER}/_tunnel/stream/{j_id}",
                                headers={
                                    "X-Tunnel-Token": TUNNEL_TOKEN,
                                    "X-Reply-Status": "502",
                                    "X-Reply-Content-Type": "application/json",
                                    "User-Agent": USER_AGENT
                                },
                                content=json.dumps({"error": {"message": f"Local bridge error: {str(ex)}"}}).encode("utf-8")
                            )
                    except Exception:
                        pass

            threading.Thread(target=handle_job, daemon=True).start()

        except httpx.RequestError:
            time.sleep(2)
        except Exception as e:
            time.sleep(1)

def main():
    print("=" * 65)
    print("  Gemini Web2API Reverse Tunnel Worker")
    print("=" * 65)
    print(f"  Remote Endpoint: {REMOTE_SERVER}")
    print(f"  Local Target:    {LOCAL_TARGET}")
    print(f"  Worker Threads:  {NUM_WORKERS}")
    print("-" * 65)

    if not check_local_server():
        print(f"[!] Warning: Local server at {LOCAL_TARGET} is not reachable.")
        print(f"    Make sure local gemini_web2api is running (e.g. python gemini_web2api.py --config config.json).")
    else:
        print(f"[*] Local Gemini server at {LOCAL_TARGET} is ONLINE and healthy.")

    stop_event = threading.Event()
    threads = []
    for i in range(1, NUM_WORKERS + 1):
        w_id = f"Worker-{i}"
        t = threading.Thread(target=worker_loop, args=(w_id, stop_event), daemon=True)
        t.start()
        threads.append(t)

    print(f"[*] Connected! Permanent URL https://gemini.anagataitsolutions.in is now active.")
    print("    Press Ctrl+C to stop.")
    print("=" * 65)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping workers...")
        stop_event.set()

if __name__ == "__main__":
    main()
