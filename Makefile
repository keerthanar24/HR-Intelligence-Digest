# Weekly operating loop for the HR Intelligence Digest.
# WEEK defaults to the most recently completed week (Monday-start).

WEEK ?= $(shell python3 -c "import sys;sys.path.insert(0,'scripts');import hrintel as H;print(H.last_complete_week())")
PY   ?= python3

.PHONY: help setup sheet alerts import collect scan validate digest weekly test clean

help:
	@echo "HR Intelligence Digest — week $(WEEK)"
	@echo ""
	@echo "  make setup     install the one dependency and report outstanding TODOs"
	@echo "  make sheet     print tab headers, dropdowns and formatting for the sheet"
	@echo "  make alerts    print search strings for Google Alerts and manual sweeps"
	@echo "  make import BOOK=tracker.xlsx   pull the workbook into data/"
	@echo "  make collect   pull the permitted feeds into data/mentions.csv"
	@echo "  make scan      suggest rows that may be red flags (a human decides)"
	@echo "  make validate  check config and data for the week"
	@echo "  make digest    build out/digest-$(WEEK).html and .txt"
	@echo "  make weekly    scan + validate + digest, in order"
	@echo "  make test      run the end-to-end smoke test"
	@echo ""
	@echo "Override the week:  make digest WEEK=2026-09-07"

setup:
	$(PY) -m pip install -r requirements.txt
	-$(PY) scripts/validate_data.py

sheet:
	$(PY) scripts/sheet_setup.py

alerts:
	$(PY) scripts/alert_queries.py

BOOK ?= HR_Intelligence_Master_Tracker.xlsx

import:
	$(PY) scripts/import_sheet.py $(BOOK)

collect:
	$(PY) scripts/collect_feeds.py

scan:
	$(PY) scripts/red_flags.py --scan
	$(PY) scripts/red_flags.py

validate:
	$(PY) scripts/validate_data.py --week $(WEEK)

# Fails if the week still has untagged mentions — tag them before sending.
digest:
	$(PY) scripts/build_digest.py --week $(WEEK) --strict

weekly: scan validate digest
	@echo ""
	@echo "Paste out/digest-$(WEEK).html into the email body. No attachments."

test:
	$(PY) tests/smoke_test.py

clean:
	rm -f out/digest-*.html out/digest-*.txt out/red-flag-*.txt
