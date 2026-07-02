# Keysight Power CLI

用於控制 Keysight 直流電源供應器的 CLI 轉接器。

此文件是 `docs/cli/README.md` 的繁體中文操作摘要。完整工程細節、命令清單與最新範例仍以英文 README 為主；操作員工作流程請優先閱讀 [CLI 使用者指南](USER_GUIDE.zh-TW.md)。

## 文件集

- [CLI 使用者指南](USER_GUIDE.zh-TW.md) - 操作員工作流程、即時資源選擇與安全優先檢查。
- [CLI README](README.zh-TW.md) - 工程建置、驗證腳本、詳細指令參考、自動化與維護者邊界。
- [Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md) - 命令列 JSON 封裝與 JSONL 規則。
- [Power Worker 契約](../contracts/power-worker-contract.md) - 本機 worker REST、JSONL 與 artifact 契約。
- [Power Orchestrator 工作流程](../contracts/power-orchestrator-workflows.md) - 子行程交接與結果輪詢指南。
- [命令參數契約](../contracts/commands-parameter-contract.md) - 穩定的命令參數邊界。

## 安裝與基本檢查

從 repository 根目錄安裝：

```powershell
pip install -e ".[all,dev]"
pip install .
```

確認 CLI 可執行：

```powershell
uv run keysight-power --version
uv run keysight-power doctor --simulate --json
```

## 測試與驗證

預設 CLI 測試為無硬體測試：

```powershell
./.venv/Scripts/python.exe -m pytest tests/cli -q -p no:cacheprovider
```

常用無硬體回歸檢查：

```powershell
./scripts/no-hardware-regression.ps1
```

實機 smoke 腳本不會掃描資源、猜測資源或讀取環境預設值。請先尋找資源，再明確傳入 `-Resource`：

```powershell
./.venv/Scripts/keysight-power.exe list-resources --live-only --json

$env:E36312A_USB_RESOURCE = "USB0::...::INSTR"
$env:EDU36311A_USB_RESOURCE = "USB0::...::INSTR"

./scripts/live-smoke-validation-check.ps1 -Target E36312A -Connection USB -Resource $env:E36312A_USB_RESOURCE
./scripts/live-smoke-validation-check.ps1 -Target EDU36311A -Connection USB -Resource $env:EDU36311A_USB_RESOURCE
```

## 範例

### 資源搜尋與實機資源設定

僅列出可以被開啟並透過 `*IDN?` 查詢的 VISA 資源：

```powershell
uv run keysight-power list-resources --live-only
```

通用實機 USB/LAN 範例請先在 PowerShell 工作階段設定 VISA 資源一次：

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
```

驗證單一資源可被開啟並透過 `*IDN?` 查詢：

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_RESOURCE"
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

### E3646A RS-232 / ASRL 唯讀範例

E3646A 目前在 RS-232/ASRL 上僅限唯讀與狀態查詢。型號支援的命令包括 `identify`、`measure`、`readback`、`read-status`、`output-state` 與 `capabilities`。`verify` 也可作為與型號無關的連線診斷。

每個 PowerShell 工作階段設定一次 ASRL 資源：

```powershell
$env:KEYSIGHT_POWER_ASRL_RESOURCE = "ASRL1::INSTR"
```

如果 Connection Expert 已經設定並驗證 ASRL 資源，可讓 VISA 使用既有設定：

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE"
```

若要為單一命令明確套用序列設定，請只傳入要覆寫的欄位：

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` 會在開啟 ASRL 資源後發送 `SYST:REM`。`--serial-local-on-close` 會在清理時盡最大努力發送 `SYST:LOC`。這些命令會影響儀器遠端/本機狀態，且只在明確要求時發送。

常用唯讀範例：

```powershell
uv run keysight-power identify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-remote --serial-local-on-close
uv run keysight-power readback --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
uv run keysight-power measure --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
uv run keysight-power output-state --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

序列終止字元請優先使用別名 `CR`、`LF`、`CRLF` 或 `NONE`。`NONE` 表示不設定該終止字元選項；省略或空白欄位也表示不覆寫 VISA 設定。

### 唯讀指令範例

```powershell
uv run keysight-power measure --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
uv run keysight-power measure-all --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power read-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power validate-readonly --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi --save-json logs/validate-readonly.json
uv run keysight-power readback --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power protection-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

### Snapshot 與 Restore 範例

```powershell
uv run keysight-power snapshot --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power snapshot --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --compare logs/e36312a-baseline.json
uv run keysight-power snapshot-diff --summary --json --before logs/before.json --after logs/after.json
uv run keysight-power restore-from-snapshot --dry-run --json --snapshot logs/before.json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --plan-json logs/restore-plan.json
```

### Protection 與 Trigger 範例

```powershell
uv run keysight-power clear-protection --dry-run --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --all
uv run keysight-power protection-set --dry-run --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --ovp-voltage 5 --ocp on
uv run keysight-power trigger-pulse --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --pin 1 --channel 1 --polarity positive --log-scpi
uv run keysight-power trigger-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all
```

### 會影響輸出的範例

影響輸出的命令必須明確要求，且使用前需確認型號、通道、DUT 接線、電壓、電流限制與保護設定。詳細範例請參考英文 README 與 CLI 使用者指南。

### Ramp、Sequence 與模擬器範例

```powershell
uv run keysight-power ramp-list --lint --json --file example.ramp-list.json
uv run keysight-power sequence --lint --json --resource "USB0::SIM::E36312A::INSTR" --file examples/sequence-readonly.yaml
uv run keysight-power clear --dry-run --json --resource "USB0::SIM::E36103B::INSTR"
uv run keysight-power measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
uv run keysight-power doctor --simulate --json
uv run keysight-power capabilities --simulate --json --resource "USB0::SIM::EDU36311A::INSTR" --command protection-set
uv run keysight-power safety inspect --json --explain --safety-config examples/safety-config.toml --resource-alias sim-e36103b --channel 1
```

## Safety Defaults

- 影響輸出的行為必須明確要求。
- E3646A 目前只保留 RS-232 / ASRL 唯讀與狀態查詢工作流程。
- `--safety-config` 只會套用本機 plan validation 限制；它不會自動啟用硬體輸出。
- 真實 VISA resource 不應硬編碼在提交的檔案中。
- 硬體測試必須要求使用者提供 resource。
- 啟用輸出的範例必須設定安全的 current limit，並在清理時關閉輸出。

## Status

Active package. Live E36312A validation covers read-only CLI flows, output-safe setpoint flows, worker dry-run/read-only behavior, and native trigger-list flows documented in the hardware test guide.
