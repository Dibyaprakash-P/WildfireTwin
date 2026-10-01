# Train U-Net, FNO and PI-FNO sequentially, then evaluate. Logs: data/models/logs/
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:WT_WORKERS = "6"
New-Item -ItemType Directory -Force data/models/logs | Out-Null
foreach ($m in @("unet", "fno", "physics_fno")) {
    & .\.venv\Scripts\python.exe -m "ml.training.train_$m" *> "data/models/logs/train_$m.log"
}
& .\.venv\Scripts\python.exe -m ml.evaluation.evaluate_models *> data/models/logs/evaluate.log
"done" | Out-File data/models/logs/ALL_DONE.txt
