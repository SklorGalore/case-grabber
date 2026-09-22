# RAW Case Viewer

A read-only desktop inspector for PSS/E revision 35 `.raw` files. It shows each case section in a sortable, searchable table, full record fields and source lines, parser diagnostics, and focused equipment diagrams. Click a bus in a diagram to navigate to its record. The current filtered table can be exported to CSV.

## Run

Use Python 3.11 or newer:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
case-viewer
```

You can also pass a RAW path to `case-viewer`, use **File → Open RAW**, or drag a file into the window. The app holds one active case at a time. Parsing happens off the UI thread.

## Format behavior

- Supports revision 35 text RAW. Other revisions and RAWX are reported as unsupported.
- Reads every section present, including empty sections, multiline transformers, DC records, and generic network equipment records. Unknown extension sections remain visible with their original fields and source lines.
- Uses the file's `@!` column headings when available. Surplus fields receive numbered labels. Original lines are retained for inspection.
- Opens usable records from a partly malformed file and lists detected structural issues in **Diagnostics**.
- The **Circuit** tab renders annotated AC-line π equivalents and two- or three-winding transformer equivalents, including series impedance, terminal shunts, excitation data, tap ratio, nominal voltage, and impedance bases when available.
- Does not edit or solve cases. Diagrams are focused equipment schematics, not a whole-network map.

## Test and package

```bash
pip install -e '.[dev]'
pytest
pyinstaller --noconfirm --windowed --name RAW-Case-Viewer run_case_viewer.py
```

Run PyInstaller separately on macOS, Windows, and Linux. The build workflow in `.github/workflows/build.yml` does this for tagged releases and manual runs.
