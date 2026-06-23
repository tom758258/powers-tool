# Keysight Power Core

安全控制 Keysight 直流電源供應器的核心函式庫與驅動層。

Core 內建於單一 `keysight-powers` 發行套件中，同時保留了 `keysight_power_core` 的 import 邊界。它負責處理與硬體互動的行為，並由 CLI 與 WebUI 轉接器共用。

## 用途

本套件負責硬體層的型號邏輯、安全驗證、傳輸輔助工具、模擬器支援、快照 (snapshot) 處理，以及與解析器無關的序列 (sequence) runtime。它必須與 CLI 及 WebUI 套件保持獨立。

當其他 Python 套件需要直接呼叫電源供應器 runtime 時，請使用 core 套件。一般使用者通常應使用包含在同一個 `keysight-powers` 發行套件中的 `keysight-power` 主控台腳本。

## 套件內容

- `keysight_power_core.connection`: VISA 後端選擇、資源列表、身分查詢與連線輔助工具。
- `keysight_power_core.factory`: 基於 IDN 的驅動程式選擇，適用於通用 SCPI、E36312A 與 EDU36311A 儀器。
- `keysight_power_core.drivers`: 特定型號的驅動程式實作與共用的 SCPI 通道策略。
- `keysight_power_core.operations`: 輸出與設定點操作，例如 `set`、`apply`、`output-on`、`output-off`、`safe-off`、`ramp`、`ramp-list`，以及 readback/snapshot 輔助工具。
- `keysight_power_core.readonly`: 唯讀的 `status`、`readback`、`measure-all`、log 與驗證流程，包含不會開啟 VISA 的 dry-run 計畫。
- `keysight_power_core.trigger`: E36312A 觸發 (trigger)、STEP、原生 LIST、fire 與 abort 支援。
- `keysight_power_core.sequence`: 與解析器無關的序列文件載入、語法檢查 (linting)、dry-run 計畫與執行。
- `keysight_power_core.ramp_list`: 版本化的 JSON Ramp List 載入、完整的預先驗證、計畫與有序的軟體設定點執行。
- `keysight_power_core.discovery`、`instrument_io`、`protection` 與 `snapshot`: 供 CLI 與 WebUI 共用的 adapter-neutral 執行器 (runners)，用於探索、安全的儀器 I/O、保護與快照指令。
- `keysight_power_core.command_runner`: 共用路由器，供提交 parser-neutral core 請求的轉接器使用。
- `keysight_power_core.cancellation` 與 `stop_cleanup`: 協作取消、可中斷的等待、僅限 GPIB 的 local release，以及 Worker 與 WebUI 共用的結構化停止清理結果。
- `keysight_power_core.safety`: 明確的本機安全設定檔載入與計畫驗證。
- `keysight_power_core.electrical_ratings` 與 `setpoint_limits`: 已驗證的獨立通道直流輸出額定值與有效的安全限制。
- `keysight_power_core.capabilities`: 指令與型號的能力 (capability) 報告。
- `keysight_power_core.testing`: 供測試與 CLI 模擬模式使用的無硬體模擬器。

## 安裝

從 repository 根目錄：

```powershell
pip install -e ".[all,dev]"
```

基本 Core/CLI 安裝：

```powershell
pip install .
```

Runtime 安裝會解析 `pyvisa`、支援序列 YAML 的 PyYAML，並在需要時提供 Python 版本的 TOML 替代方案 (fallback)。本套件不包含主控台腳本。本專案支援 Python `>=3.10`；測試相依套件來自根目錄的 `dev` extra。

## 測試

預設的 core 測試為無硬體測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
```

在修改特定層級時，特定焦點測試套件很有用：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core\test_model_drivers.py tests\core\test_trigger.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\core\test_operations.py -q -p no:cacheprovider
```

Pytest 預設使用已忽略的 repository-local `.tmp_pytest` 目錄，因此測試不依賴 Windows 系統暫存目錄權限。請從 repository 根目錄執行 pytest。若單次執行需要獨立覆寫 basetemp，請使用 `--basetemp .tmp_tests/<purpose>`。不要把 pytest 暫存資料或產生的測試產物寫到 `Local/`。

儲存庫層級的驗證腳本也會透過 CLI 轉接器執行 core 行為。在進行實機驗證前，請先執行無硬體測試閘口：

```powershell
.\scripts\no-hardware-regression.ps1
.\scripts\preflight-smoke-validation.ps1 -Target E36312A
```

實機快速測試 (Live smoke) 與硬體 pytest 是明確且需主動啟用 (opt-in) 的硬體檢查。它們的指令、改變狀態的行為與報告位置，記錄在 [CLI README 的腳本化驗證章節](../cli/README.zh-TW.md#scripted-validation)。

## 文件

- Core 整合指南：`integration.md`
- 支援型號：`supported-models.md`
- 接收 core 封裝的 CLI JSON 契約：`../contracts/power-cli-jsonl-contract.md`
- 根目錄工作區 README：`../../README.zh-TW.md`
- CLI 驗證腳本：`../cli/README.zh-TW.md#scripted-validation`
- 命令參數契約：`../contracts/commands-parameter-contract.md`

## 狀態

活躍中的套件。E36312A 與 EDU36311A 是主要的特定型號目標。基於有效的 `*IDN?` 回應來選擇特定型號的驅動基礎。channel-list SCPI、快照/讀回解析、保護狀態處理、序列載入/計畫、安全驗證、模擬器行為以及輸出操作計畫，皆涵蓋於無硬體測試中。

E36312A 與 EDU36311A 的保護觸發讀取使用 channel-list 查詢。共用的 Core 保護狀態會保留總和旗標 (aggregate flags)，同時從所選的通道計算它們；WebUI 的 live-panel 讀取則回傳已解析的型號身分及通道本身的 OVP/OCP 觸發狀態。

E36312A 的原生觸發/LIST 行為具備無硬體測試涵蓋範圍，以及針對通道 1 的 trigger-list、arm/fire 與 trigger-fire 的實機 USB 驗證。原生 LIST 執行僅限於 `trigger-list`；Ramp 一律使用軟體設定點步進。EDU36311A 的 STEP 觸發命令僅供模擬器/dry-run 計畫使用；該型號的真實觸發/LIST 執行仍被停用。影響硬體的行為保持明確且需主動啟用 (opt-in)。

轉接器邊界刻意設計為單向：core 包含驅動程式方法、SCPI 輔助工具、模擬器選擇與 dry-run 計畫；CLI 與 WebUI 建立 `RuntimeOptions`/`OperationRequest` 物件，並將回傳的 `data` 封裝在它們自己的傳輸封裝 (transport envelopes) 中。

## 輸出工作流程脈波 (Pulses)

完成脈波 (Completion pulses) 使用 E36312A 的後面板數位腳位；後面板腳位與所選的輸出通道是分開的。Ramp 針對單一完成脈波支援 `segment` 時序，並針對每次電壓寫入 (包含最後一次寫入) 後的軟體後續動作脈波支援 `step` 時序。每一步驟 (every-step) 時序接受 `delay_ms = 0`。

Ramp List 版本 1 可選用包含 `timing`、`pins` 與 `polarity` 的文件層級 `completion_pulse` 物件。序列文件接受規範的 `trigger-pulse` 動作。軟體脈波會為觸發與數位腳位設定建立快照並進行還原，除非明確要求 `leave_trigger_configured`。它們會發送全域 `*TRG`，這可能也會觸發其他已經 armed 的 BUS 行為。
