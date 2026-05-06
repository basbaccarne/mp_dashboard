import pandas as pd

ACADEMIC_YEAR = "2025-2026"
INPUT_FILE = "data/2526-jun.xlsx"
OUTPUT_FILE = "data/assignments_new.csv"

df = pd.read_excel(INPUT_FILE, header=0)

rows = []
for _, row in df.iterrows():
    student = row["student"]

    # Gather all emails from both promotoren and begeleiders columns
    raw_emails = []
    for col in ["promotoren:emails", "begeleiders:emails"]:
        if pd.notna(row.get(col)):
            raw_emails.extend(str(row[col]).split(","))

    # Keep only @ugent.be addresses
    ugent_emails = [
        e.strip()
        for e in raw_emails
        if "@ugent.be" in e.strip().lower()
    ]

    for email in ugent_emails:
        rows.append(f"{email}, {ACADEMIC_YEAR}, {student}")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("user,year,student\n")
    f.write("\n".join(rows) + "\n")

print(f"Written {len(rows)} rows to {OUTPUT_FILE}")
