# Color by Number — RE study + asset toolchain

Reverse-engineering study of the **Color by Number** Android app
(`com.sycb.coloring.book`, "Iceors" engine) plus a Python toolchain that
produces assets the engine can load.

The repo contains two largely independent halves:

| Half | Lives in | Purpose |
|------|----------|---------|
| **Android port** | `app/` | A minimal Kotlin port (`IceorsView`, `IceorsAsset`) that loads and renders the same on-disk asset format as the original APK. Used to verify converter output end-to-end on device. Package: `com.apero.color.number`. |
| **Asset toolchain** | `tools/` | Python pipeline that converts an **SVG** into the binary `b` file (paths + palette) and an optional reference JPEG `c`, packaged in a ZIP the Android app loads. |

---

## Quick start — generate an asset from an SVG

```bash
cd tools/
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Web UI (recommended)
.venv/bin/streamlit run web_app.py

# Or CLI
.venv/bin/python svg_to_colorbynumber.py input.svg --out out_b
```

Recommended upstream workflow: AI-generated PNG →
[vectorizer.ai](https://vectorizer.ai) → upload the resulting SVG to the
web UI. Each fill region in the SVG becomes one paint-by-number region;
black strokes become fixed (non-paintable) outlines.

The output ZIP contains:

```
{key}_b.zip
├── {key}b              ← path data (CRLF-separated, pipe-delimited)
├── {key}c              ← reference JPEG 2048×2048 (optional)
└── sp_new_paint_flag   ← "111\r\n" sentinel
```

Drop this ZIP into the Android app's asset directory; `IceorsAsset.load()`
parses it and `IceorsView` renders it.

---

## Repository layout

```
ColorByNumber/
├── app/                          # Android (Kotlin) — port of IceorsView
│   └── src/main/java/com/apero/color/number/
│       ├── iceors/
│       │   ├── IceorsAsset.kt    # parses {key}b + palette
│       │   └── IceorsView.kt     # layered-bitmap renderer
│       └── *Activity.kt          # demo activities
├── tools/                        # Python conversion pipeline
│   ├── web_app.py                # Streamlit UI
│   ├── svg_to_colorbynumber.py   # core SVG → lines converter (also CLI)
│   ├── cdn_scraper.py            # standalone helper (CDN scraping)
│   ├── requirements.txt
│   └── FLOW.md                   # step-by-step pipeline doc
├── REPORT_VI.md                  # RE analysis of the original APK
├── docs.md                       # IceorsView rendering mechanism
├── cmssetupdata.md               # CMS data-model spec
└── README.md                     # this file
```

---

## Asset format (one-paragraph summary)

The `b` file is plain text, CRLF-terminated, one region per line:

```
{svgPathD}|{colorHex6}|{strokeWidth}|{labelPosPacked}|{fontSize}
```

- `colorHex` = `000000` marks a **fixed** region (black/dark-brown
  decoration; not paintable).
- `strokeWidth` = `0` marks a **fill region**; `> 0` marks a **stroke-only
  outline**.
- `labelPosPacked` = `cy * canvasSize + cx` (canvas size = 2048).
- Coordinates are in pixel space at canvas size 2048×2048; non-square
  inputs are padded to square automatically.

For the rendering side (how the engine reveals colour underneath a
"painted" region), see `docs.md`. For the full conversion pipeline (how
the SVG becomes lines), see `tools/FLOW.md`. For the original APK
analysis, see `REPORT_VI.md`.

---

## Where to look for what

| If you want to… | Read |
|---|---|
| Understand the original app's reveal mechanism | `REPORT_VI.md` |
| Understand the Kotlin renderer in this repo | `docs.md` |
| Trace what the converter does, step by step | `tools/FLOW.md` |
| See the data model the CMS needs to expose | `cmssetupdata.md` |
| Run the tool against a new SVG | this README, **Quick start** above |
| Hack on the converter | `tools/svg_to_colorbynumber.py` (entry: `svg_to_lines()`) |
| Hack on the web UI | `tools/web_app.py` |

---

## Status & scope

- **Tool** (`tools/`): production-usable. SVG-only input (the older
  K-means/potrace raster pipeline was removed; see commit `e257ba6`).
  Auto-merges near-identical fill colors; subtracts overlapping fills so
  each region paints unique pixels; auto-detects black/dark-brown
  decorations as fixed outlines.
- **Android app** (`app/`): demo/verification harness, not a shipping
  product. Implements just enough of the original `IceorsView` /
  `IceorsAsset` API surface to load and render converter output.
- **Asset format compatibility**: matches the original APK's parser
  (`IceorsAsset.parseLines`), so the same ZIP works in both this app and
  (in principle) the original.
