# B92_ALPO Monitoring Report Extractor

Extracts sensor data from Sanofi B92_ALPO PDF monitoring reports and outputs a wide-format CSV with columns for Date, Time, Timestamp, and one column per sensor (e.g. `VIA MEDIA AND FORMULATION N/01350/TT_33`).

---

## Quick Start (Easiest Method)

1. **Install Python** (one-time setup) — Download Python 3.10 or higher from [python.org](https://www.python.org/downloads/). During installation, **check the box that says "Add Python to PATH"**.
2. **Unzip this folder** anywhere on your computer (Desktop, Documents, etc.).
3. **Double-click `start.bat`** inside the folder. It will automatically install the required packages the first time you run it.
4. Follow the on-screen menu to process your PDF(s).

That's it — no command line knowledge needed.

---

## What This Program Does

This tool reads B92_ALPO PDF monitoring reports and pulls out the timestamped sensor readings into a clean CSV spreadsheet you can open in Excel. Each sensor gets its own column, and each row is one timestamp.

---

## Prerequisites

- **Windows PC**
- **Python 3.10 or higher** — [Download here](https://www.python.org/downloads/)
  - During the installer, make sure **"Add Python to PATH"** is checked (see screenshot below the download button on the Python website)
- An internet connection is needed the first time to install two small packages (`pdfplumber` and `pandas`)

---

## Setup (First Time Only)

If `start.bat` handles the install for you, skip this section. Otherwise:

1. Open **Command Prompt** (press `Win + R`, type `cmd`, press Enter).
2. Navigate to the folder you unzipped. For example, if you put it on your Desktop:
   ```
   cd "%USERPROFILE%\Desktop\PDFtoexcel"
   ```
3. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

---

## Usage

### Option A: Interactive Launcher (recommended)

Double-click **`start.bat`**. You will see this menu:

```
Select mode:

  [1] Process a single PDF file
  [2] Process all PDFs in a folder
  [3] Exit
```

- **Option 1 — Single PDF:** Drag and drop a PDF file into the window (or type its full path), then press Enter. You will be prompted for an output CSV name — just press Enter to accept the default (`b92_output.csv`).
- **Option 2 — Batch (whole folder):** Type or paste the path to a folder that contains your PDF files. All `.pdf` files in that folder will be processed and combined into one CSV.

When finished, the program will tell you where the output file was saved (the `outputs` subfolder by default).

### Option B: Command Line

Open Command Prompt, navigate to this folder, then run:

**Single PDF:**
```
python extract_b92.py "C:\path\to\report.pdf"
```

**Multiple PDFs:**
```
python extract_b92.py "C:\path\to\report1.pdf" "C:\path\to\report2.pdf"
```

**All PDFs in a folder:**
```
python extract_b92.py "C:\path\to\pdf_folder"
```

**Custom output location:**
```
python extract_b92.py "C:\path\to\report.pdf" -o "C:\path\to\my_output.csv"
```

**Verbose mode (shows detailed processing info):**
```
python extract_b92.py "C:\path\to\report.pdf" -v
```

These flags can be combined:
```
python extract_b92.py "C:\path\to\pdf_folder" -o results.csv -v
```

---

## Opening the Output

The output CSV is saved in the `outputs/` subfolder inside this program's folder. To view it:

1. Navigate to the `outputs` folder.
2. Double-click the `.csv` file to open it in **Excel**.
3. The spreadsheet will have these columns:

| Column | Description |
|---|---|
| Date | Date in `YYYY-MM-DD` format |
| Time | Time in `HH:MM:SS` format |
| Timestamp | Original timestamp string from the PDF |
| *Sensor columns* | One column per sensor, named exactly as it appears in the PDF header (e.g. `VIA MEDIA AND FORMULATION N/01350/TT_33`) |

Example:

| Date | Time | Timestamp | VIA MEDIA AND FORMULATION N/01350/AT-COND_01 | VIA MEDIA AND FORMULATION N/01350/TT_33 |
|---|---|---|---|---|
| 2026-01-16 | 15:00:00 | 1/16/2026 15:00 | 0.07 | 33.15 |
| 2026-01-16 | 15:00:30 | 1/16/2026 15:00:30 | 0.11 | 33.1 |

---

## Re-running on New PDFs

If you run the extractor on a new PDF that contains sensors not seen before, the new sensor columns are **automatically added** to the existing output CSV. Previously extracted data is preserved; new columns show blanks for old rows.

To start fresh, simply delete the existing CSV in the `outputs` folder before running again.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **"Python is not recognized"** or **"Python not found"** | Python is not installed or not on your PATH. Reinstall Python from [python.org](https://www.python.org/downloads/) and make sure **"Add Python to PATH"** is checked during installation. |
| **"No PDF files found"** | Check that the file/folder path you entered is correct and points to `.pdf` files. |
| **"No data rows extracted"** | The PDF may not be a B92_ALPO tabular monitoring report. Try running with `-v` for detailed diagnostics. |
| **Columns look wrong or jumbled** | Delete the old output CSV in the `outputs` folder and re-run. |
| **Values/columns mismatch warning** | A data row in the PDF had a different number of values than expected. The program takes as many as it can match — check the original PDF for irregularities. |
| **start.bat closes immediately** | Right-click `start.bat` and choose "Run as administrator", or open Command Prompt first, navigate to this folder, and type `start.bat`. |

---

## Files in This Package

| File | Purpose |
|---|---|
| `start.bat` | Double-click this to run the program (interactive menu) |
| `extract_b92.py` | Main extraction script |
| `validate_extraction.py` | Diagnostic tool — runs the parser and reports detailed per-page info |
| `requirements.txt` | Lists the Python packages needed (`pdfplumber`, `pandas`) |
| `outputs/` | Default folder where output CSV files are saved |
| `README.md` | This file |
