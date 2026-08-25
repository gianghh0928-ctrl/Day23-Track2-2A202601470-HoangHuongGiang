import os
import pathlib
import subprocess
import sys
import time
import httpx

root = pathlib.Path(__file__).resolve().parent.parent
os.chdir(root)
(root / "run").mkdir(exist_ok=True)
(root / "reports").mkdir(exist_ok=True)

# Stop existing processes
for pid_file in (root / "run").glob("*.pid"):
    if pid_file.exists():
        try:
            pid = pid_file.read_text().strip()
            if pid:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                else:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
        except Exception:
            pass

python_bin = sys.executable

def launch(name, cmd_args, env_vars, log_filename, pid_filename):
    log_path = root / f"run/{log_filename}"
    pid_path = root / f"run/{pid_filename}"
    err_path = root / f"run/{name}-err.log"
    if sys.platform == "win32":
        env_cmds = "".join([f'$env:{k}="{v}"; ' for k, v in env_vars.items()])
        args_str = " ".join([f'"{a}"' for a in cmd_args])
        pid_win_path = str(pid_path).replace("\\", "/")
        log_win_path = str(log_path).replace("\\", "/")
        err_win_path = str(err_path).replace("\\", "/")
        ps_cmd = f'{env_cmds} $p = Start-Process -FilePath "{python_bin}" -ArgumentList \'{args_str}\' -RedirectStandardOutput "{log_win_path}" -RedirectStandardError "{err_win_path}" -PassThru -WindowStyle Hidden; [System.IO.File]::WriteAllText("{pid_win_path}", $p.Id.ToString())'
        subprocess.run(["powershell", "-Command", ps_cmd], check=True)
    else:
        env = os.environ.copy()
        env.update(env_vars)
        f = open(log_path, "w")
        p = subprocess.Popen([python_bin] + cmd_args, env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        pid_path.write_text(str(p.pid))

launch("region-a", ["-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
       {"REGION": "a", "STATE_DIR": "state/region-a", "WARMUP_SECONDS": "6"}, "region-a.log", "region-a.pid")

launch("region-b", ["-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8002", "--log-level", "warning"],
       {"REGION": "b", "STATE_DIR": "state/region-b", "WARMUP_SECONDS": "6"}, "region-b.log", "region-b.pid")

edge_port = int(os.environ.get("EDGE_PORT", "8088"))
launch("edge", ["-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", str(edge_port), "--log-level", "warning"],
       {"EDGE_TTL_SECONDS": "5"}, "edge.log", "edge.pid")

print("Waiting for services to become ready...")
all_ok = True
for name, port in [("region-a", 8001), ("region-b", 8002), ("edge", edge_port)]:
    up = False
    url = f"http://127.0.0.1:{port}/healthz" if port != edge_port else f"http://127.0.0.1:{port}/edge/state"
    for _ in range(15):
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                up = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    if up:
        print(f"  {name} (port {port}): UP")
    else:
        print(f"  {name} (port {port}): DOWN")
        all_ok = False

if all_ok:
    try:
        r = httpx.get(f"http://127.0.0.1:{edge_port}/edge/state")
        print("Edge State:", r.json())
    except Exception as e:
        print("Edge state query error:", e)
    if "--daemon" in sys.argv:
        print("Running in daemon mode (holding processes alive)...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
else:
    print("Some services failed to start. Check run/*.log")
    sys.exit(1)
