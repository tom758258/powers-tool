[English](README.md)

# Keysight Powers

Keysight Powers 是用於 Keysight 直流電源供應器的 Python 控制工具。
專案提供單一可安裝發行套件 `keysight-powers` `1.0.0`，並保留三個
獨立 import package：`keysight_power_core`、`keysight_power_cli`、
`keysight_power_webui`。

本專案透過 VISA 支援 USB 與 LAN 通訊，並提供命令列工具與本機瀏覽器
WebUI。它適合需要明確安全檢查、模擬器支援，以及機器可讀輸出的電源供應器
工作流程。

## 功能特性

- 透過 VISA 使用 USB 或 LAN 控制支援的 Keysight 直流電源供應器。
- 可使用 `keysight-power` CLI 或本機 `keysight-power-webui` 儀表板。
- 使用 dry-run 模式在開啟 VISA 前預覽會影響硬體的命令。
- 使用內建模擬器在沒有硬體時測試流程。
- 設定電壓/電流限制、控制輸出狀態，並讀取即時儀器資料。
- 透過共用 Core runtime 執行 ramp、ramp-list、sequence、trigger、
  snapshot、restore 與 protection 流程。
- 產生 JSON 與 JSONL 輸出，供自動化、agent 與 orchestrator 使用。
- 真實硬體輸出必須明確選擇啟用；預設測試與模擬流程不會啟用儀器輸出。

## 專案結構

此 repository 使用單一發行套件與單一版本號：

- 發行套件：`keysight-powers` `1.0.0`
- Core import：`keysight_power_core`
- CLI import：`keysight_power_cli`
- WebUI import：`keysight_power_webui`

import 路徑彼此獨立。請不要使用 `keysight_power.*` namespace package。

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

先開啟 PowerShell 並進入專案根目錄：

```powershell
cd path\to\Keysight_Powers_Controller
```

如果尚未安裝 uv，先安裝：

```powershell
py -m pip install --user uv
```

確認 uv 可用：

```powershell
uv --version
```

在專案資料夾建立虛擬環境：

```powershell
uv venv .venv
```

依照 `uv.lock` 同步可重現的開發與測試環境：

```powershell
uv sync --all-extras --link-mode=copy
```

CI 或嚴格本機檢查可要求已提交的 lock file 不被改動：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

本專案支援 Python `>=3.10`。`uv venv .venv` 會使用可用的相容 Python。
如果需要指定版本，請明確指定：

```powershell
uv venv .venv --python 3.12
```

`uv.lock` 用於 uv 的開發與 CI 可重現環境。`pip install .` 會讀取
`pyproject.toml`，不會讀取 `uv.lock`。沒有 uv 的使用者需要先安裝 uv，
才能使用 lock 環境。

如果需要直接使用 pip，請使用虛擬環境中的 Python：

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install ".[webui]"
.\.venv\Scripts\python.exe -m pip install -e ".[all,dev]"
```

Windows 會建立虛擬環境 console wrapper，例如
`.\.venv\Scripts\keysight-power.exe` 與
`.\.venv\Scripts\keysight-power-webui.exe`。

## 執行

列出目前能回應 `*IDN?` 的 VISA resource：

```powershell
.\.venv\Scripts\keysight-power.exe list-resources --live-only
```

一般 `list-resources` 是被動 VISA discovery，可能顯示過期的快取 resource。
一般現場操作請使用 `--live-only`，診斷過期項目時再使用 `--verify`。

執行只使用模擬器的健康檢查：

```powershell
.\.venv\Scripts\keysight-power.exe doctor --simulate --json
```

啟動 WebUI：

```powershell
.\.venv\Scripts\keysight-power-webui.exe --host 127.0.0.1 --port 8000
```

開啟 `http://127.0.0.1:8000/`。

## 建置

建置 wheel 與 source distribution。這會使用前面安裝的 `dev` extra 中的
`build` 套件：

```powershell
.\.venv\Scripts\python.exe -m build
```

這只會產生一個 Python 發行套件：

```text
dist\keysight_powers-1.0.0-py3-none-any.whl
dist\keysight_powers-1.0.0.tar.gz
```

Python package build 不會產生 Windows executable。未來若要封裝 executable，
應放在獨立腳本中，並與 `python -m build` 分開。

## 測試

Pytest 預設使用已忽略的 repository-local `.tmp_pytest` 目錄，因此無硬體測試
不依賴 Windows 系統暫存目錄權限。請從 repository 根目錄執行 pytest。
如果單次執行需要獨立 basetemp，請使用 `--basetemp .tmp_tests/<purpose>`。
不要把 pytest 暫存資料或測試產物寫到 `Local/`。

開發迭代時可先跑 focused tests：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

執行完整無硬體測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

硬體驗證必須明確 opt-in。live smoke checks、hardware pytest 命令與安全細節
請見 CLI README。

## Release Validation

建立 release commit 或 package tag 前，從 repository 根目錄執行無硬體與套件
檢查：

```powershell
uv sync --all-extras --locked --link-mode=copy
.\.venv\Scripts\python.exe -m pytest tests\core\test_import.py -q -p no:cacheprovider
uv run keysight-power doctor --simulate --json
.\scripts\no-hardware-regression.ps1
.\.venv\Scripts\python.exe -m build
git status --short
```

最後的 `git status --short` 在提交前應只顯示預期的 release、文件與 lockfile
變更。

這個 release 不加入 PyInstaller、Nuitka 或其他 packager dependency。未來若
要封裝 EXE，應保持 package entry point 與目前 console script 一致：

```text
keysight_power_cli.cli:main
keysight_power_webui.server:main
```

## 文件

- [Core README](docs/core/README.md)
- [CLI 使用者指南](docs/cli/USER_GUIDE.md)
- [CLI README](docs/cli/README.md)
- [WebUI README](docs/webui/README.md)
- [WebUI 使用者指南](docs/webui/USER_GUIDE.md)
- [Web UI Change Rules](docs/webui/web-ui-change-rules.md)
- [Monorepo 架構](docs/architecture/monorepo-layout.md)
- [測試指南](docs/testing-guidelines.md)
- [Public Contracts](docs/contracts)
- [Power CLI JSONL Contract](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker Contract](docs/contracts/power-worker-contract.md)

## 授權條款與免責聲明

本專案採用 MIT License。詳見 [LICENSE](LICENSE)。

本專案是獨立且非官方的專案，未與 Keysight Technologies 建立從屬、
背書或贊助關係。

使用者需自行遵守所有適用的 Keysight 軟體、driver、儀器與文件授權條款。
