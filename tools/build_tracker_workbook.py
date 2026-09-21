"""Apply the docs/09-workbook-review.md fixes to the Master Tracker."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import hrintel as H

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import FormulaRule

SRC = sys.argv[1]
DST = sys.argv[2]
# Rows pre-armed with validation and formulas. Sized to the trial, not to the
# sheet's limits: the delta formulas are SUMIFS/COUNTIFS over the whole column,
# so arming thousands of rows makes the file slow to open for no benefit.
ROWS = 250          # Raw_Data_Log - generous for a low-volume 8-week trial
RT_ROWS = 120       # Rating_Tracker - 4 entities x 9 weeks = 36 rows needed

FONT = "Arial"
HDR_FILL = PatternFill("solid", fgColor="D9E2EC")
HDR_FONT = Font(name=FONT, bold=True, color="1F2933")
BODY_FONT = Font(name=FONT)
NOTE_FONT = Font(name=FONT, italic=True, color="52606D")
THIN = Side(style="thin", color="BCCCDC")
BORDER = Border(bottom=THIN)

# --- controlled vocabularies (must stay in step with config/column_map.yaml) ---
ENTITIES = ["RK Group", "RK World Infocom", "Robust Kommerce", "Westbury Kommerce"]
PLATFORMS = ["AmbitionBox", "Glassdoor", "LinkedIn", "X / Twitter", "Reddit",
             "Quora", "YouTube", "Google Reviews", "Indeed"]
# 'Red Flag' removed: it is not a point on a sentiment scale and there is a
# separate flag column. 'Mixed' added: praise and complaint in one post is the
# most common real case and had nowhere to go.
SENTIMENT = ["Positive", "Neutral", "Mixed", "Negative"]
# 'Salary & Appraisals' split three ways: only non-payment is a red-flag
# trigger. 'Exit / Layoff' split: a layoff wave and a stream of resignations
# read very differently in a digest.
TOPICS = ["Culture", "Management", "Compensation", "Appraisals", "Payroll Delay",
          "Interviews", "Work Hours", "Workload", "Onboarding", "Exits", "Layoffs",
          "Safety / Legal", "Growth", "Facilities", "Transparency", "Job Security"]
AUTHOR = ["Current Employee", "Ex-Employee", "Candidate", "Intern", "Contractor",
          "Anonymous", "Unknown"]
YESNO = ["Yes", "No"]
FLAG_REASON = ["Names Individual", "Harassment / Safety", "Non-payment",
               "Legal / Regulatory", "Public Escalation Risk"]
STATUS = ["Needs Review", "Reviewed", "Escalated", "Closed", "Out of Scope"]
SEVERITY = ["High", "Critical"]
ESC_STATUS = ["Open", "Acknowledged", "Closed"]


def col(headers, name) -> str:
    """Column letter by header name.

    The validations, formulas and conditional formats used to hard-code letters,
    so inserting one column silently pointed the red-flag rule at the wrong
    field. Looking the letter up by name makes the header list the only place
    that has to be right.
    """
    return get_column_letter(headers.index(name) + 1)


def style_header(ws, headers, widths):
    for i, (head, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=i, value=head)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = BORDER
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"


def add_list_validation(ws, column_letter, values, prompt, rows=None):
    dv = DataValidation(
        type="list",
        formula1='"' + ",".join(values) + '"',
        allow_blank=True,
        showDropDown=False,   # False = show the arrow; True hides it
        errorTitle="Not on the list",
        error=f"Pick one of: {', '.join(values)}",
        promptTitle=column_letter,
        prompt=prompt,
    )
    ws.add_data_validation(dv)
    dv.add(f"{column_letter}2:{column_letter}{rows or ROWS}")


def set_body_font(ws, ncols, rows=None):
    for row in ws.iter_rows(min_row=2, max_row=rows or ROWS, max_col=ncols):
        for cell in row:
            cell.font = BODY_FONT


wb = openpyxl.load_workbook(SRC)

# ===================== Raw_Data_Log =====================
ws = wb["Raw_Data_Log"]
# Clear the old validations and headers; the tab holds no data.
ws.data_validations.dataValidation = []
for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
    for cell in row:
        cell.value = None

# One column per field in the canonical mentions schema (scripts/hrintel.py
# MENTION_FIELDS). The sheet is the data link the digest hands out, so a field
# the digest holds and the sheet cannot show is a field nobody can audit -
# and, before carry_forward existed, one the next import silently blanked.
HEADERS = [
    "Mention ID", "Date Logged", "Date Posted", "Week Of", "Entity", "Platform",
    "Source", "Sentiment", "Topic Category", "Title / Snippet", "Summary Overview",
    "Direct Link / URL", "Author Type", "Role / Department", "Stars", "Engagement",
    "Names Individual", "Red Flag Escalated", "Red Flag Reason", "Status",
    "Logged By", "Notes",
]
WIDTHS = [16, 12, 12, 12, 18, 15, 20, 12, 16, 30, 46, 34, 16, 18, 8,
          12, 15, 16, 20, 14, 12, 28]
style_header(ws, HEADERS, WIDTHS)
set_body_font(ws, len(HEADERS))

# Week Of derives from Date Posted so the sweeper never types it. WEEKDAY(d,3)
# is 0 on Monday through 6 on Sunday, so subtracting MOD(WEEKDAY(d,3) - start, 7)
# lands on the configured first day of the reporting week. Read from config so
# the sheet and the scripts cannot disagree about which day a week starts.
WEEK_START = H.week_start_day()
POSTED = col(HEADERS, "Date Posted")
for r in range(2, ROWS + 1):
    ws[f"{col(HEADERS, 'Week Of')}{r}"] = (
        f'=IF(${POSTED}{r}="","",'
        f'${POSTED}{r}-MOD(WEEKDAY(${POSTED}{r},3)-{WEEK_START},7))'
    )
    for name in ("Week Of", "Date Logged", "Date Posted"):
        ws[f"{col(HEADERS, name)}{r}"].number_format = "yyyy-mm-dd"
    ws[f"{col(HEADERS, 'Stars')}{r}"].number_format = "0.0"

add_list_validation(ws, col(HEADERS, "Entity"), ENTITIES,
                    "Which group entity this is about.")
add_list_validation(ws, col(HEADERS, "Platform"), PLATFORMS, "Where it was posted.")
add_list_validation(ws, col(HEADERS, "Sentiment"), SENTIMENT,
                    "Tag the post, not your view of the company. "
                    "Mixed = real praise AND a real complaint.")
add_list_validation(ws, col(HEADERS, "Topic Category"), TOPICS,
                    "One topic. See the Guide tab.")
add_list_validation(ws, col(HEADERS, "Author Type"), AUTHOR,
                    "Only if the post states or clearly implies it.")
add_list_validation(ws, col(HEADERS, "Names Individual"), YESNO,
                    "Does the post name an individual?")
add_list_validation(ws, col(HEADERS, "Red Flag Escalated"), YESNO,
                    "One of the five triggers on the Guide tab.")
add_list_validation(ws, col(HEADERS, "Red Flag Reason"), FLAG_REASON,
                    "Which trigger fired.")
add_list_validation(ws, col(HEADERS, "Status"), STATUS, "Needs Review until tagged.")

# Red rows for flags, amber for anything still untagged on send day.
# Conditional formats are *differential* formats: Excel reads the colour from
# bgColor, not fgColor, so a fill built the usual way renders as no colour.
red = PatternFill(bgColor="FADDDD", patternType="solid")
amber = PatternFill(bgColor="FBF0D9", patternType="solid")
span = f"A2:{get_column_letter(len(HEADERS))}{ROWS}"
flag = col(HEADERS, "Red Flag Escalated")
state = col(HEADERS, "Status")
ws.conditional_formatting.add(
    span, FormulaRule(formula=[f'${flag}2="Yes"'], fill=red, stopIfTrue=False))
ws.conditional_formatting.add(
    span, FormulaRule(formula=[f'${state}2="Needs Review"'], fill=amber))

# ===================== Rating_Tracker =====================
ws = wb["Rating_Tracker"]
ws.data_validations.dataValidation = []
for row in ws.iter_rows(min_row=1, max_row=max(ws.max_row, 1), max_col=max(ws.max_column, 1)):
    for cell in row:
        cell.value = None

# No stored delta column: build_digest.py derives week-on-week movement from
# consecutive snapshots, and a copy kept by hand drifts the first time anyone
# corrects a rating. Last week's row sits directly above for eyeballing.
# Rating and Reviews Count are the two the weekly three-minute check fills in.
# The rest - recommend %, CEO approval, sub-scores, profile URL - move slowly
# and are typed when they change, but they are columns here because the digest
# holds them and the sheet is what anyone auditing the digest opens.
RT = ["Week Of", "Entity",
      "AmbitionBox Rating", "AmbitionBox Reviews Count", "AmbitionBox Recommend %",
      "AmbitionBox Work-Life", "AmbitionBox Salary", "AmbitionBox Job Security",
      "AmbitionBox Growth", "AmbitionBox Culture", "AmbitionBox URL",
      "AmbitionBox Notes",
      "Glassdoor Rating", "Glassdoor Reviews Count", "Glassdoor Recommend %",
      "Glassdoor CEO Approval %", "Glassdoor Work-Life", "Glassdoor Compensation",
      "Glassdoor Job Security", "Glassdoor Career Opportunities", "Glassdoor Culture",
      "Glassdoor URL", "Glassdoor Notes", "Last Checked Date", "Checked By",
      "Notes"]
RT_W = [12, 20, 14, 14, 15, 14, 13, 14, 13, 13, 30, 44,
        14, 14, 15, 16, 14, 15, 14, 16, 13, 30, 44, 14, 12, 30]
style_header(ws, RT, RT_W)
set_body_font(ws, len(RT), rows=RT_ROWS)
add_list_validation(ws, col(RT, "Entity"), ENTITIES,
                    "One row per entity per week. APPEND, never overwrite.",
                    rows=RT_ROWS)

SCORES = [h for h in RT if h.endswith(
    ("Rating", "Work-Life", "Salary", "Job Security", "Growth", "Culture",
     "Compensation", "Career Opportunities"))]
for r in range(2, RT_ROWS + 1):
    for name in ("Week Of", "Last Checked Date"):
        ws[f"{col(RT, name)}{r}"].number_format = "yyyy-mm-dd"
    for name in SCORES:
        ws[f"{col(RT, name)}{r}"].number_format = "0.00"
    for name in ("AmbitionBox Recommend %", "Glassdoor Recommend %",
                 "Glassdoor CEO Approval %"):
        ws[f"{col(RT, name)}{r}"].number_format = "0"

# ===================== Escalations (new) =====================
ws = wb.create_sheet("Escalations", 2)
ESC = ["Escalation ID", "Raised At", "Week Of", "Mention ID", "Entity", "Platform",
       "Direct Link / URL", "Severity", "Reason", "Notified", "Notified At",
       "Owner", "Action Taken", "Status", "Closed At"]
ESC_W = [15, 12, 12, 16, 18, 15, 34, 11, 20, 26, 12, 14, 40, 14, 12]
style_header(ws, ESC, ESC_W)
set_body_font(ws, len(ESC), rows=RT_ROWS)
add_list_validation(ws, col(ESC, "Entity"), ENTITIES, "", rows=RT_ROWS)
add_list_validation(ws, col(ESC, "Platform"), PLATFORMS, "", rows=RT_ROWS)
add_list_validation(ws, col(ESC, "Severity"), SEVERITY, "Critical = harassment/safety naming a person, or media involved.", rows=RT_ROWS)
add_list_validation(ws, col(ESC, "Reason"), FLAG_REASON,
                    "Which of the five triggers.", rows=RT_ROWS)
add_list_validation(ws, col(ESC, "Status"), ESC_STATUS,
                    "Open until acknowledged.", rows=RT_ROWS)
for r in range(2, RT_ROWS + 1):
    for name in ("Raised At", "Week Of", "Notified At", "Closed At"):
        ws[f"{col(ESC, name)}{r}"].number_format = "yyyy-mm-dd"

wb.save(DST)
print("written:", DST)
