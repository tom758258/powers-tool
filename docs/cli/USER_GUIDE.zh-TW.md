# Keysight Power CLI 使用者指南

本指南針對取得已建置之 CLI 執行檔或已安裝 `keysight-power` 命令的操作員，說明如何控制支援的 Keysight 直流電源供應器。重點涵蓋常規的實機 (live) 工作流程、資源選擇與安全優先檢查。有關開發人員環境設定、詳細指令參考與自動化細節，請參見 [CLI README](README.zh-TW.md)。

## 啟動 CLI

在包含 CLI 執行檔的資料夾中開啟 PowerShell 並檢查：

```powershell
.\keysight-power.exe --version
```

發佈資料夾可能包含帶有版本號的執行檔名稱，例如：

```text
keysight-power-<version>.exe
```

如果您的發佈資料夾使用的是帶有版本號的執行檔，請在以下的命令中使用該檔名。開發人員或簽出原始碼的使用者請參閱 [CLI README](README.zh-TW.md) 以了解虛擬環境、模組、驗證與建置命令。

若為已安裝的命令，請將 `.\keysight-power.exe` 替換為 `keysight-power`：

```powershell
keysight-power --version
```

## 首次實機檢查 (First Live Check)

在檢查新電腦、VISA runtime、連線或電源供應器設定時，請使用此流程。

1. 確認該儀器可安全地進行查詢，且任何連接的受測物 (DUT) 均能承受現有的輸出狀態。
2. 僅列出目前能回應 `*IDN?` 的 VISA 資源：

```powershell
.\keysight-power.exe list-resources --live-only
```

3. 複製目標儀器確切的資源字串，並設定工作階段變數：

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
```

4. 執行唯讀的身分檢查：

```powershell
.\keysight-power.exe verify --resource "$env:KEYSIGHT_POWER_RESOURCE" --log-scpi
```

5. 在執行任何輸出動作前，進行唯讀的測量或狀態檢查：

```powershell
.\keysight-power.exe measure --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --log-scpi
.\keysight-power.exe read-status --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
```

對於實機命令，請使用明確的資源字串。請勿依賴腳本或無人值守的工作流程來猜測應使用哪台儀器。

## 資源列表

對於正常的實機使用，建議使用：

```powershell
.\keysight-power.exe list-resources --live-only
```

單純的 `list-resources` 是被動的 VISA 探索。當裝置斷線或無法使用時，它可能會顯示過時的快取資源。`--live-only` 會開啟每個找到的資源，查詢 `*IDN?`，並只印出有回應的資源。

診斷過時項目時請使用 `--verify`，因為它會同時回報實機存活與連線失敗的資源：

```powershell
.\keysight-power.exe list-resources --verify
```

將結果複製到自動化流程時，請加上 `--json`：

```powershell
.\keysight-power.exe list-resources --live-only --json
```

## 資源環境變數

使用環境變數可以簡化在同一個工作階段中複製與執行多個命令的操作：

```powershell
$env:KEYSIGHT_POWER_RESOURCE = "USB0::...::INSTR"
$env:KEYSIGHT_POWER_ASRL_RESOURCE = "ASRL1::INSTR"
```

請注意：
* `$env:KEYSIGHT_POWER_RESOURCE` 用於通用的實機 USB/LAN 範例。
* `$env:KEYSIGHT_POWER_ASRL_RESOURCE` 用於 E3646A RS-232 / ASRL 範例。
* 這些是為了文件方便而提供的變數，並非隱藏的 CLI 預設值。
* 實機命令仍需要明確提供 `--resource` 參數。

## E3646A RS-232 / ASRL

E3646A 在 RS-232/ASRL 上支援已實機驗證的唯讀/狀態查詢與輸出工作流程。執行任何 E3646A 實機輸出命令前，請確認實體接線已檢查完成，且要求的電壓/電流限制對連接負載是安全的。

型號支援的實機命令包括 `identify`、`measure`、`readback`、`read-status`、`output-state`、`capabilities`、`set`、`apply`、`output-on`、`output-off`、`safe-off`、`cycle-output`、`smoke-output`、`ramp`、`ramp-list` 與影響輸出的 `sequence` 步驟。`verify` 也可作為與型號無關的連線診斷，用以開啟所選資源並查詢 `*IDN?`。E3646A 使用 `INST:NSEL` 做通道預選；`OUTP ON/OFF` 是全域輸出啟用/停用行為，即使命令接受通道參數，啟用或停用輸出仍可能影響儀器整體輸出狀態。E3646A 的保護寫入、trigger 工作流程、snapshot restore、completion pulse 與 native LIST 仍維持停用。

每個 PowerShell 工作階段設定一次 ASRL 資源：

```powershell
$env:KEYSIGHT_POWER_ASRL_RESOURCE = "ASRL1::INSTR"
```

單純的 `list-resources` 通常不需要序列設定：

```powershell
keysight-power list-resources
```

如果 Keysight IO Libraries Suite / Connection Expert 已經設定好 ASRL 資源，請嘗試進行唯讀檢查而不覆寫這些設定：

```powershell
keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE"
```

若要為單一命令明確套用序列設定，請僅傳遞您要覆寫的欄位。E3646A 的出廠預設範例為 9600 baud、8 data bits、none parity、2 stop bits 與 DTR/DSR 握手，但儀器前控制板的設定可能已被修改：

```powershell
keysight-power verify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` 會發送 `SYST:REM`。`--serial-local-on-close` 會在清理時盡最大努力發送 `SYST:LOC`。這些設定會影響遠端/本機狀態，且僅在明確要求時才會發送。

實用的唯讀/狀態範例：

```powershell
keysight-power identify --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --serial-remote --serial-local-on-close
keysight-power readback --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
keysight-power measure --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
keysight-power output-state --resource "$env:KEYSIGHT_POWER_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

對於 PowerShell 中的序列讀取/寫入終止字元，請儘量使用別名：`CR`、`LF`、`CRLF` 或 `NONE`。`NONE`、省略或空白終止字元表示不覆寫 VISA 設定。

## 唯讀工作流程

驗證儀器時，請先使用唯讀命令：

```powershell
.\keysight-power.exe identify --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
.\keysight-power.exe readback --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
.\keysight-power.exe protection-status --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
.\keysight-power.exe validate-readonly --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
```

這些命令會查詢身分、程式設定點、測量值、狀態或保護狀態。它們不會刻意啟用輸出。

## 影響輸出的工作流程

影響輸出的命令需要明確指定。使用前，請確認儀器型號、通道、DUT 接線、電壓、電流限制與保護設定。

在不啟用輸出的情況下設定較低的設定點：

```powershell
.\keysight-power.exe set --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --voltage 1 --current 0.05 --json --log-scpi
```

讀回已設定的狀態：

```powershell
.\keysight-power.exe readback --resource "$env:KEYSIGHT_POWER_RESOURCE" --json --log-scpi
```

僅在確認設定點安全後才啟用輸出。對 E3646A 而言，`OUTP ON/OFF` 是全域輸出啟用/停用行為；啟用輸出前請先確認實體接線與連接負載：

```powershell
.\keysight-power.exe output-on --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --confirm --json --log-scpi
```

檢查完成後關閉輸出：

```powershell
.\keysight-power.exe output-off --resource "$env:KEYSIGHT_POWER_RESOURCE" --channel 1 --json --log-scpi
```

若要進行簡短的快速測試動作 (smoke action)，請將電壓與電流保持在低位，並使用 CLI README 中記錄的有限度命令。請勿針對未知的資源在無人值守的情況下執行輸出工作流程。

## 常用指令

| 指令 | 典型用途 |
| --- | --- |
| `list-resources --live-only` | 尋找目前能回應 `*IDN?` 的資源。 |
| `verify` | 確認單一明確資源可被開啟並回應。 |
| `identify` | 讀取型號身分。 |
| `measure` | 讀取單一通道的電壓/電流。 |
| `read-status` | 讀取輸出狀態。 |
| `readback` | 讀取程式設定點與測量值。 |
| `protection-status` | 讀取保護狀態。 |
| `validate-readonly` | 執行一次唯讀診斷。 |
| `set` | 設定電壓/電流而不啟用輸出。 |
| `output-on` / `output-off` | 明確啟用或停用輸出。 |
| `safe-off` | 使用支援的安全路徑關閉輸出。 |

## 常見問題

如果找不到 `keysight-power.exe`，請確認您位於包含 CLI 執行檔的資料夾中，並使用該資料夾中實際的檔名。

如果找不到實機存活的資源，請檢查儀器電源、USB/LAN 纜線、VISA 驅動程式可見度，以及是否有其他程式佔用了該儀器。

如果單純的 `list-resources` 顯示舊項目，請在常規操作流程改用 `--live-only` 重新執行，或使用 `--verify` 來診斷過時的 VISA 快取項目。

如果命令拒絕執行，請在重試前閱讀驗證訊息。CLI 會在執行風險動作前，刻意拒絕不支援的型號、通道、不安全的設定點，以及缺少確認的操作。

如果日誌或自動化需要 JSON 輸出，請加上 `--json`。來自 `--log-scpi` 的診斷 SCPI 日誌會分開寫入 (stderr)，讓 JSON stdout 保持可解析狀態。

## 更多 CLI 文件

- [CLI README](README.zh-TW.md)：工程建置、驗證腳本、完整指令參考、JSON 行為、worker 細節與維護者筆記。
- [Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md)：結構化的命令列輸出規則。
- [Power Worker 契約](../contracts/power-worker-contract.md)：本機 worker REST、JSONL 與產物 (artifact) 契約。
- [支援型號](../core/supported-models.md)：特定型號的支援狀態與驗證筆記。
-
