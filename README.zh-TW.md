# Keysight Powers

Keysight Powers 是一個用於 Keysight 直流電源供應器的 Python 控制工具包。
它提供一個可安裝的發行版 `keysight-powers` `1.0.0`，同時保留了三個匯入套件：`keysight_power_core`、`keysight_power_cli` 和 `keysight_power_webui`。

該專案支援透過 VISA 進行 USB 和 LAN 通訊、命令列操作以及本地瀏覽器 WebUI。它專為需要明確安全檢查、模擬器支援和機器可讀輸出的電源供應器工作流程而設計。

## 功能特性

- 支援透過 VISA 使用 USB 或 LAN 控制支援的 Keysight 直流電源供應器
- 可使用 `keysight-power` 命令列介面 (CLI) 或本地 `keysight-power-webui` 儀表板
- 在開啟 VISA 之前，使用預跑 (dry-run) 模式預覽會影響硬體的命令
- 使用內建模擬器，在沒有硬體的情況下測試工作流程
- 設定電壓/電流限制、控制輸出狀態並讀回即時儀器數據
- 透過共享的 Core 執行期，執行步進 (ramp)、步進列表 (ramp-list)、序列 (sequence)、觸發 (trigger)、快照 (snapshot)、還原 (restore) 和保護 (protection) 工作流程
- 為自動化、代理 (agents) 和協調器 (orchestrators) 產生 JSON 和 JSONL 輸出
- 保持真實硬體輸出為選擇性啟用 (opt-in)；預設測試和模擬器流程不會啟用儀器輸出

## 專案結構

此儲存庫包含一個發行版和一個版本號：

- 發行版：`keysight-powers` `1.0.0`
- Core 匯入：`keysight_power_core`
- CLI 匯入：`keysight_power_cli`
- WebUI 匯入：`keysight_power_webui`

匯入路徑保持獨立。請勿使用 `keysight_power.*` 命名空間套件。

```text
src/
  keysight_power_core/
  keysight_power_cli/
  keysight_power_webui/
tests/
  core/
  cli/
  webui/
  integration/
docs/
  core/
  cli/
  webui/
scripts/
```

## 安裝

基本 Core/CLI 安裝：

```powershell
pip install .
```

安裝 WebUI 執行期依賴項：

```powershell
pip install ".[webui]"
```

安裝本地開發和測試所需的一切（不使用 uv）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[all,dev]"
```

使用 uv 時，利用 lock 檔案重現開發和測試環境：

```powershell
uv sync --all-extras --link-mode=copy
```

對於 CI 或嚴格的本地檢查，要求已提交的 lock 檔案保持不變：

```powershell
uv sync --locked --all-extras --link-mode=copy
```

`uv.lock` 檔案用於開發和 CI 的重現性。它並不能取代套件使用者標準的 `pip install` 命令。

Windows 會建立虛擬環境主控台包裝器（如 `.\.venv\Scripts\keysight-power.exe` 和 `.\.venv\Scripts\keysight-power-webui.exe`）。

## 執行

列出 VISA 資源：

```powershell
.\.venv\Scripts\keysight-power.exe list-resources
```

執行僅限模擬器的健康檢查：

```powershell
.\.venv\Scripts\keysight-power.exe doctor --simulate --json
```

啟動 WebUI：

```powershell
.\.venv\Scripts\keysight-power-webui.exe --host 127.0.0.1 --port 8000
```

開啟 `http://127.0.0.1:8000/`。

## 建置

建置 wheel 和原始碼發行版。這會使用上面安裝的 `dev` 額外相依性中的 `build` 套件：

```powershell
.\.venv\Scripts\python.exe -m build
```

這僅會產生一個 Python 發行版：

```text
dist\keysight_powers-1.0.0-py3-none-any.whl
dist\keysight_powers-1.0.0.tar.gz
```

Python 套件建置不會建立 Windows 可執行檔。未來任何可執行檔的打包工作都應保留在獨立的腳本中，與 `python -m build` 分開。

## 測試

在迭代時執行特定部分的測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

執行完整的無硬體測試套件：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

硬體驗證是明確且選擇性啟用的。請參閱 CLI README 以取得即時煙霧測試 (smoke checks)、硬體 pytest 命令和安全詳細資訊。

## 文件

- [Core README](docs/core/README.md)
- [CLI README](docs/cli/README.md)
- [WebUI README](docs/webui/README.md)
- [WebUI 使用者指南](docs/webui/USER_GUIDE.md)
- [Monorepo 架構](docs/architecture/monorepo-layout.md)
- [測試指引](docs/testing-guidelines.md)
- [公開合約](docs/contracts)
- [Power CLI JSONL 合約](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker 合約](docs/contracts/power-worker-contract.md)

## 授權條款與免責聲明

本專案採用 MIT 授權條款。詳見 [LICENSE](LICENSE)。

本專案是獨立且非官方的。與 Keysight Technologies 無任何關聯，亦未獲得其認可或贊助。

使用者有責任遵守所有適用的 Keysight 軟體、驅動程式、儀器和文件的授權條款。
