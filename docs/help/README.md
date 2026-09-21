# Help Maintenance

Bundled Help is generated from the maintained Markdown sources below.

## Canonical Sources

- `docs/cli/USER_GUIDE.md`
- `docs/cli/USER_GUIDE.zh-TW.md`
- `docs/webui/USER_GUIDE.md`
- `docs/webui/USER_GUIDE.zh-TW.md`
- `docs/core/supported-models.md`
- `docs/core/supported-models.zh-TW.md`

Shared presentation sources are `docs/help/template.html` and
`docs/help/help.css`. The generator is `scripts/generate_help.py`.

The generator emits the complete canonical Help set in one run: CLI guide
pages, WebUI guide pages, both locales, both Supported Models pages, and shared
Help CSS. It does not generate only one runtime surface.

The CLI runtime owns its CLI guide pages, Supported Models pages, and shared
Help CSS under `src/powers_tool_cli/help/`. The WebUI runtime owns its WebUI
guide pages, Supported Models pages, and shared Help CSS under
`src/powers_tool_webui/static/help/`.

Editing or saving a canonical Markdown source does not by itself update the
tracked runtime Help assets. After changing maintained Help content, run the
generator explicitly into a temporary directory:

```powershell
uv run python scripts/generate_help.py `
    --output-dir .tmp_tests\generated_help
```

Do not point the generator directly at either tracked runtime Help directory.
After generation, synchronize only the generated files owned by the affected
runtime surface(s). For a CLI/WebUI User Guide-only update, the usual mappings
are:

| Canonical source | Generated file | Tracked runtime asset |
| --- | --- | --- |
| `docs/cli/USER_GUIDE.md` | `cli.html` | `src/powers_tool_cli/help/cli.html` |
| `docs/cli/USER_GUIDE.zh-TW.md` | `cli.zh-TW.html` | `src/powers_tool_cli/help/cli.zh-TW.html` |
| `docs/webui/USER_GUIDE.md` | `webui.html` | `src/powers_tool_webui/static/help/webui.html` |
| `docs/webui/USER_GUIDE.zh-TW.md` | `webui.zh-TW.html` | `src/powers_tool_webui/static/help/webui.zh-TW.html` |

If Supported Models Markdown or shared Help presentation sources change,
synchronize the corresponding generated Supported Models pages and/or shared
CSS for each affected runtime owner as well.

Never manually edit generated Help HTML as a second documentation source.

Run the focused generator/synchronization checks after updating tracked runtime
assets:

```powershell
uv run python -m pytest tests/tooling/test_help_generator.py tests/cli/test_cli_user_guide.py tests/webui/test_webui_help.py -q -p no:cacheprovider
```

Focused checks include
[`test_help_generator.py`](../../tests/tooling/test_help_generator.py),
[`test_cli_user_guide.py`](../../tests/cli/test_cli_user_guide.py), and
[`test_webui_help.py`](../../tests/webui/test_webui_help.py).
