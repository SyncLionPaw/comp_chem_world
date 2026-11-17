# website

Standalone academic project homepage for **comp-chem-world** (static HTML/CSS/JS). Offline input archive context links to [AI4EC](https://ai4ec.ac.cn).

Marketing/stat numbers on the page count the **scored** set only: **245** research tasks (001–245) = **195** local + **50** HPC. Smoke task `000-hello` is mentioned as excluded, never added into totals. (`configs/local.yaml` lists 196 paths including hello; display local as 195.)

## Theme & language

Header controls (next to GitHub): compact **theme** (sun/moon) and **language** (中文 / EN) toggles.

| Preference | `localStorage` key | First visit |
|---|---|---|
| Theme (`dark` / `light`) | `ccw-theme` | `prefers-color-scheme` |
| Language (`en` / `zh`) | `ccw-lang` | `navigator.language` starting with `zh` → Chinese, else English |

Applied via `data-theme` and `lang` on `<html>`; a tiny inline script in `<head>` avoids a flash of the wrong theme/lang. Copy is driven by `data-i18n` keys and a dictionary in `assets/main.js`.

## Preview

From this directory:

```bash
cd website
python3 -m http.server 8080
```

Then open [http://127.0.0.1:8080](http://127.0.0.1:8080).

You can also open `index.html` directly in a browser; a local server is preferred so relative asset paths behave consistently.
