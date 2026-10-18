#!/usr/bin/env python3
"""Write a no-weights environment report for step 19."""
import argparse
import json
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path

PINS = {"torch": "2.10.0+cu128", "torchvision": "0.25.0+cu128", "transformers": "5.15.0",
        "accelerate": "1.11.0", "Pillow": "11.3.0"}

PROBE = r'''import importlib.metadata as md, json, platform, subprocess, sys
r={"python":platform.python_version(),"packages":{},"cuda":{"available":False},"classes":{}}
for n in ("torch","torchvision","transformers","accelerate","Pillow","sympy","mpmath"):
 try:r["packages"][n]=md.version(n)
 except md.PackageNotFoundError:r["packages"][n]=None
try:
 import torch
 r["cuda"]={"available":bool(torch.cuda.is_available()),"torch_cuda_build":torch.version.cuda,
             "device_count":int(torch.cuda.device_count()),
             "devices":[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}
except Exception as e:r["torch_import_error"]=type(e).__name__+": "+str(e)
try:
 import transformers
 r["transformers_version"]=transformers.__version__
 for n in ("AutoProcessor","Qwen3_5ForConditionalGeneration","AutoModelForImageTextToText"):
  try:getattr(transformers,n);r["classes"][n]=True
  except Exception as e:r["classes"][n]=type(e).__name__+": "+str(e)
except Exception as e:r["transformers_import_error"]=type(e).__name__+": "+str(e)
try:
 from transformers import AutoProcessor
 proc=AutoProcessor.from_pretrained(sys.argv[1],local_files_only=True)
 r["processor"]={"loaded_local_only":True,"class":type(proc).__name__}
except Exception as e:r["processor"]={"loaded_local_only":False,"error":type(e).__name__+": "+str(e)}
try:
 check=subprocess.run([sys.executable,"-m","pip","check"],capture_output=True,text=True,timeout=60)
 r["pip_check"]={"returncode":check.returncode,"output":(check.stdout+check.stderr)[-6000:]}
except Exception as e:r["pip_check"]={"error":type(e).__name__+": "+str(e)}
print(json.dumps(r,ensure_ascii=False))
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--status", required=True)
    p.add_argument("--env-prefix", type=Path, required=True)
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--process-file", type=Path)
    p.add_argument("--runtime", action="store_true")
    p.add_argument("--detail", default="")
    a = p.parse_args()
    model_dir = a.model_dir
    report = {"stage": "19_continue_model_setup", "created_utc": datetime.now(timezone.utc).isoformat(),
              "status": a.status, "detail": a.detail, "env_prefix": str(a.env_prefix),
              "model_dir": str(model_dir), "weights_loaded": False, "model_loaded": False,
              "packages_installed_by_probe": False, "expected_pins": PINS,
              "active_install_processes": [], "model_config": None}
    report["installed_metadata_snapshot"] = {}
    for site_packages in (a.env_prefix / "lib").glob("python*/site-packages"):
        try:
            for dist in __import__("importlib.metadata", fromlist=["distributions"]).distributions(path=[str(site_packages)]):
                try:
                    name = dist.metadata.get("Name")
                    if name and name.casefold() in {x.casefold() for x in (*PINS.keys(), "sympy", "mpmath")}:
                        report["installed_metadata_snapshot"][name] = dist.version
                except Exception:
                    continue
        except Exception as e:
            report["metadata_scan_error"] = type(e).__name__ + ": " + str(e)
    report["gpu_host_probe"] = {"performed": False}
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            proc = subprocess.run([smi, "--query-gpu=name,driver_version,memory.total,memory.free", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=15)
            report["gpu_host_probe"] = {"performed": True, "returncode": proc.returncode,
                                         "rows": [line.strip() for line in proc.stdout.splitlines() if line.strip()],
                                         "error": (proc.stderr[-2000:] if proc.returncode else None)}
        except Exception as e:
            report["gpu_host_probe"] = {"performed": True, "error": type(e).__name__ + ": " + str(e)}
    if a.process_file and a.process_file.is_file():
        report["active_install_processes"] = [x for x in a.process_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    config_path = model_dir / "config.json"
    report["model_config_file_exists"] = config_path.is_file()
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            report["model_config"] = {k: cfg.get(k) for k in ("model_type", "architectures")}
            for key in ("vision_config", "text_config"):
                val = cfg.get(key)
                report["model_config"][key] = ({k: val.get(k) for k in ("model_type", "hidden_size", "num_hidden_layers") if k in val}
                                                if isinstance(val, dict) else None)
        except Exception as e:
            report["model_config_error"] = type(e).__name__ + ": " + str(e)
    report["runtime_probe"] = {"performed": False, "weights_loaded": False}
    if a.runtime:
        py = a.env_prefix / "bin" / "python"
        if py.is_file():
            try:
                proc = subprocess.run([str(py), "-c", PROBE, str(model_dir)], capture_output=True, text=True, timeout=180)
                report["runtime_probe"] = {"performed": True, "returncode": proc.returncode,
                                           "weights_loaded": False}
                if proc.returncode == 0:
                    lines = [x for x in proc.stdout.splitlines() if x.strip()]
                    report["runtime_probe"].update(json.loads(lines[-1]) if lines else {})
                else:
                    report["runtime_probe"]["error"] = (proc.stderr or proc.stdout)[-6000:]
            except Exception as e:
                report["runtime_probe"] = {"performed": True, "error": type(e).__name__ + ": " + str(e),
                                           "weights_loaded": False}
        else:
            report["runtime_probe"]["error"] = f"Environment Python is missing: {py}"
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"REPORT_FILE={a.report}")


if __name__ == "__main__":
    main()
