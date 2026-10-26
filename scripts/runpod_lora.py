"""Drive a RunPod pod for LoRA training. API key is read from runpod/api_key (never printed).

  python3 scripts/runpod_lora.py gpus                      # 48 GB cards: price and availability
  python3 scripts/runpod_lora.py create --gpu "NVIDIA A40" [--disk 150] [--cloud COMMUNITY]
  python3 scripts/runpod_lora.py status <pod_id>
  python3 scripts/runpod_lora.py upload <pod_id>           # train.py, sft_render.py, data, bootstrap.sh -> /workspace/lora
  python3 scripts/runpod_lora.py run <pod_id> [THINK=1 MAX_LEN=20480 ...]   # bash bootstrap.sh (download model, start training)
  python3 scripts/runpod_lora.py log <pod_id> [n]
  python3 scripts/runpod_lora.py fetch <pod_id> <local_dir>   # /workspace/adapter -> local_dir
  python3 scripts/runpod_lora.py delete <pod_id>
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = (ROOT / "runpod/api_key").read_text().strip()
SSH_KEY = ROOT / "runpod/id_ed25519"
PUB = (ROOT / "runpod/id_ed25519.pub").read_text().strip()
V1 = "https://rest.runpod.io/v1"
IMAGE = "runpod/pytorch:1.4.1-cu1281-torch280-ubuntu2404"
CARDS = ["NVIDIA A40", "NVIDIA L40S", "NVIDIA RTX A6000", "NVIDIA RTX 6000 Ada Generation", "NVIDIA L40", "NVIDIA A100 80GB PCIe"]


def _ctx():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def api(method, url, body=None, auth=True):
    headers = {"Content-Type": "application/json", "User-Agent": "curl/8.7.1", "Accept": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {KEY}"
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {method} {url}: {e.read().decode()[:500]}")


def pod(pid):
    return api("GET", f"{V1}/pods/{pid}?includeMachine=true")


def ssh_target(pid):
    for _ in range(60):
        p = pod(pid)
        ip, pm = p.get("publicIp"), p.get("portMappings") or {}
        if p.get("desiredStatus") == "RUNNING" and ip and pm.get("22"):
            return ip, int(pm["22"])
        print("waiting for pod:", p.get("desiredStatus"), p.get("lastStatusChange"), file=sys.stderr)
        time.sleep(15)
    raise SystemExit("pod not ready")


def ssh(pid, cmd, check=True):
    ip, port = ssh_target(pid)
    return subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", str(SSH_KEY),
                           "-p", str(port), f"root@{ip}", cmd], check=check)


def scp(pid, src, dst, to_pod=True):
    ip, port = ssh_target(pid)
    base = ["scp", "-r", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", str(SSH_KEY), "-P", str(port)]
    args = base + ([src, f"root@{ip}:{dst}"] if to_pod else [f"root@{ip}:{src}", dst])
    subprocess.run(args, check=True)


def main():
    cmd = sys.argv[1]
    if cmd == "gpus":
        for cloud in ("COMMUNITY", "SECURE"):
            d = api("GET", f"https://api.runpod.io/v2/catalog/gpus?include=AVAILABILITY&product=POD&cloud={cloud}")
            for g in d.get("gpus", []):
                if g["id"] in CARDS:
                    print(f"{cloud:9s} {g['id']:32s} {g.get('memory')} GB  ${(g.get('price') or {}).get(cloud.lower())}/h  avail {g.get('availability')}")
    elif cmd == "create":
        gpu = sys.argv[sys.argv.index("--gpu") + 1]
        disk = int(sys.argv[sys.argv.index("--disk") + 1]) if "--disk" in sys.argv else 150
        cloud = sys.argv[sys.argv.index("--cloud") + 1] if "--cloud" in sys.argv else "COMMUNITY"
        body = {"name": "gemma-lora", "imageName": IMAGE, "gpuTypeIds": [gpu], "gpuCount": 1, "cloudType": cloud,
                "containerDiskInGb": disk, "volumeInGb": 0, "ports": ["22/tcp"], "supportPublicIp": True,
                "env": {"SSH_PUBLIC_KEY": PUB}, "minRAMPerGPU": 32}
        if "--dc" in sys.argv:  # comma-separated data center ids in priority order
            body["dataCenterIds"] = sys.argv[sys.argv.index("--dc") + 1].split(",")
            body["dataCenterPriority"] = "custom"
        p = api("POST", f"{V1}/pods", body)
        print("created pod", p.get("id"), "cost/h", p.get("costPerHr"), "gpu", (p.get("machine") or {}).get("gpuTypeId"))
    elif cmd == "status":
        p = pod(sys.argv[2])
        print({k: p.get(k) for k in ("id", "desiredStatus", "publicIp", "portMappings", "costPerHr", "lastStatusChange")},
              (p.get("machine") or {}).get("gpuTypeId"))
    elif cmd == "upload":
        pid = sys.argv[2]
        ssh(pid, "mkdir -p /workspace/lora/data")
        for f in ("research/lora/kernel/train.py", "research/lora/kernel/chunked_attn.py", "research/lora/runpod/bootstrap.sh"):
            scp(pid, str(ROOT / f), "/workspace/lora/")
        for f in ("research/lora/sft_messages.jsonl", "research/lora/tools.json", "research/lora/sft_render.py"):
            scp(pid, str(ROOT / f), "/workspace/lora/data/")
        ssh(pid, "ls -la /workspace/lora /workspace/lora/data")
    elif cmd == "run":
        env = " ".join(sys.argv[3:])
        ssh(sys.argv[2], f"cd /workspace/lora && {env} bash bootstrap.sh")
    elif cmd == "log":
        n = sys.argv[3] if len(sys.argv) > 3 else "30"
        ssh(sys.argv[2], f"tail -n {n} /workspace/train.log; nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader", check=False)
    elif cmd == "fetch":
        Path(sys.argv[3]).mkdir(parents=True, exist_ok=True)
        scp(sys.argv[2], "/workspace/adapter", sys.argv[3], to_pod=False)
        subprocess.run(["ls", "-la", sys.argv[3] + "/adapter"])
    elif cmd == "delete":
        api("DELETE", f"{V1}/pods/{sys.argv[2]}")
        print("deleted", sys.argv[2])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
