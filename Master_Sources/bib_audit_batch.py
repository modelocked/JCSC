#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bib_audit_batch.py — Audit an entire .bib file (Maynooth Harvard rules).

Outputs:
1) Corrected/normalized .bib (auto-fixes applied where safe)
2) An issues report (what to correct and why, per entry)

Usage:
- GUI (default):    python bib_audit_batch.py
- CLI (stdin):      python bib_audit_batch.py --cli < Thesis_2025_2026.bib > cleaned.bib
                    (report goes to stderr)  OR  python bib_audit_batch.py --cli --report report.txt < in.bib > out.bib
"""

import sys
import re
import argparse
import datetime
from typing import List, Tuple, Dict

# =========================
# CONFIG (Maynooth Harvard)
# =========================
REQUIRE_ONLINE_ACCESS_BLOCK = True
STRICT_SENTENCE_CASE_HINT   = True
REQUIRE_INITIALS            = True

# =========================
# Regex helpers
# =========================
ENTRY_HEAD_RE = re.compile(r'@(?P<type>\w+)\s*\{\s*(?P<key>[^,]+)\s*,', re.IGNORECASE)
FIELD_RE      = re.compile(r'(?P<name>[A-Za-z]+)\s*=\s*\{(?P<value>.*?)\}\s*,?', re.DOTALL)

MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"]

# =========================
# Core helpers
# =========================
def sentence_case(title: str) -> str:
    if not title.strip():
        return title
    tokens = re.split(r'(\s+)', title)
    out = []
    first_alpha_done = False
    for t in tokens:
        if t.isspace():
            out.append(t)
            continue
        if not first_alpha_done:
            first_alpha_done = True
            if t.isupper() and len(t) <= 5:
                out.append(t)
            else:
                out.append(t[:1].upper() + t[1:].lower())
        else:
            if t.isupper() and len(t) <= 5:
                out.append(t)
            else:
                if out and out[-1].endswith(':'):
                    out.append(t[:1].upper() + t[1:].lower())
                else:
                    out.append(t.lower())
    return ''.join(out)

def iso_today():
    return datetime.date.today().isoformat()

def accessed_today():
    d = datetime.date.today()
    return f"(Accessed: {d.day} {MONTHS[d.month-1]} {d.year})"

# ---------- Initials enforcement (Unicode-aware) ----------
def author_uses_full_given_names(author_field: str) -> bool:
    authors = re.split(r'\s+\band\b\s+', author_field, flags=re.IGNORECASE)
    for a in authors:
        a = a.strip()
        if not a:
            continue
        if a.startswith('{') and a.endswith('}'):
            continue  # corporate author
        # After the comma: word of >=2 letters => likely full name (not "R.")
        if re.search(r',\s*[^\W\d_]{2,}', a, flags=re.UNICODE):
            # allow proper initials ", R." or ", R. J."
            if not re.search(r',\s*[A-Z]\.(?:\s*[A-Z]\.)*$', a):
                return True
    return False

def _givens_to_initials(givens: str) -> str:
    parts = re.split(r'(\s+|-)', givens.strip())
    out = []
    for p in parts:
        if not p or re.match(r'\s+|-', p):
            out.append(p)
        else:
            m = re.search(r'[^\W\d_]', p, flags=re.UNICODE)
            if m:
                out.append(m.group(0).upper() + '.')
    return ''.join(out).replace('..','.')

def enforce_initials(author_field: str) -> str:
    authors = re.split(r'\s+\band\b\s+', author_field, flags=re.IGNORECASE)
    fixed = []
    for a in authors:
        a = a.strip()
        if not a:
            continue
        if a.startswith('{') and a.endswith('}'):
            fixed.append(a)
            continue
        if ',' in a:
            surname, givens = a.split(',', 1)
            fixed.append(f"{surname.strip()}, {_givens_to_initials(givens)}")
        else:
            parts = a.split()
            surname = parts[-1]
            givens = ' '.join(parts[:-1])
            fixed.append(f"{surname}, {_givens_to_initials(givens)}")
    return ' and '.join(fixed)

def parse_entry(text: str) -> Tuple[str,str,Dict[str,str]]:
    m = ENTRY_HEAD_RE.search(text)
    if not m:
        raise ValueError("Could not find @type{key, ...} in entry.")
    etype = m.group('type').lower()
    key   = m.group('key').strip()
    fields = {m.group('name').lower(): m.group('value').strip() for m in FIELD_RE.finditer(text)}
    return etype, key, fields

def rebuild_entry(etype: str, key: str, F: Dict[str,str]) -> str:
    order_hint = [
        'author','title','year','date','type','institution','organization',
        'journaltitle','volume','number','pages','edition','location','publisher',
        'note','url','urldate','addendum','issn','isbn','series','doi'
    ]
    lines = [f"@{etype.capitalize()}{{{key},"]
    used = set()
    for k in order_hint:
        if k in F and F[k] is not None and str(F[k]).strip():
            lines.append(f"  {k:<12}= {{{F[k]}}},")
            used.add(k)
    for k,v in F.items():
        if k not in used:
            lines.append(f"  {k:<12}= {{{v}}},")
    if len(lines) > 1 and lines[-1].endswith(','):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)

def suggest_entry(etype: str, key: str, F: Dict[str,str]) -> Tuple[str, List[str]]:
    issues = []

    # Trim noisy fields
    for k in list(F.keys()):
        if k.lower() in ('abstract',):
            issues.append(f"Removed noisy field '{k}'.")
            F.pop(k, None)

    # Enforce initials
    if REQUIRE_INITIALS and ('author' in F) and author_uses_full_given_names(F['author']):
        issues.append("Author uses full given names; use initials (Surname, X. or Surname, X. Y.) per Maynooth Harvard.")
        F['author'] = enforce_initials(F['author'])

    # Sentence case for article/online
    if STRICT_SENTENCE_CASE_HINT and etype in ('article','online'):
        sc = sentence_case(F.get('title',''))
        if sc and sc != F.get('title',''):
            issues.append("Title looked like Title Case; converted to sentence case in suggestion.")
            F['title'] = sc

    # Online block
    if etype in ('online','electronic'):
        if 'note' not in F or F['note'].strip().lower() != '[online]':
            issues.append("Missing note = {[Online]} for online source.")
            F['note'] = '[Online]'
        if 'urldate' not in F:
            issues.append("Missing urldate (ISO YYYY-MM-DD).")
            F['urldate'] = iso_today()
        if 'addendum' not in F or 'Accessed' not in F.get('addendum',''):
            issues.append("Missing addendum with Accessed: Day Month Year.")
            F['addendum'] = accessed_today()
        if 'url' not in F or not F['url'].strip():
            issues.append("Missing url for online source.")

    # Article requirements
    if etype == 'article':
        if 'journaltitle' not in F:
            issues.append("Missing journaltitle for article.")
            F['journaltitle'] = '<ADD JOURNAL TITLE>'
        if 'pages' not in F:
            issues.append("Missing pages for article.")
            F['pages'] = '<ADD PAGES>'
        if ('volume' not in F) and ('number' not in F):
            issues.append("Missing volume/number for article.")
            F['volume'] = '<ADD VOLUME>'

    # Book requirements
    if etype == 'book':
        for req in ('publisher','location'):
            if req not in F:
                issues.append(f"Missing {req} for book.")
                F[req] = f'<ADD {req.upper()}>'

    # Thesis requirements
    if etype == 'thesis':
        for req in ('type','institution'):
            if req not in F:
                issues.append(f"Missing {req} for thesis.")
                F[req] = f'<ADD {req.upper()}>'

    # year vs date
    if 'date' in F and 'year' in F:
        issues.append("Both 'date' and 'year' present — pick one (usually 'year').")

    # institution vs organization
    if ('institution' in F and 'organization' in F):
        issues.append("Both 'institution' and 'organization' present — keep one consistently.")

    # edition sanity
    if 'edition' in F and not re.fullmatch(r'\d+|[0-9]+(st|nd|rd|th)', F['edition'], flags=re.IGNORECASE):
        issues.append("Edition should be numeric (e.g., 3) or ordinal (e.g., 3rd).")

    return rebuild_entry(etype, key, F), issues

# =========================
# Multi-entry parsing
# =========================
def split_entries(bib_text: str) -> List[str]:
    """
    Robust-ish splitter: scans for '@', then consumes until the matching closing '}' at top nesting.
    Handles nested braces in field values.
    """
    entries = []
    i = 0
    n = len(bib_text)
    while i < n:
        at = bib_text.find('@', i)
        if at == -1:
            break
        # skip if it's within a comment line starting with %
        if at > 0:
            prev_nl = bib_text.rfind('\n', 0, at)
            if prev_nl != -1 and bib_text[prev_nl+1:at].lstrip().startswith('%'):
                i = at + 1
                continue
        # find first '{' after the @type
        brace = bib_text.find('{', at)
        if brace == -1:
            break
        depth = 1
        j = brace + 1
        while j < n and depth > 0:
            if bib_text[j] == '{':
                depth += 1
            elif bib_text[j] == '}':
                depth -= 1
            j += 1
        if depth == 0:
            entries.append(bib_text[at:j])
            i = j
        else:
            # unmatched; bail out with remainder
            entries.append(bib_text[at:])
            break
    return entries

# =========================
# Batch audit
# =========================
def audit_all(bib_text: str) -> Tuple[str, str]:
    """
    Returns (cleaned_bib, report_text)
    """
    entries = split_entries(bib_text)
    cleaned_chunks = []
    report_lines = []
    for raw in entries:
        raw_stripped = raw.strip()
        if not raw_stripped:
            continue
        try:
            etype, key, F = parse_entry(raw_stripped)
            suggested, issues = suggest_entry(etype, key, F.copy())
            cleaned_chunks.append(suggested)
            hdr = f"[{key}] @{etype}"
            if issues:
                report_lines.append(hdr)
                for it in issues:
                    report_lines.append(f"  - {it}")
            else:
                report_lines.append(f"{hdr} — OK")
        except Exception as e:
            # Keep original chunk if parse fails; log error
            report_lines.append(f"[?] Parse error: {e}")
            report_lines.append("  (Entry snippet)")
            report_lines.append("  " + raw_stripped[:200].replace("\n"," ") + ("..." if len(raw_stripped)>200 else ""))
            cleaned_chunks.append(raw_stripped)  # preserve original to avoid data loss
    cleaned_bib = "\n\n".join(cleaned_chunks) + "\n"
    report_text = "\n".join(report_lines) + "\n"
    return cleaned_bib, report_text

# =========================
# CLI
# =========================
def run_cli(report_path: str = None):
    src = sys.stdin.read()
    if not src.strip():
        print("No input .bib provided on stdin.", file=sys.stderr)
        sys.exit(1)
    cleaned, report = audit_all(src)
    # write cleaned to stdout
    sys.stdout.write(cleaned)
    # write report
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
    else:
        sys.stderr.write(report)

# =========================
# GUI
# =========================
def run_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Bib Audit — Batch (Maynooth Harvard)")
            self.geometry("1200x800")

            topbar = ttk.Frame(self)
            topbar.pack(fill='x', padx=10, pady=8)

            ttk.Button(topbar, text="Open .bib…", command=self.load_file).pack(side='left', padx=5)
            ttk.Button(topbar, text="Audit All", command=self.on_audit).pack(side='left', padx=5)
            ttk.Button(topbar, text="Save Cleaned .bib…", command=self.save_cleaned).pack(side='left', padx=5)
            ttk.Button(topbar, text="Save Report…", command=self.save_report).pack(side='left', padx=5)

            paned = ttk.PanedWindow(self, orient='horizontal')
            paned.pack(fill='both', expand=True, padx=10, pady=8)

            # Input .bib
            left = ttk.Frame(paned)
            ttk.Label(left, text="Input .bib (paste or open file)").pack(anchor='w')
            self.in_text = tk.Text(left, wrap='none')
            self.in_text.pack(fill='both', expand=True)
            paned.add(left, weight=1)

            # Cleaned .bib
            mid = ttk.Frame(paned)
            ttk.Label(mid, text="Cleaned .bib (auto-fixes applied)").pack(anchor='w')
            self.out_clean = tk.Text(mid, wrap='none')
            self.out_clean.pack(fill='both', expand=True)
            paned.add(mid, weight=1)

            # Report
            right = ttk.Frame(paned)
            ttk.Label(right, text="Issues Report").pack(anchor='w')
            self.out_report = tk.Text(right, wrap='word')
            self.out_report.pack(fill='both', expand=True)
            paned.add(right, weight=1)

        def load_file(self):
            path = filedialog.askopenfilename(filetypes=[("BibTeX", "*.bib"), ("All files", "*.*")])
            if not path: return
            with open(path, "r", encoding="utf-8") as f:
                self.in_text.delete("1.0","end")
                self.in_text.insert("1.0", f.read())

        def on_audit(self):
            src = self.in_text.get("1.0","end")
            if not src.strip():
                messagebox.showwarning("No input", "Paste or open a .bib file first.")
                return
            cleaned, report = audit_all(src)
            self.out_clean.delete("1.0","end")
            self.out_clean.insert("1.0", cleaned)
            self.out_report.delete("1.0","end")
            self.out_report.insert("1.0", report)

        def save_cleaned(self):
            data = self.out_clean.get("1.0","end")
            if not data.strip():
                messagebox.showinfo("Nothing to save", "Run Audit All first.")
                return
            path = filedialog.asksaveasfilename(defaultextension=".bib", filetypes=[("BibTeX", "*.bib")])
            if not path: return
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)

        def save_report(self):
            data = self.out_report.get("1.0","end")
            if not data.strip():
                messagebox.showinfo("Nothing to save", "Run Audit All first.")
                return
            path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
            if not path: return
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)

    App().mainloop()

# =========================
# Entry
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cli', action='store_true', help='Use stdin/stdout instead of GUI')
    ap.add_argument('--report', type=str, default=None, help='Path to write the issues report (CLI only).')
    args = ap.parse_args()

    if args.cli:
        run_cli(report_path=args.report)
        return

    try:
        run_gui()
    except Exception as e:
        print(f"[GUI unavailable, falling back to CLI] {e}", file=sys.stderr)
        run_cli(report_path=args.report)

if __name__ == "__main__":
    main()
