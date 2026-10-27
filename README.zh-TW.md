[English](README.md)

# Powers Tool

Powers Tool 是以安全為優先、供已支援直流電源供應器使用的 vendor-neutral Python 控制工具。
單一發行套件 `powers-tool` 包含三個獨立 import package：`powers_tool_core`、
`powers_tool_cli`、`powers_tool_webui`。透過 VISA 支援已登錄的 USB、LAN 與明確設定的
RS-232/ASRL 通訊，並提供 dry-run、模擬器及 JSON/JSONL 自動化工作流程。

Core 負責儀器識別、Driver、SCPI、安全驗證和精確的實機支援決策；CLI 與 WebUI 是平行
Adapter，Power Worker 則提供相同 Core 命令邊界給本機自動化。實機以 `*IDN?` 識別，
未知、未註冊或不符精確支援範圍的型號、命令、傳輸、Backend 與功能皆 fail closed。
Vendor-specific Driver、Alias、手冊、SCPI 與支援資訊仍保留正確的廠商名稱。
確切範圍參閱 [支援型號](docs/core/supported-models.zh-TW.md)；規劃及預期型號防護參閱
[CLI README](docs/cli/README.zh-TW.md#planning-identities-與-live-expected-model-guards)。

**VISA 後端：** Python 安裝及 Windows Bundle 都包含 PyVISA、PyVISA-py，另有支援
TCPIP 網路介面探索的 `psutil` 和 HiSLIP 探索的 `zeroconf`。System VISA 預設選用
IVI (`@ivi`)，需另行安裝 Keysight IO Libraries Suite、NI-VISA 等執行環境；
載入失敗不會回退到 `@py`，即使設定 `PYVISA_LIBRARY=@py` 也是如此。可透過 CLI
`--backend @py` 或 WebUI「裝置選項 → VISA 後端」明確選擇 PyVISA-py；CLI 也保留
受政策限制的自訂 VISA Library 路徑與 Backend 選項。不隨附選用的 USB／Serial 函式庫。

E36312A 和 EDU36311A 的 **TCPIP + PyVISA-py (`@py`)** 已有經驗證的 Product-open
精確支援範圍；USB + `@py` 及其他型號／Backend 組合不得據此推論為支援，Sequence
與 Trigger 子功能亦受個別限制。Backend 可載入、儀器可辨識，或已安裝 VISA Runtime，
均不代表已取得 Product 支援。dry-run、Simulator 和一般無硬體測試不需要實體儀器或
廠商 VISA Runtime；實機限制詳見 [支援型號](docs/core/supported-models.zh-TW.md)。

## 功能特性

- 透過 VISA 使用 USB、LAN 或明確設定的 RS-232/ASRL 控制支援的直流電源供應器
- 透過 `powers-tool` CLI 或本機 `powers-tool-webui` 儀表板操作
- 在 WebUI 即時切換英文與繁體中文、不重新載入頁面，且不改變 Machine-facing 值、API Payload 或原始診斷資訊
- 使用 dry-run 在開啟 VISA 前預覽會影響硬體的命令
- 使用內建模擬器在無硬體環境測試流程
- 設定電壓／電流限制、控制輸出狀態並讀取即時儀器資料
- 透過共用 Core 執行 Ramp、Ramp-list、Sequence、Trigger、Snapshot、Restore 與 Protection 工作流程
- 輸出 JSON／JSONL，供自動化、Agent 和 Orchestrator 使用
- 實機輸出必須明確 Opt-in；預設測試及模擬流程不啟用儀器輸出

## 專案結構

單一 `powers-tool` Distribution 的 `<version>` 由根目錄 `pyproject.toml` 的
`[project].version` 定義：

- 發行套件：`powers-tool` `<version>`
- Core import：`powers_tool_core`
- CLI import：`powers_tool_cli`
- WebUI import：`powers_tool_webui`

import 路徑彼此獨立；請不要使用 `powers_tool.*` namespace package 或已淘汰的
`keysight_power.*` namespace。

```text
src/
  powers_tool_core/
  powers_tool_cli/
  powers_tool_webui/
desktop/
  package.json
  package-lock.json
  main.cjs
tests/
  core/
  cli/
  webui/
  integration/
  packaging/
  tooling/
docs/
  core/                runtime 與 Product 支援文件
  cli/                 CLI 維護者與操作員文件
  webui/               WebUI 與 Desktop 文件
  contracts/           公開 protocol 與 workflow contracts
  help/                bundled Help presentation 與維護
  architecture/
  CONTRIBUTING.md
  testing-guidelines.md
scripts/
```

## 安裝

在 PowerShell 進入專案根目錄：

```powershell
cd path\to\powers-tool
```

如尚未安裝 uv，先安裝並確認版本：

```powershell
py -m pip install --user uv
```

```powershell
uv --version
```

建立虛擬環境，並依 `uv.lock` 同步開發／測試相依套件：

```powershell
uv venv .venv
```

```powershell
uv sync --all-extras --link-mode=copy
```

CI 或嚴格的本機驗證應鎖定已提交的相依套件版本：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

支援 Python `>=3.10`；uv 會選擇相容版本，也可明確指定：

```powershell
uv venv .venv --python 3.12
```

`uv.lock` 記錄 `powers-tool` Distribution。Windows 在 `.venv\Scripts\` 建立
`powers-tool.exe`、`powers-tool-webui.exe`、`powers-tool-webui-launcher.exe`；舊名稱
不作為相容別名。如既有環境同步成功但 Wrapper 遺失或未更新，僅重裝專案套件：

```powershell
uv sync --all-extras --link-mode=copy --reinstall-package powers-tool
```

一般安裝只需 `uv sync`；更多無硬體操作參閱
[CLI Quick Start](docs/cli/README.zh-TW.md#快速開始) 和
[WebUI 使用者指南](docs/webui/USER_GUIDE.zh-TW.md)。

## 快速開始

下列範例僅執行無硬體或本機工作；不會搜尋 VISA 資源或開啟實機輸出。

執行 CLI 模擬器診斷：

```powershell
uv run powers-tool doctor --simulate --json
```

啟動本機 WebUI Launcher：

```powershell
uv run powers-tool-webui-launcher
```

從 `desktop/` 啟動 Electron 開發 Shell：

```powershell
Set-Location .\desktop
npm ci
npm start
```

詳細指令與介面操作請參閱 [CLI README](docs/cli/README.zh-TW.md) 及
[WebUI 使用者指南](docs/webui/USER_GUIDE.zh-TW.md)。

## 建置

使用 `dev` Extra 中的 `build` 套件建立單一 Wheel 與 Sdist：

```powershell
.\.venv\Scripts\python.exe -m build
```

產物：

```text
dist\powers_tool-<version>-py3-none-any.whl
dist\powers_tool-<version>.tar.gz
```

Distribution Inspector 會檢查 Wheel／Sdist，排除 Validation Scripts、Private Fixtures、
Candidate Evidence 及 Internal Tests。Windows Bundle 另以 PyInstaller Onedir 建立。

先準備包含 PyInstaller 的鎖定開發環境：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

建立共用 CLI、WebUI Launcher 和私有 Desktop Host Bundle：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

**Windows 建置必要條件：** WebUI Launcher 使用 Tkinter；Python 環境必須具備可用的
Tcl/Tk Runtime，腳本會在啟動 PyInstaller 前檢查。

輸出共用目錄：

```text
dist\powers-tool\
  powers-tool.exe
  powers-tool-webui-launcher.exe
  powers-tool-webui-host.exe
  _internal\
```

Bundle 的 Launcher 與安裝後的 `powers-tool-webui-launcher` 都使用
`powers_tool_webui.launcher:main`。`powers-tool-webui-host.exe` 僅供 Desktop 使用，
不是公開 CLI 入口；三個執行檔共用單一 `_internal`。

開發 Desktop 時，可在 `desktop/` 啟動重用 WebUI 的 Electron Shell：

```powershell
Set-Location .\desktop
npm ci
npm start
```

Desktop 使用私有 WebUI Host，視窗會依顯示器工作區調整，並支援 System／Light／Dark
主題；外觀詳見 [WebUI README](docs/webui/README.zh-TW.md)。允許多個 Instance 控制
**不同**的儀器，但不得由不同 Client 同時操作同一個實體儀器 Resource。

建立包含共用 Python Bundle 的 Windows Desktop 目錄：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

產生 `Powers Tool.exe`、三個 Python 執行檔、Electron Runtime，以及共用
`_internal`；正式版以相同目錄製作 Windows ZIP。

使用封裝的 CLI 進行無硬體 Smoke：

```powershell
.\dist\powers-tool\powers-tool.exe --version
.\dist\powers-tool\powers-tool.exe doctor --simulate --json
```

組裝帶版本號的 Wheel、Sdist、Windows ZIP 與 SHA-256 Checksums：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

產物：

```text
release\<version>\powers-tool-<version>-windows-x64.zip
release\<version>\powers_tool-<version>-py3-none-any.whl
release\<version>\powers_tool-<version>.tar.gz
release\<version>\checksums.txt
```

ZIP 含單一 `powers-tool-<version>\`，共用 `_internal`；`checksums.txt` 僅涵蓋
ZIP、Wheel 與 Sdist。

從 **乾淨、已提交且執行期間不變的 HEAD** 執行正式無硬體 Release Acceptance：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-acceptance.ps1
```

驗收使用既有 `.venv`、驗證 `uv.lock`、完整執行一次無硬體測試並只建置一次 Release；
檢查 Wheel／Sdist／Desktop ZIP、三筆 SHA-256，分別在乾淨環境安裝最終 Wheel 與 Sdist，
確認兩者的內建 Help，以及 Sdist 的全部 Console Entry Points。另對每個 Product-active
型號執行快速 CLI Smoke、對具代表性的 Capability／硬體結構執行較深入流程，
並檢查模擬器 `PlanOnly`。只有新增尚未涵蓋的 Capability Family 或硬體結構，
才需要額外的深度代表型號。報告存於被忽略的輸出目錄（`report.json`、`summary.md`）；
如指定 `-OutputRoot`，必須位於專案的 `.tmp_tests/` 內。

手動 GitHub Actions **Build Windows** 提供 `bundle`、`desktop`、`release` 與
`release-acceptance`；前三者僅供下載 Build Artifacts。只有從 `main` 使用
`release-acceptance` 並明確設定 `create_draft=true`，在報告、Commit、版本及
Checksums 驗證成功後，才能由已驗收的原始產物及對應 CHANGELOG 建立 Draft Release；
正式發布仍需人工審查。此驗收不做 VISA 探索、開啟 Resource、送出 SCPI，
不會自動發布；HEAD 或工作樹改變時驗收失敗。

## 測試

Pytest 預設使用已忽略的專案內 `.tmp_pytest/`；從根目錄執行。若單次測試需獨立
暫存位置，使用 `--basetemp .tmp_tests/<purpose>`，不得寫入私人 `Local/`。

開發時先執行各元件的 Focused Tests：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

執行 CI 使用的 Ruff：

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```

執行快速無硬體測試（排除指定 Windows Wrapper 和 Release Acceptance Contract Tests）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --ignore=tests\cli\test_cli_wrappers.py --ignore=tests\packaging\test_release_acceptance.py
```

CI 另外驗證文字編碼／空白、WebUI JavaScript 與 Node Runtime Tests、跨版本 Python
測試、封裝及 Console Entry Points；Windows PowerShell Contracts 與 Windows
Packaging Smoke 依變更路徑條件執行。完整 Release Acceptance 不屬一般 PR CI。
詳見 [測試指南](docs/testing-guidelines.md)。

腳本化與實機驗證請參閱 [CLI README](docs/cli/README.zh-TW.md#scripted-validation)。
實機測試必須由使用者明確選擇並提供 VISA Resource，絕不由一般測試自動啟動。

## 文件

- [版本紀錄](CHANGELOG.md)
- [Core README](docs/core/README.zh-TW.md)
- [Supported Models](docs/core/supported-models.zh-TW.md)
- [CLI 使用者指南](docs/cli/USER_GUIDE.zh-TW.md)
- [CLI README](docs/cli/README.zh-TW.md)
- [WebUI README](docs/webui/README.zh-TW.md)
- [WebUI 使用者指南](docs/webui/USER_GUIDE.zh-TW.md)
- [Web UI Change Rules](docs/webui/web-ui-change-rules.md)
- [Help 維護](docs/help/README.md)
- [Repository Layout](docs/architecture/monorepo-layout.md)
- [測試指南](docs/testing-guidelines.md)
- [貢獻指南](docs/CONTRIBUTING.md)
- [Public Contracts](docs/contracts)
- [Power CLI JSONL Contract](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker Contract](docs/contracts/power-worker-contract.md)

## 貢獻

貢獻、開發 ownership、no-hardware 測試期望、contributor validation-artifact
workflow 與變更規則請參閱 [CONTRIBUTING](docs/CONTRIBUTING.md)。變更 live
model、command、transport 或 backend 支援時，適用情況下需要可審閱的真機
evidence。

## 授權條款與免責聲明

本專案採用 MIT License。詳見 [LICENSE](LICENSE)。

應用程式圖示：Powers Tool 應用程式圖示使用 ChatGPT 中的 OpenAI 圖像生成功能產生，
並由專案維護者審閱及選定。

本專案是獨立且非官方的專案，未與支援之儀器製造商或 vendor 建立從屬、
背書或贊助關係。

Powers Tool 所提及的所有製造商名稱、產品名稱、型號名稱與商標，其權利均歸各自權利人所有。

使用者需自行遵守支援之 vendor 所適用的軟體、driver、儀器與文件授權條款。
