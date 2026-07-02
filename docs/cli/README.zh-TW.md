# Keysight Power CLI

用於控制 Keysight 直流電源供應器的 CLI 轉接器。

該 CLI 內建於單一 `keysight-powers` 發行套件中，同時保留了 `keysight_power_cli` 的 import 邊界。它提供了 `keysight-power` 主控台命令，並將操作員的命令轉接至共用的 `keysight_power_core` runtime 執行。

## 文件集

- [CLI 使用者指南](USER_GUIDE.zh-TW.md) - 操作員工作流程、即時資源選擇與安全優先檢查。
- [CLI README](README.zh-TW.md) - 工程建置、驗證腳本、詳細指令參考、自動化與維護者邊界。
- [Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md) - 命令列 JSON 封裝與 JSONL 規則。
- [Power Worker 契約](../contracts/power-worker-contract.md) - 本機 worker REST、JSONL 與產物 (artifact) 契約。
- [Power Orchestrator 工作流程](../contracts/power-orchestrator-workflows.md) - 子行程交接與結果輪詢指南。
- [命令參數契約](../contracts/commands-parameter-contract.md) - 穩定的命令參數邊界。

## 用途

本套件提供 `keysight-power` 主控台腳本、命令參數解析、JSON 封裝處理、SCPI 日誌記錄、基於 `keysight_power_core` 的命令轉接器，以及供 orchestrators/agents 使用的本機 Power Worker daemon。

影響硬體的命令保持明確且需主動啟用 (opt-in)；預設的套件測試套件在無硬體環境下執行。

一般操作員工作流程請從 [CLI 使用者指南](USER_GUIDE.zh-TW.md) 開始。此 README 將詳細指令參考、驗證路徑、JSON/JSONL 契約、範例以及針對維護者的 CLI 行為集中說明。

## 套件內容

- `keysight_power_cli.cli`: 頂層參數解析器、命令分派、JSON 封裝轉換、SCPI 日誌記錄，以及對應至 core 的 runtime 轉接器。
- `keysight_power_cli.cli_io`: 穩定的 JSON 成功/錯誤封裝輔助工具，以及選用的 `--save-json` 輸出。
- `keysight_power_cli.worker`: 本機非同步 worker 服務、設定驗證、事件發布、工作排程、產物寫入，以及 `/command`/`/stop` HTTP 端點。
- `keysight_power_cli.commands.output`: 輸出指令註冊輔助工具。
- `keysight_power_cli.commands.sequence`: 序列指令註冊與 CLI 請求轉換。
- `keysight_power_cli.commands.trigger`: 觸發指令註冊與 CLI 請求轉換。

## 安裝

從 repository 根目錄：

```powershell
pip install -e ".[all,dev]"
```

基本 Core/CLI 安裝：

```powershell
pip install .
```

主要進入點為安裝的主控台腳本：

```powershell
uv run keysight-power --version
uv run keysight-power doctor --simulate --json
```

替代的模組進入點為：

```powershell
uv run python -m keysight_power_cli.cli doctor --simulate --json
```

`--version` 會印出 `keysight-power <package-version>` 並結束，不需要子命令或開啟 VISA。

## 測試

預設 CLI 測試為無硬體測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
```

特定焦點測試套件：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli\test_cli.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli\test_worker.py -q -p no:cacheprovider
```

Pytest 預設使用已忽略的 repository-local `.tmp_pytest` 目錄，因此測試不依賴 Windows 系統暫存目錄權限。請從 repository 根目錄執行 pytest。若單次執行需要獨立覆寫 basetemp，請使用 `--basetemp .tmp_tests/<purpose>`。不要把 pytest 暫存資料或產生的測試產物寫到 `Local/`。

執行內附的無硬體回歸檢查清單：

```powershell
.\scripts\no-hardware-regression.ps1
```

### 腳本化驗證

請在 PowerShell 從 repository 根目錄執行所有腳本。每個腳本都會在 `.tmp_tests` 下寫入機器可讀的 `report.json` 與人類可讀的 `summary.md`。

| 腳本 | 硬體需求 | 用途 |
| --- | --- | --- |
| `scripts\no-hardware-regression.ps1` | 無硬體 | 執行焦點後續檢查、JSON/文件契約檢查，以及完整預設 pytest 套件。將此作為一般的無硬體回歸測試閘口。 |
| `scripts\preflight-smoke-validation.ps1` | 無硬體 | 在進行實體硬體操作前，針對 E36312A 或 EDU36311A 執行特定目標的 dry-run 與模擬器快速測試 (smoke checks)。 |
| `scripts\live-smoke-validation-check.ps1` | 實體硬體 | 執行對應的無硬體行前檢查 (preflight)，在確認後，針對明確指定的 `-Resource` 進行有限度的實機快速測試。 |
| `scripts\batch-validation.ps1` | 由開關選擇 | 僅執行所選的模擬或實機驗證工作，並寫入單一批次報告。 |

如果目前的 Windows 執行原則阻擋 `.ps1` 檔案，請針對所選腳本使用 process-local bypass：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\no-hardware-regression.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-smoke-validation.ps1 -Target E36312A
```

無硬體回歸測試會執行焦點後續檢查、JSON/文件契約檢查，以及完整預設 pytest 套件：

```powershell
.\scripts\no-hardware-regression.ps1
```

預設報告目錄為 `.tmp_tests\no_hardware_regression`。若要選擇其他 Python 執行檔或報告目錄：

```powershell
.\scripts\no-hardware-regression.ps1 -Python .\.venv\Scripts\python.exe -OutputDir .tmp_tests\my_regression
```

行前快速測試 (Smoke preflight) 僅使用 `--dry-run` 與 `--simulate`；它不會開啟 VISA 或接觸硬體：

```powershell
.\scripts\preflight-smoke-validation.ps1 -Target E36312A
.\scripts\preflight-smoke-validation.ps1 -Target EDU36311A
```

只有在需要舊版 EDU36311A 唯讀行前檢查，而不是預設的輸出快速測試行前檢查時，才搭配 `-Target EDU36311A` 傳入 `-Profile readonly`。

報告會寫入 `.tmp_tests\smoke_validation_preflight\<Target>`。

實機快速測試 (Live smoke) 永遠會先執行對應的無硬體行前檢查，並需要明確的 `-Resource` 參數。該腳本不會掃描資源、猜測資源或讀取環境預設值。請先尋找實機資源，複製確切的值，然後明確傳遞：

```powershell
.\.venv\Scripts\keysight-power.exe list-resources --live-only --json
```

需要診斷過時的 VISA 快取時，請改用 `list-resources --verify --json`。選定目標實機資源後，執行實機快速測試腳本。它會在開啟 VISA 前暫停以供確認：

```powershell
$env:E36312A_USB_RESOURCE = "USB0::...::INSTR"
$env:EDU36311A_USB_RESOURCE = "USB0::...::INSTR"

.\scripts\live-smoke-validation-check.ps1 -Target E36312A -Connection USB -Resource $env:E36312A_USB_RESOURCE
.\scripts\live-smoke-validation-check.ps1 -Target EDU36311A -Connection USB -Resource $env:EDU36311A_USB_RESOURCE
```

E36312A 與 EDU36311A 實機快速測試是常規的硬體驗收閘口。它們會先執行唯讀檢查，在不更改保護設定的情況下讀取保護狀態，將所有通道設定為 1 V / 0.05 A (輸出關閉)，接著短暫啟用 CH1、CH2 與 CH3 (每次一個通道約 500 ms)。EDU36311A 仍可使用 `-Profile readonly` 執行舊版唯讀設定檔。提供明確的 LAN VISA 資源時，也支援 `-Connection LAN`。只有在本機 VISA 設定有需求時才使用 `-Backend "@ivi"` 或其他後端。

批次驗證僅執行開關選擇的檢查。模擬資源適合在無硬體的情況下檢查批次/報告工作流程：

```powershell
.\scripts\batch-validation.ps1 `
  -RunE36312AOutput `
  -E36312AUsbResource "USB0::SIM::E36312A::INSTR" `
  -RunEDUReadOnly `
  -EDU36311AUsbResource "USB0::SIM::EDU36311A::INSTR"
```

若為真實硬體，請將模擬資源替換為明確的 VISA 資源。`-RunE36312AOutput` 會改變狀態；`-RunEDUReadOnly` 為唯讀。目前的 `-RunIntegrationPytest` 批次開關只會記錄跳過的工作，因此必要時請直接執行硬體 pytest。

### 選用的硬體 Pytest

實機快速測試腳本是操作員驗收的常規硬體過關閘口。只有當您需要更深入、可重複的硬體回歸測試、當修改的功能有對應的硬體測試、或驗證快速測試腳本涵蓋範圍以外的 SCPI、觸發、保護設定或刻意觸發保護行為時，才執行硬體 pytest。

除非傳遞明確的資源，否則硬體整合測試不包含在一般使用中。如果需要更深入的硬體 pytest，請先執行唯讀硬體套件：

```powershell
uv run python -m pytest tests\integration -q -m hardware --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A
```

會影響輸出的硬體 pytest 額外需要 `--run-output`：

```powershell
uv run python -m pytest tests\integration -q -m hardware_output --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A --run-output
```

需要時可加入 `--backend "@ivi"`。在進行任何影響輸出的執行之前，請確認預期的儀器、拔除未知的受測物 (DUT)，並驗證所要求的電壓/電流是安全的。

## 命令狀態

E36312A 與 EDU36311A 具有基於有效 `*IDN?` 回應選擇的特定型號驅動基礎。它們的 channel-list SCPI 包含在無硬體測試的涵蓋範圍內。這些型號的模擬 CLI 測量支援通道 1、2 與 3。

真實 CLI 測量會將通用儀器保留在通道 1。E36312A 與 EDU36311A 的通道 2 與 3 使用 IDN 選擇的 channel-list 測量查詢。真實 CLI 的 `set` 支援 E36312A 與 EDU36311A 的通道 1、2 與 3。它接受 `--voltage`、`--current` 或兩者。省略的設定點將保持不變；當兩者皆提供時，會先寫入電流限制再寫入電壓。它不會啟用輸出。

真實 CLI 的 `output-on` 支援 E36312A 與 EDU36311A 通道 1、2、3 及 `all`。在 `*IDN?` 之後，它會先讀回 `VOLT? (@N)` 與 `CURR? (@N)` 再發送 `OUTP ON,(@N)`。若使用 `--safety-config`，不安全的讀回設定點會在輸出啟用前被拒絕。真實 CLI 的 `output-off`、`output-state`、`safe-off`、`cycle-output`、`apply`、`smoke-output` 及僅含設定點的 `ramp` 也支援此兩種型號。`output-off`、`output-state` 與 `cycle-output` 同時接受 `--channel all`；`set`、`ramp` 與 `smoke-output` 維持單一通道命令。

真實 CLI `measure-all` 與 `trigger-pulse` 仍為 E36312A 優先命令，用於全通道測量與後面板數位觸發輸出脈波。`validate-readonly` 是 E36312A 與 EDU36311A 的一次性唯讀診斷命令。

`list-resources`、`verify`、`clear`、`error`、`measure`、`identify`、`protection-status`、`protection-set`、`clear-protection` 與 `snapshot` 現在透過共用的 core runners 執行。CLI 仍負責 argparse 處理、人類可讀文字輸出、JSON 成功/錯誤封裝、`--save-json` 以及 exit-code 對應。

`snapshot --compare PATH` 會將目前的 E36312A 快照與已儲存的 JSON 封裝或原始的 snapshot `data` 進行比較。它會忽略 `resource` 與 `read_count`，對程式設定點使用預設容差 0.001 V/A、測量電壓容差 0.05 V、測量電流容差 0.01 A，並在發現差異時退出狀態碼 `3`。

`ramp` 是 E36312A 與 EDU36311A 的僅設定點命令：它先設定電流限制，然後將電壓從 `--start-voltage` 步進到確切的 `--stop-voltage`。它不會開啟或關閉輸出，並且一律使用軟體設定點步進。EDU36311A 真實的 `ramp` 不支援完成脈波 (completion-pulse) 選項。`set`、`apply`、`output-on`、`output-off` 與 `ramp` 接受 `--settle-ms` 與 `--verify-after-write`；驗證失敗會回傳 JSON 錯誤代碼 `verification_failed` 並退出狀態碼 `3`。

`ramp-list` 透過單一 VISA session 執行 1 到 10 個有序的軟體設定點斜坡 (ramp) 區段。它會在首次寫入硬體之前，驗證完整的版本化 JSON 文件及所有產生的設定點。它不會啟用或停用輸出、使用原生 LIST 或在失敗時自動執行 safe-off。

Ramp `--completion-pulse-timing segment` 會保留一個完成脈波。`--completion-pulse-timing step` 在每次電壓寫入後會發出一個軟體的後續動作脈波，並接受 `--delay-ms 0`。後面板脈波腳位並非輸出通道。脈波工作流程僅限 E36312A，且 `*TRG` 可能會影響其他已經 arm 好的 BUS 觸發行為。

Ramp List 版本 1 可能包含全域的 `completion_pulse` 物件。內聯 (Inline) 的 `--segment` 用法接受 `--completion-pulse-timing`、`--completion-pulse-pins` 與 `--completion-pulse-polarity`；若使用 `--file`，則以文件為準，CLI 的脈波覆寫選項將被拒絕。

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
uv run keysight-power ramp-list --lint --json --file example.ramp-list.json
uv run keysight-power ramp-list --dry-run --json --file example.ramp-list.json --resource "$env:KEYSIGHT_POWER_RESOURCE"
uv run keysight-power ramp-list --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --segment 1 0.1 0 1 0.1 100 0 --segment 2 0.05 0 2 0.2 50 500
```

## Power Worker Daemon (背景服務)

Keysight Power Supply Worker 是一個本機背景服務，會監聽 localhost 並接受 HTTP 指令以非同步方式控制 Keysight 儀器。

關於 REST API、JSONL 生命週期事件與工作結果產物的完整詳細資訊，請參見 [Power Worker 契約](../contracts/power-worker-contract.md)。關於 orchestrator/agent 交接流程 (包含準備就緒事件發現與結果產物輪詢)，請參閱 [Power Orchestrator 工作流程指南](../contracts/power-orchestrator-workflows.md)。

在動態埠上以模擬模式啟動 worker：

```powershell
uv run keysight-power worker --id power_1 --mode simulate --control-port 0
```

`POST /stop` 是協作模式：handler 僅設定停止狀態並喚醒 runner。Worker 會發出結構化的 `power_cleanup` JSONL 事件，且直到 runner 清理完成前，不會發出最終的 `summary` 或停止 HTTP 伺服器。

啟動時，它會在 stdout 輸出 `ready` 事件，其中包含動態分配的控制端點。

執行僅限模擬器的 orchestrator 快速測試範例：

```powershell
.\examples\worker_orchestrator_smoke.ps1
```

## 範例

僅列出可以被開啟並透過 `*IDN?` 查詢的 VISA 資源：

```powershell
uv run keysight-power list-resources --live-only
```

正常實機操作請使用此命令。文字輸出包含每個資源的原始 IDN 回應，因此可以看到儀器型號。加上 `--log-scpi` 可顯示每次實機檢查的驗證查詢與回應。

僅列出所選後端回報的 VISA 資源字串，而不開啟它們：

```powershell
uv run keysight-power list-resources
```

這僅是被動探索：即使目前無法連線到該儀器，資源字串也可能出現在這裡。

以下實機 USB 範例請先在 PowerShell 工作階段設定 VISA 資源一次：

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
```

驗證單一資源可被開啟並透過 `*IDN?` 查詢：

```powershell
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_RESOURCE"
uv run keysight-power verify --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

透過 `*CLS` 清除儀器狀態與錯誤佇列：

```powershell
uv run keysight-power clear --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power clear --dry-run --json --resource "USB0::SIM::E36103B::INSTR"
```

讀取儀器錯誤佇列但不改變輸出狀態：

```powershell
uv run keysight-power error --resource "$env:KEYSIGHT_POWER_RESOURCE" --max-reads 20 --log-scpi
```

測量電壓與電流：

```powershell
uv run keysight-power measure --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
uv run keysight-power measure --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 2 --log-scpi
uv run keysight-power measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
```

測量所有 E36312A 通道並讀取輸出狀態：

```powershell
uv run keysight-power measure-all --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power read-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

在 E36312A 或 EDU36311A 上執行一次完整的唯讀驗證：

```powershell
uv run keysight-power validate-readonly --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi --save-json logs\validate-readonly.json
```

讀取設定的 E36312A 設定點與保護狀態：

```powershell
uv run keysight-power readback --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power protection-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

對於 E36312A 與 EDU36311A，`protection-status` 會讀取各通道的 OVP/OCP 觸發旗標。現有的總和旗標仍然可用，並計算為所選通道結果的 OR 邏輯運算。

擷取並比較 E36312A 快照 (snapshots)：

```powershell
uv run keysight-power identify --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power snapshot --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
uv run keysight-power snapshot --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --compare logs\e36312a-baseline.json
uv run keysight-power snapshot --simulate --json --redact-resource --resource "USB0::SIM::E36312A::INSTR"
uv run keysight-power snapshot-diff --summary --json --before logs\before.json --after logs\after.json
```

預覽還原計畫並儲存計畫資料而不開啟 VISA：

```powershell
uv run keysight-power restore-from-snapshot --dry-run --json --snapshot logs\before.json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --plan-json logs\restore-plan.json
```

預覽或確認 E36312A 保護動作：

```powershell
uv run keysight-power clear-protection --dry-run --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --all
uv run keysight-power clear-protection --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --all --confirm --log-scpi
uv run keysight-power protection-set --dry-run --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --ovp-voltage 5 --ocp on
uv run keysight-power protection-set --dry-run --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --ocp-delay 0.5 --ocp-delay-trigger setting-change
uv run keysight-power protection-set --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --ovp-voltage 5 --ocp on --confirm --log-scpi
```

將 E36312A 後面板數位腳位設定為觸發輸出，對一個輸出通道 arm 一組無變化的 STEP 觸發序列，並發出 `*TRG`：

```powershell
uv run keysight-power trigger-pulse --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --pin 1 --channel 1 --polarity positive --log-scpi
```

使用 `--dry-run` 在不開啟 VISA 的情況下預覽 trigger-pulse SCPI。最後發出的 `*TRG` 可能也會觸發任何已 arm 的 BUS 觸發儀器行為。真實執行時，會在影響輸出的寫入動作後檢查 `SYST:ERR?`，如果儀器回報錯誤則該指令會失敗。

原生 E36312A 觸發/LIST 命令：

```powershell
uv run keysight-power trigger-status --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all
uv run keysight-power trigger-step --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --source bus --fire --wait-complete
uv run keysight-power trigger-list --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --completion-pulse-pins 1 --fire --wait-complete
uv run keysight-power trigger-list --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --bost-list on,off --eost-list off,on --trigger-output-pins 1 --source immediate --wait-complete
uv run keysight-power trigger-fire --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --wait-complete
uv run keysight-power trigger-abort --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all
```

對於原生 BUS 觸發，`trigger-step` 與 `trigger-list` 預設僅執行 arm；加入 `--fire` 以在同一命令中發送 `*TRG`。BUS `--wait-complete` 需要 `--fire`。Immediate 來源在發送 `INIT` 時即啟動，並拒絕接受 `--fire`。僅 arm 的 LIST 需要 `--leave-trigger-configured`；沒有 `--wait-complete` 就啟動的 LIST 也需要 `--leave-trigger-configured`，否則還原動作會中止它。Trigger Step 保持其現有非等待行為。對於 `trigger-fire`，`--channel N` 僅在使用 `--wait-complete` 時才需要；它會選擇在全儀器範圍的完成等待逾時或被中斷時要 abort 的輸出通道。它不限制 `*TRG` 或完成等待的作用範圍。`trigger-pulse` 是舊有的動作後脈波輔助工具，與原生的 trigger/list 子系統是分開的。規範的 Trigger LIST 檔案與旗標接受每一步驟的 `bost_list`、`eost_list` 加上 `trigger_output_pins` 與 `trigger_output_polarity`。啟用的脈波需要明確的輸出腳位。舊版的 `--completion-pulse-pins` 仍維持最後一步的 EOST 脈波，且不能與規範欄位混用。除非選擇了 `--leave-trigger-configured`，否則等待完成後會還原執行前的觸發設定與 LIST 表格。

執行離線診斷：

```powershell
uv run keysight-power doctor --simulate --json
uv run keysight-power capabilities --simulate --json --resource "USB0::SIM::EDU36311A::INSTR" --command protection-set
uv run keysight-power safety inspect --json --explain --safety-config examples\safety-config.toml --resource-alias sim-e36103b --channel 1
```

驗證序列檔案或在不開啟 VISA 的情況下預覽確定的寫入 SCPI：

```powershell
uv run keysight-power sequence --lint --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run keysight-power sequence --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
```

Sequence YAML 檔案透過 core 套件的 PyYAML runtime 依賴項目正式支援。對於最小環境，仍保留了一個小型的內建解析器作為替代方案。

序列文件同樣接受 `{"action":"trigger-pulse","channel":1, "pins":[1],"polarity":"positive","leave_trigger_configured":false}`。預設情況會在脈波發出後還原觸發與後面板腳位設定。`leave_trigger_configured` 僅控制該還原動作；它不會讓脈波觸發保持 armed 狀態，且啟用它可能會影響後續步驟或其他 BUS 觸發。

預覽影響輸出的命令但不寫入硬體：

```powershell
uv run keysight-power set --dry-run --json --resource "USB0::SIM::E36103B::INSTR" --channel 1 --voltage 1 --current 0.05
```

在不啟用輸出的情況下設定較低的 E36312A 或 EDU36311A 設定點：

```powershell
uv run keysight-power set --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --current 0.05 --log-scpi
uv run keysight-power set --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --log-scpi
```

真實的 `set` 會先透過 `*IDN?` 確認選擇的資源為 E36312A 或 EDU36311A，然後僅寫入所要求的設定點欄位。1、2、3 以外的通道會被拒絕。

僅在設定點已經安全時，才啟用 E36312A 或 EDU36311A 的輸出：

```powershell
uv run keysight-power output-on --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
uv run keysight-power output-on --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --log-scpi
```

真實的 `output-on` 會先透過 `*IDN?` 確認資源為 E36312A 或 EDU36311A，讀取已設定的電壓/電流設定點，然後發送 `OUTP ON,(@N)`。它不會改變電壓或電流設定點。

讀回並循環切換輸出狀態：

```powershell
uv run keysight-power output-state --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
uv run keysight-power cycle-output --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --duration-ms 500 --log-scpi
uv run keysight-power cycle-output --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --duration-ms 500 --log-scpi
```

對於 `cycle-output --channel all`，CLI 會依序啟用通道 1、2 與 3，等待 `--duration-ms` 一次，然後依序停用通道 1、2 與 3。

套用較低的設定點並啟用輸出：

```powershell
uv run keysight-power apply --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --current 0.05 --log-scpi
uv run keysight-power apply --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --voltage 1 --current 0.05 --log-scpi
uv run keysight-power apply --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel all --voltage 1 --current 0.05 --no-output --log-scpi
```

斜坡步進電壓設定點，不改變輸出狀態：

```powershell
uv run keysight-power ramp --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --verify-after-write --settle-ms 200 --log-scpi
uv run keysight-power ramp --json --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.5 --current 0.05 --completion-pulse-pins 1 --log-scpi
```

加入明確的安全設定檔 (safety config)，將本機的全域限制應用於輸出計畫中：

```powershell
uv run keysight-power set --dry-run --json --safety-config examples\safety-config.toml --resource "USB0::SIM::E36103B::INSTR" --channel 1 --voltage 1 --current 0.05
```

設定檔永遠不會從當前目錄自動尋找。它僅在 `--safety-config PATH` 傳遞給 `set`、`apply`、`output-on`、`output-off` 或 `safe-off` 時使用。`--resource-alias ALIAS` 與 `--resource` 互斥，且需要明確的安全設定檔路徑。

```toml
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2, 3]

[[resources]]
alias = "sim-e36103b"
resource = "USB0::SIM::E36103B::INSTR"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
```

資源專屬欄位會逐一覆寫全域 `[safety]` 欄位。原始 `--resource` 若符合某個 `[[resources]].resource` 項目，也將套用該項目的專屬限制；否則將套用全域 `[safety]` 限制。

```powershell
uv run keysight-power set --dry-run --json --safety-config examples\safety-config.toml --resource-alias sim-e36103b --channel 1 --voltage 1 --current 0.05
```

早期獨立的範例提供了相同的被動探索與身分查詢行為：

```powershell
.\.venv\Scripts\python.exe examples\01_list_resources.py
.\.venv\Scripts\python.exe examples\02_identify.py --resource "$env:KEYSIGHT_POWER_RESOURCE"
```

在支援的 CLI 命令中加入 `--json`，以使用穩定且機器可讀的 v1 契約。診斷日誌 (例如 `--log-scpi`) 會保留在 stderr，讓 JSON stdout 保持可解析。每個 JSON 成功與錯誤封裝皆包含 `metadata.duration_ms`。

## 安全預設值

- 影響輸出的行為必須明確指定。
- 對於明確的通道 1、2 或 3，真實輸出執行已針對 E36312A 與 EDU36311A 的 `set`、`apply`、`output-on`、`output-off`、`output-state`、`cycle-output`、`safe-off`、`smoke-output` 與 `ramp` 啟用。`apply`、`output-on`、`output-off`、`output-state`、`cycle-output` 與 `safe-off` 接受 `--channel all` 並依序展開為通道 1、2 與 3。`set`、`ramp` 與 `smoke-output` 仍為單一通道命令。`output-on` 不會設定電壓或電流。
- 真實的 `measure-all`、`trigger-pulse`、`trigger-status` 與 `trigger-list` 僅為 E36312A 啟用。`status`、`readback`、`log`、`validate-readonly` 與保護命令則為 E36312A 與 EDU36311A 皆啟用。EDU36311A 的 STEP 觸發命令僅供模擬器/dry-run 計畫使用；該型號的真實觸發/LIST 執行仍被停用。
- 真實的 `clear`、`error` 與 `measure` 是安全的 I/O 命令：`clear` 發送 `*CLS` 並清除狀態/錯誤狀態，而 `error` 與 `measure` 僅執行查詢。
- `--safety-config` 需明確指定並只套用本機的計畫驗證限制；它不會啟用真實硬體輸出。
- E36312A 與 EDU36311A 的設定點也受已驗證的官方獨立通道直流輸出額定值所限制。安全設定檔只能降低這些限制。
- 真實 VISA 資源不得寫死 (hard-coded) 於被提交的版本庫檔案中。
- 硬體測試必須要求由使用者提供資源。
- 啟用輸出的範例必須先設定電流限制再設定電壓，並在清理 (cleanup) 階段關閉輸出。

## 狀態

活躍中的套件。實機的 E36312A 驗證涵蓋了唯讀 CLI 流程、安全輸出設定點流程、worker dry-run/唯讀行為，以及硬體測試指南中記錄的原生 trigger-list 流程。
