# Master Thesis Evaluation Dashboard

A Streamlit dashboard that allows UGent promotors and supervisors to view jury evaluations for their master thesis students. Data is collected via Qualtrics and stored in an AWS S3 bucket.

---

## Project structure

| File | Purpose |
|---|---|
| `dashboard.py` | Main application — run this |
| `users.yaml` | Login credentials per user (username → password) |
| `assignments.csv` | Links usernames to students and academic years |
| `assignments_new.csv` | Generated assignments file (output of `extract_assignments.py`) |
| `rubric.csv` | Evaluation rubric: 22 competencies across 11 clusters, each scored on a 6-point scale |
| `extract_assignments.py` | Utility script: reads the Excel export and writes `assignments_new.csv` |
| `2526-jun.xlsx` | Excel export from the thesis management system with student–promotor–begeleider links |
| `.env` | AWS credentials (not committed to version control) |
| `img/ugent.png` | UGent logo used in the footer |
| `sampledata.csv` | Sample score data (3 evaluators) used as fallback when S3 is unavailable |
| `sampledata_review.csv` | Sample written reviews and questions used as fallback |

---

## How to run

### Install dependencies

```console
pip install streamlit pyyaml boto3 pandas python-dotenv plotly pillow openpyxl
```

### Configure AWS credentials

Create a `.env` file in the project root:

```ini
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_DEFAULT_REGION=us-east-1
```

The IAM user (`mp_dashboard`) needs read access to the S3 bucket `qualtrics-data-bucket-live`.

### Run the dashboard

```console
python -m streamlit run dashboard.py
```

---

## User flow

1. **Login** — user enters username and password, validated against `users.yaml`. On success, all CSV files are fetched from the Qualtrics S3 bucket and combined into one dataset (stored in session state for the rest of the session).
2. **Student selection** — user picks an academic year and a student from a dropdown. Only students assigned to the logged-in user in `assignments.csv` are shown.
3. **Evaluation view** — two tabs:
   - **Visualisatie**: interactive Plotly chart with competencies on the Y-axis grouped by cluster, scores on the X-axis, one coloured dot per evaluator, and cluster averages in the labels. Hovering shows the rubric description for that competence × score cell.
   - **Reviews**: written evaluations and Q&A per evaluator.

If S3 is unreachable (e.g. during local development without credentials), the dashboard falls back to `sampledata.csv` and `sampledata_review.csv` and marks the session as *(testdata)*.

---

## Qualtrics / S3 data pipeline

Qualtrics exports survey responses to the S3 bucket `qualtrics-data-bucket-live` as timestamped CSV files (e.g. `qualtrics_live_2025-07-09_075851825.csv`). A new file is created on each export run, so responses accumulate across multiple files.

The dashboard fetches and concatenates **all** CSV files on login. During preprocessing:

| Raw Qualtrics column | Dashboard column |
|---|---|
| `C1_1`, `C1_2`, `C2_1` … | Competency names from `rubric.csv` (e.g. `Conceptual Thinking`) |
| `evaluator_4` + `evaluator_5` | `evaluator` (first + last name combined) |
| `evaluator_6` | dropped (email address) |
| `textual_feedback` | `evaluation` |
| `questions_1` … `questions_5` | `Q1` … `Q5` |

Score labels are translated from Dutch to English to match the rubric scale:

| Qualtrics (NL) | Rubric (EN) |
|---|---|
| Zwak | Weak |
| Onvoldoende | Insufficient |
| Voldoende | Sufficient |
| Goed | Good |
| Zeer Goed | Very Good |
| Uitstekend | Excellent |

The competency column mapping (`C1_1` → `Conceptual Thinking` etc.) is derived automatically from the cluster and competency order in `rubric.csv`, so it stays in sync if the rubric changes.

---

## Managing users and assignments

### Add a user

Add an entry to `users.yaml`:

```yaml
users:
  bas: test1
  davy: test2
  newuser: password
```

### Add student assignments

Either edit `assignments.csv` manually:

```
user,year,student
bas,2024-2025,Leon Dehullu
```

Or generate it from the Excel export using `extract_assignments.py`:

1. Place the Excel file in the project root
2. Set `INPUT_FILE` and `ACADEMIC_YEAR` at the top of the script
3. Run:

```console
python extract_assignments.py
```

This reads all `@ugent.be` email addresses from both the `promotoren:emails` and `begeleiders:emails` columns and writes one row per (student, UGent email) pair to `assignments_new.csv`. Non-UGent email addresses are ignored.

---

---

# Tests

The tests below document the incremental development steps. Each was a standalone proof-of-concept that was later integrated into `dashboard.py`.

### Test 1 — Set up a Streamlit server

- Create a simple [test app](app.py)
- Install dependencies
  *(`streamlit` is the main framework)*
    ```console
    pip install streamlit
    python -m streamlit run app.py
    ```

### Test 2 — Authentication of users

- Create a [YAML file](users.yaml) with credentials of dashboard users
- Install dependencies
  *(`pyyaml` allows working with YAML files)*
    ```console
    pip install pyyaml
    ```
- [App](app2.py) example that allows authentication with this YAML file
    ```console
    python -m streamlit run app2.py
    ```

### Test 3 — Get data from S3 bucket

- Install dependencies
  *(`boto3` is for S3 communication, `pandas` for data management & `dotenv` allows interaction with a .env file)*
    ```console
    pip install boto3 pandas python-dotenv
    ```
- Create IAM user (called `mp_dashboard`) with access to the bucket (called `qualtrics-data-bucket-live`)
- Store the user's access key and secret key in a `.env` file (in the home directory)
    ```ini
    AWS_ACCESS_KEY_ID=xxx
    AWS_SECRET_ACCESS_KEY=xxx
    AWS_DEFAULT_REGION=xxx
    ```
- [App](app3.py) that shows the latest CSV file in the bucket
    ```console
    python -m streamlit run app3.py
    ```

### Test 4 — Information selection

- Create [assignments.csv](assignments.csv) in which accounts are linked to master thesis students
- [App that allows selecting AJ & students](app4.py) based on `assignments.csv`
    ```console
    python -m streamlit run app4.py
    ```

### Test 5 — Visualisation

- Install dependencies
  *(`plotly` allows dataviz)*
    ```console
    pip install plotly
    ```
- Create a [sample data file](sampledata.csv)
- Create a [rubrics overview](rubric.csv)
- [App](app5.py) that visualizes data
    ```console
    python -m streamlit run app5.py
    ```
