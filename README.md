# Code Rookie – Fully Editable 3-Round Quiz Website

This is the **source-code version** of the Code Rookie mock competition website. Nothing is locked or minified. Open the folder in VS Code and edit any file you want.

## Fastest way to edit

For normal organizer changes, edit **`EDIT_HERE.json`**. It contains:

- Website title and hero text
- Optional logo paths
- Theme colors
- Round 1/2/3 timers
- Round 1 and Round 2 mock qualification percentages
- Number of Round 1 questions shown per attempt
- Every Round 1 MCQ for Python and C++
- Correct option index and explanation for each MCQ
- Every Round 2 coding/debugging problem
- Every Round 3 final coding problem
- Starter code, sample input/output, and evaluator/hidden test cases

After saving `EDIT_HERE.json`, restart the local server to reload your changes.

## Full-control files

- `EDIT_HERE.json` — questions, coding tasks, tests, branding, timers, colors
- `static/index.html` — page structure/layout/text
- `static/styles.css` — complete visual design
- `static/app.js` — quiz behavior and browser interactions
- `app.py` — local server, grading, code execution, result storage
- `results/` — saved participant attempts

## Run on Windows

1. Install Python 3.10 or newer.
2. Double-click `start_windows.bat`.
3. Open `http://127.0.0.1:8765` in Chrome/Edge.

Or open a terminal in the project folder and run:

```text
python app.py
```

To edit in VS Code, double-click `edit_in_vscode.bat` if the `code` command is installed, or open VS Code and choose **File → Open Folder**.

## Add your logos

1. Put the image files inside `static/`, for example:
   - `static/hash-logo.png`
   - `static/jain-logo.png`
2. In `EDIT_HERE.json`, set:

```json
"left_logo": "/hash-logo.png",
"right_logo": "/jain-logo.png"
```

Leave the values empty to hide the logos.

## Change colors

The `theme` object in `EDIT_HERE.json` controls the main CSS variables. Example:

```json
"--bg": "#07110f",
"--accent": "#6ee7b7",
"--accent2": "#34d399"
```

## Add a Round 1 question

Add an object to `round1.common`, `round1.python`, or `round1.cpp`:

```json
{
  "id": "p09",
  "type": "single",
  "question": "What is the output?\n\nprint(10 % 3)",
  "options": ["0", "1", "3", "10"],
  "answer": 1,
  "explanation": "10 divided by 3 leaves remainder 1."
}
```

`answer` is zero-based: `0` = first option, `1` = second option, and so on. Every question ID must be unique.

## Edit or add a coding problem

Problems live under `problems` in `EDIT_HERE.json`. Each problem contains:

- `round`: 2 or 3
- `title`
- `kind`
- `statement`
- `input_format`
- `output_format`
- `samples`
- `starter.python`
- `starter.cpp`
- `tests`

The `tests` section is kept on the server; hidden test input/output is **not sent to the participant browser** during a normal submission.

## C++ support

Python submissions use the Python installation running this app. C++ submissions require `g++` or `clang++` in PATH. The website shows whether a C++ compiler was detected.

## Results

Participant attempts are saved as JSON files in `results/`. Use **Organizer Results** in the website to view them and export CSV.

## Validation

At startup, `app.py` validates `EDIT_HERE.json`. If an edit breaks the JSON or a required question/problem field, the terminal gives a specific error instead of silently running bad data.

Run the included checks with:

```text
python -m unittest discover -s tests -v
```

## Local-use security note

The server binds to `127.0.0.1`. It runs participant code in temporary subprocesses with timeouts, but it is not a hardened remote-code sandbox. Keep it local/offline rather than exposing this server directly to the public internet.
