"""
CSV/XLSX reading, column mapping, and validation (spec Sections 2-4). Reader/mapping/validation
functions are pure Python (stdlib csv + openpyxl, both available in this environment) - no DB -
so they're genuinely tested in tests_pure/, unlike staging.py which needs the DB session to
write into price_review_files/price_review_lines and stays syntax-checked-only for now.
"""
