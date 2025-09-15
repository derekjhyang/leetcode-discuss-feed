import json, pathlib
mf = pathlib.Path("data/manifest.json")
data = json.loads(mf.read_text())
print("Latest JSON path:", data.get("json_path"))
p = pathlib.Path(data.get("json_path"))
if not p.exists():
    raise SystemExit(f"JSON file {p} does not exist!")
print("JSON file exists, count:", data.get("count"))