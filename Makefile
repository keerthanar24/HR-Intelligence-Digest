# Weekly operating loop for the HR Intelligence Digest.
# WEEK defaults to the most recently completed week (Saturday-start, per config/settings.yaml).

WEEK ?= $(shell python3 -c "import sys;sys.path.insert(0,'scripts');import hrintel as H;print(H.last_complete_week())")
PY   ?= python3

.PHONY: help setup sheet alerts sweep import collect scan validate digest weekly auto logsweep logweek logmarket checkurls checkfeeds test clean

help:
	@echo "HR Intelligence Digest — week $(WEEK)"
	@echo ""
	@echo "  make setup     install the one dependency and report outstanding TODOs"
	@echo "  make sheet     print tab headers, dropdowns and formatting for the sheet"
	@echo "  make alerts    print search strings for Google Alerts and manual sweeps"
	@echo "  make sweep     print this week's sweep worksheet with every URL"
	@echo "  make daily     the 3-minute daily count check (same-day cover)"
	@echo "  make import BOOK=tracker.xlsx   pull the workbook into data/"
	@echo "  make collect   pull the permitted feeds into data/mentions.csv"
	@echo "  make log       show how to log a review as a mention"
	@echo "  make scan      suggest rows that may be red flags (a human decides)"
	@echo "  make validate  check config and data for the week"
	@echo "  make digest    build out/digest-$(WEEK).html and .txt"
	@echo "  make weekly    scan + validate + digest, in order"
	@echo "  make auto      collect + validate + digest (what the scheduler runs)"
	@echo "  make send      dry-run the email send (add --send to really send)"
	@echo "  make logmarket open roles and salary entries per entity (scope: job-market)"
	@echo "  make logsweep  tick off the channels you checked (LinkedIn, X, Quora, ...)"
	@echo "  make checkurls open every configured page and report dead links (one-off)"
	@echo "  make checkfeeds test every enabled alert/RSS URL — run after adding one"
	@echo "  make logweek   record the hours and what was new (do it the same Friday)"
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

daily:
	$(PY) scripts/daily_check.py

sweep:
	$(PY) scripts/alert_queries.py --format sweep --week $(WEEK)
	@$(PY) scripts/log_rating.py --status

BOOK ?= HR_Intelligence_Master_Tracker.xlsx

import:
	$(PY) scripts/import_sheet.py $(BOOK)

collect:
	$(PY) scripts/collect_feeds.py

log:
	@$(PY) scripts/log_mention.py --help | head -20
	@echo ""
	@$(PY) scripts/log_mention.py --vocab

scan:
	$(PY) scripts/red_flags.py --scan
	$(PY) scripts/red_flags.py

validate:
	$(PY) scripts/validate_data.py --week $(WEEK)

# Fails if the week still has untagged mentions — tag them before sending.
digest:
	$(PY) scripts/build_digest.py --week $(WEEK) --strict

auto:
	$(PY) scripts/weekly_run.py

weekly: scan validate digest
	@echo ""
	@echo "Paste out/digest-$(WEEK).html into the email body. No attachments."

send:
	$(PY) scripts/send_digest.py --week $(WEEK)

# One-off, after editing config/sources.yaml. Touches real sites, so not scheduled.
checkurls:
	$(PY) scripts/check_urls.py

# Run after creating a Google Alert. A feed URL that 400s means the alert
# behind it does not exist, usually because it was never saved.
checkfeeds:
	$(PY) scripts/check_urls.py --feeds

# The two scope figures that are neither a review nor a rating.
logmarket:
	$(PY) scripts/log_market.py --status

# The channels with no review count: only a person can say they were opened.
logsweep:
	$(PY) scripts/log_sweep.py --week $(WEEK)

# The two Phase 3 questions the data cannot answer for itself.
logweek:
	$(PY) scripts/log_week.py --week $(WEEK)

test:
	$(PY) tests/smoke_test.py

clean:
	rm -f out/digest-*.html out/digest-*.txt out/red-flag-*.txt
