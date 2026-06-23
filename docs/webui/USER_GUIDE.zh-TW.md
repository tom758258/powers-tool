# Keysight Power WebUI 使用者指南

本指南針對取得已建置之 WebUI 啟動器並使用它來檢查與控制支援的 Keysight 直流電源供應器的操作員。本指南避開了開發人員細節，專注於一般的本機 WebUI 工作流程。開發人員環境設定、API 行為、驗證以及 UI 變更邊界，皆記錄於 [WebUI README](README.zh-TW.md) 與 [Web UI 變更規則](web-ui-change-rules.md)。

## 啟動 WebUI

一般使用時，請雙擊發行套件或本機建置提供的 WebUI 啟動器：

```text
keysight-power-webui-launcher.exe
```

若要從 PowerShell 確認啟動器版本：

```powershell
.\keysight-power-webui-launcher.exe --version
```

發佈資料夾可能包含帶有版本號的啟動器名稱，例如：

```text
keysight-power-webui-launcher-<version>.exe
```

在啟動器視窗中：

1. 除非該 port 已被佔用，否則請保持勾選 `Use default port 8000`。
2. 點擊 `Start` (啟動)。
3. 等待瀏覽器開啟。啟動器會在此電腦上啟動本機 WebUI 伺服器，並為您開啟瀏覽器頁面。
4. 使用完 WebUI 後，請在啟動器中點擊 `Quit` (離開)。

如果 port 8000 已被佔用，請取消勾選 `Use default port 8000`，輸入一個可用的本機 port (例如 `7999`)，然後點擊 `Start`。

如果瀏覽器沒有自動開啟，請手動開啟此網址：

```text
http://127.0.0.1:8000/
```

開發人員或簽出原始碼的使用者應參閱 [WebUI README](README.zh-TW.md) 以了解終端機指令、驗證、API 與建置細節。

WebUI 執行於與儀器連接的同一台 Windows 電腦上。它是一個本機工具，而非雲端服務。關閉瀏覽器分頁並不一定會停止伺服器；使用完畢後，請使用啟動器中的 `Quit` 或停止終端機程序。

## 畫面總覽

此頁面為儀器控制主控台。主要區域包含：

- `VISA resource`：命令工作所使用的明確儀器位址。
- `Live resource`：由「掃描裝置」(Scan Device) 工作流程探索到的資源。
- `Scan Device` (掃描裝置)：搜尋實機存活的 VISA 資源並填入選擇器。
- `Live Data` (即時資料)：唯讀的通道卡片與狀態指示燈。
- `Basic command` (基本命令)：各通道的電壓 (Voltage)、電流 (Current)、設定 (Set) 及輸出開啟 (ON) 控制項。
- `Show more commands` (顯示更多命令)：開啟進階命令列與生成的表單。
- `Job Result` (工作結果)：最近提交的工作及其狀態。
- `Result Detail` (結果詳情)：所選工作的原始 JSON 細節。

影響硬體的工作依然需要明確指定與確認。

## 首次使用

在檢查新電腦、VISA runtime、連線或電源供應器設定時，請使用此流程。

1. 確認電源供應器與連接的受測物 (DUT) 均可安全查詢。
2. 啟動 WebUI 並開啟本機瀏覽器頁面。
3. 點擊 `Scan Device`。
4. 選擇目標實機資源或將其複製到 `VISA resource`。
5. 啟動 `Live Data` 以確認唯讀通訊與通道狀態。
6. 在執行任何影響輸出的命令前，請先檢閱型號身分、輸出狀態、程式設定點以及保護狀態。
7. 只有在目標通道與設定點確認安全後，才使用 Basic command (基本命令) 或進階命令列。

當可能連接多台儀器時，請勿用猜測的方式選擇資源。

## 資源掃描

`Scan Device` (掃描裝置) 會執行啟用實機資源過濾的 WebUI 資源探索工作。它的目的是顯示目前能回應的資源，而非過時的 VISA 快取項目。

選擇資源後會將其複製到 `VISA resource` 輸入框中。您也可以手動輸入由操作員提供的已知 VISA 資源。

如果未出現實機存活的資源，請檢查儀器電源、纜線、VISA 驅動程式可見度，以及是否有其他程式佔用了該儀器。

## 即時資料 (Live Data)

`Live Data` 是一個唯讀監控器。它會定期讀取所選資源，更新通道卡片，並顯示 WebUI、命令與即時監控狀態。

在執行輸出命令前使用 Live Data 來確認：

- 預期的型號有回應；
- 測量到的電壓/電流看起來合理；
- 清楚了解目前的程式設定點；
- 確知目前的輸出狀態；
- 支援 OVP/OCP 時可看見其觸發 (trip) 狀態。

成功的實機硬體命令執行後，Live Data 可能會更新一次。它維持唯讀屬性，應被視為所顯示儀器狀態的來源真相。

## 基本命令 (Basic Commands)

Basic command 面板用於常見的各通道設定點與輸出動作。

電壓 (Voltage) 與電流 (Current) 欄位允許留空。空白欄位會被省略，並由 Core 保持不變。若要同時設定兩者，請填寫這兩個欄位並點擊該通道的 `Set`。

當有最新的 Live Data 時，ON 控制項會反映其狀態。未亮的 ON 控制項代表 OFF (關閉) 或未知；除非 Live Data 是最新狀態，否則不代表已確認的 OFF 狀態。真實影響輸出的動作需要經過確認。

啟用輸出前：

1. 確認所選通道。
2. 設定安全的電流限制與電壓。
3. 透過 Live Data 或讀回 (readback) 確認數值。
4. 僅在連接的 DUT 能承受該要求時，才啟用輸出。

## 進階命令 (Advanced Commands)

使用 `Show more commands` 來開啟命令列與生成的命令表單。命令依用途分組，例如 Output (輸出)、Output Workflows (輸出工作流程)、Protection (保護)、Trigger (觸發)、Snapshot (快照) 以及 Advanced Diagnostics (進階診斷)。

該表單由 WebUI 命令 metadata 生成。必填欄位必須在 Run (執行) 之前填寫。被停用的命令或控制項表示不支援的型號、模式或不在 WebUI 的支援範圍內。

某些編輯器支援 JSON Load/Save (載入/儲存)，包括 Sequence (序列)、Ramp List (斜坡清單) 與 Trigger List (觸發清單) 工作區。請使用這些功能來處理可重複的工作流程，並保持儲存的檔案中沒有私人的實驗室資源字串，除非您刻意要將其限制為本機專用。

## 工作結果 (Job Results)

送出的命令會出現在 `Job Result` 中。選擇一個工作以在 `Result Detail` 中檢查其狀態與原始 JSON。

典型的工作狀態包括 accepted (已接受)、started (已啟動)、progress (進行中)、finished (已完成)、failed (失敗)、cancel requested (已請求取消) 與 cancelled (已取消)。失敗的工作應在結果 payload 中包含錯誤訊息。

Simulate (模擬) 與 dry-run (預演) 工作有助於在實機硬體執行前檢查 payload 形狀。真實影響輸出的工作需要確認。

## 停止與取消

如果工作尚未啟動，取消動作能很快完成。如果真實的硬體工作已經在執行中，取消將採協作模式：WebUI 請求取消並等待 Core 清理完成。

除非有外部安全考量，否則請勿關閉瀏覽器或強制終止程序來打斷正常的清理過程。清理與 release/local (解除遠端/轉為本機) 的行為由 Core 處理，可能需要一些時間。

硬體命令處於活動狀態時，啟動器會封鎖 `Quit` (離開)。請先在瀏覽器中停止或取消命令，然後等待清理完成再退出啟動器。

## 常見問題

### 頁面無法載入

確認伺服器仍在執行並開啟：

```text
http://127.0.0.1:8000/
```

如果該 port 已被佔用，請在不同的 port 啟動伺服器並開啟該網址。

### 啟動器顯示 port 已被佔用

如果該 port 上已運行另一個 Keysight Power WebUI 伺服器，啟動器會直接開啟它。如果是由其他服務占用該 port，請在啟動啟動器前選擇其他 port 或停止該服務。

### Scan Device 找不到任何東西

檢查下列事項：

- 儀器已開機；
- USB 或 LAN 已連接；
- VISA 驅動程式可看到儀器；
- 沒有其他程式佔用資源；
- 此電腦上有正確的 VISA 後端。

您仍可手動輸入已知的 VISA 資源。

### 執行 (Run) 被封鎖

閱讀畫面上可見的驗證訊息與 Result Detail。常見原因為缺少資源、缺少必填命令欄位、不支援的型號、不安全的設定點，或影響輸出的實機命令缺少確認。

### 輸出按鈕看起來不是最新狀態

啟動或重新整理 Live Data。WebUI 會避免將過時的輸出狀態當成最新的事實來顯示。

### 命令顯示忙碌中

真實硬體命令由 WebUI 的硬體鎖定進行序列化。請等待目前的命令與清理完成，或僅在這是操作員刻意要做的動作時才進行取消。

### Live Data 回報過時或錯誤狀態

檢查資源、連線，以及是否有其他命令佔用了硬體 I/O。Live Data 不會覆蓋 (override) 真實的命令執行。

## 操作員安全注意事項

- 在執行影響輸出的命令前，請使用唯讀的 Live Data。
- 首次實機檢查應保持低電壓/電流，並明確指定通道。
- 在啟用輸出前，確認電流限制。
- 請將 `channel all` 視為刻意的多通道動作。
- 在理解觸發 (trip) 原因前，請勿清除保護。
- 將觸發與 LIST 工作流程視為進階操作。
- 在可行情況下，斷開 DUT 之前請停止或關閉輸出。

## 更多 WebUI 文件

- [WebUI README](README.zh-TW.md)：API 行為、驗證、開發環境設定與維護者邊界。
- [Web UI 變更規則](web-ui-change-rules.md)：針對開發人員與 agent 的 UI 變更規則。
-
