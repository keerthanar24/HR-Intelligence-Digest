"""Apply the docs/09-workbook-review.md fixes to the Master Tracker."""
import sys
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

HEADERS = [
    "Mention ID", "Date Logged", "Date Posted", "Week Of", "Entity", "Platform",
    "Sentiment", "Topic Category", "Summary Overview", "Direct Link / URL",
    "Author Type", "Engagement", "Names Individual", "Red Flag Escalated",
    "Red Flag Reason", "Status", "Notes",
]
WIDTHS = [16, 12, 12, 12, 18, 15, 12, 16, 46, 34, 16, 12, 15, 16, 20, 14, 28]
style_header(ws, HEADERS, WIDTHS)
set_body_font(ws, len(HEADERS))

# Week Of derives from Date Posted so the sweeper never types it. WEEKDAY(d,3)
# is 0 on Monday, so d - WEEKDAY(d,3) is that week's Monday.
for r in range(2, ROWS + 1):
    ws.cell(row=r, column=4).value = f'=IF($C{r}="","",$C{r}-WEEKDAY($C{r},3))'
    ws.cell(row=r, column=4).number_format = "yyyy-mm-dd"
    ws.cell(row=r, column=2).number_format = "yyyy-mm-dd"
    ws.cell(row=r, column=3).number_format = "yyyy-mm-dd"

add_list_validation(ws, "E", ENTITIES, "Which group entity this is about.")
add_list_validation(ws, "F", PLATFORMS, "Where it was posted.")
add_list_validation(ws, "G", SENTIMENT,
                    "Tag the post, not your view of the company. "
                    "Mixed = real praise AND a real complaint.")
add_list_validation(ws, "H", TOPICS, "One topic. See the Guide tab.")
add_list_validation(ws, "K", AUTHOR, "Only if the post states or clearly implies it.")
add_list_validation(ws, "M", YESNO, "Does the post name an individual?")
add_list_validation(ws, "N", YESNO, "One of the five triggers on the Guide tab.")
add_list_validation(ws, "O", FLAG_REASON, "Which trigger fired.")
add_list_validation(ws, "P", STATUS, "Needs Review until tagged.")

# Red rows for flags, amber for anything still untagged on send day.
# Conditional formats are *differential* formats: Excel reads the colour from
# bgColor, not fgColor, so a fill built the usual way renders as no colour.
red = PatternFill(bgColor="FADDDD", patternType="solid")
amber = PatternFill(bgColor="FBF0D9", patternType="solid")
span = f"A2:Q{ROWS}"
ws.conditional_formatting.add(span, FormulaRule(formula=['$N2="Yes"'], fill=red, stopIfTrue=False))
ws.conditional_formatting.add(span, FormulaRule(formula=['$P2="Needs Review"'], fill=amber))

# ===================== Rating_Tracker =====================
ws = wb["Rating_Tracker"]
ws.data_validations.dataValidation = []
for row in ws.iter_rows(min_row=1, max_row=max(ws.max_row, 1), max_col=max(ws.max_column, 1)):
    for cell in row:
        cell.value = None

# No stored delta column: build_digest.py derives week-on-week movement from
# consecutive snapshots, and a copy kept by hand drifts the first time anyone
# corrects a rating. Last week's row sits directly above for eyeballing.
RT = ["Week Of", "Entity", "AmbitionBox Rating", "AmbitionBox Reviews Count",
      "Glassdoor Rating", "Glassdoor Reviews Count", "Last Checked Date", "Notes"]
RT_W = [12, 20, 16, 16, 16, 16, 14, 40]
style_header(ws, RT, RT_W)
set_body_font(ws, len(RT), rows=RT_ROWS)
add_list_validation(ws, "B", ENTITIES, "One row per entity per week. APPEND, never overwrite.",
                    rows=RT_ROWS)

for r in range(2, RT_ROWS + 1):
    ws.cell(row=r, column=1).number_format = "yyyy-mm-dd"
    ws.cell(row=r, column=7).number_format = "yyyy-mm-dd"
    ws.cell(row=r, column=3).number_format = "0.00"
    ws.cell(row=r, column=5).number_format = "0.00"

# ===================== Escalations (new) =====================
ws = wb.create_sheet("Escalations", 2)
ESC = ["Escalation ID", "Raised At", "Week Of", "Mention ID", "Entity", "Platform",
       "Direct Link / URL", "Severity", "Reason", "Notified", "Notified At",
       "Owner", "Action Taken", "Status", "Closed At"]
ESC_W = [15, 12, 12, 16, 18, 15, 34, 11, 20, 26, 12, 14, 40, 14, 12]
style_header(ws, ESC, ESC_W)
set_body_font(ws, len(ESC), rows=RT_ROWS)
add_list_validation(ws, "E", ENTITIES, "", rows=RT_ROWS)
add_list_validation(ws, "F", PLATFORMS, "", rows=RT_ROWS)
add_list_validation(ws, "H", SEVERITY, "Critical = harassment/safety naming a person, or media involved.", rows=RT_ROWS)
add_list_validation(ws, "I", FLAG_REASON, "Which of the five triggers.", rows=RT_ROWS)
add_list_validation(ws, "N", ESC_STATUS, "Open until acknowledged.", rows=RT_ROWS)
for r in range(2, RT_ROWS + 1):
    for col in (2, 3, 11, 15):
        ws.cell(row=r, column=col).number_format = "yyyy-mm-dd"

wb.save(DST)
print("written:", DST)
