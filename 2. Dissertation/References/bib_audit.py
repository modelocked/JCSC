#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bib_audit.py — Paste-a-reference audit for Maynooth Harvard-friendly BibTeX data.

Default behavior: opens the GUI so you can paste an entry and click “Audit”.
Optional: run with --cli to use stdin instead.

What you get:
1) Suggested BibTeX (safe auto-fixes)
2) Omissions/Gaps list (what to correct and why)
"""

import sys
import re
import argparse
import datetime

# =========================
# CONFIG
# =========================
# REQUIRE initials per Maynooth Harvard
REQUIRE_ONLINE_ACCESS_BLOCK = True
STRICT_SENTENCE_CASE_HINT   = True
REQUIRE_INITIALS            = True

# =========================
# Regex helpers
# =========================
FIELD_RE      = re.compile(r'(?P<name>[A-Za-z]+)\s*=\s*\{(?P<value>.*?)\}\s*,?', re.DOTALL)
ENTRY_HEAD_RE = re.compile(r'@(?P<type>\w+)\s*\{\s*(?P<key>[^,]+)\s*,', re.IGNORECASE)

MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"]

# =========================
# Core helpers
# =========================
def parse_entry(text):
    m = ENTRY_HEAD_RE.search(text)
    if not m:
        raise ValueError("Could not find @type{key, ...} header in the pasted text.")
    etype = m.group('type').lower()
    key = m.group('key').strip()
    fields = {m.group('name').lower(): m.group('value').strip() for m in FIELD_RE.finditer(text)}
    return etype, key, fields

def sentence_case(title: str) -> str:
    """Naive sentence-case: keeps first word capitalized, lowers subsequent words
       (leaves short ALLCAPS tokens like acronyms intact; capitalizes word after colon)."""
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
    """
    True if any author looks like 'Surname, Firstname...' (not initials).
    Unicode-aware so it catches names with accents (e.g., René).
    """
    authors = re.split(r'\s+\band\b\s+', author_field, flags=re.IGNORECASE)
    for a in authors:
        a = a.strip()
        if not a:
            continue
        if a.startswith('{') and a.endswith('}'):
            continue  # corporate author
        # After comma, word of >=2 letters without a dot => full name (e.g., ", René", ", John")
        if re.search(r',\s*[^\W\d_]{2,}', a, flags=re.UNICODE):
            # allow legitimate initials forms like ", R." or ", R. J."
            if not re.search(r',\s*[A-Z]\.(?:\s*[A-Z]\.)*$', a):
                return True
    return False

def _givens_to_initials(givens: str) -> str:
    """
    Convert 'René' -> 'R.' ; 'Jean-Luc Marie' -> 'J.-L. M.' (preserves spaces/hyphens).
    Unicode-aware.
    """
    parts = re.split(r'(\s+|-)', givens.strip())
    out = []
    for p in parts:
        if not p or re.match(r'\s+|-', p):
            out.append(p)
        else:
            m = re.search(r'[^\W\d_]', p, flags=re.UNICODE)  # first letter
            if m:
                out.append(m.group(0).upper() + '.')
    return ''.join(out).replace('..', '.')

def enforce_initials(author_field: str) -> str:
    authors = re.split(r'\s+\band\b\s+', author_field, flags=re.IGNORECASE)
    fixed = []
    for a in authors:
        a = a.strip()
        if not a:
            continue
        if a.startswith('{') and a.endswith('}'):  # corporate author
            fixed.append(a)
            continue
        if ',' in a:
            surname, givens = a.split(',', 1)
            fixed.append(f"{surname.strip()}, {_givens_to_initials(givens)}")
        else:
            # Fallback 'Firstname Surname'
            parts = a.split()
            surname = parts[-1]
            givens = ' '.join(parts[:-1])
            fixed.append(f"{surname}, {_givens_to_initials(givens)}")
    return ' and '.join(fixed)

# =========================
# Suggestion + Issues
# =========================
def suggest_entry(etype, key, F):
    issues = []

    # Remove noisy fields that bloat/break references
    for k in list(F.keys()):
        if k.lower() in ('abstract',):
            issues.append(f"Removed noisy field '{k}'.")
            F.pop(k, None)

    # Enforce initials per Maynooth Harvard
    if REQUIRE_INITIALS and ('author' in F) and author_uses_full_given_names(F['author']):
        issues.append("Author uses full given names; use initials (Surname, X. or Surname, X. Y.) per Maynooth Harvard.")
        F['author'] = enforce_initials(F['author'])

    # Sentence case for article/online titles
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

    # Build suggested entry (deterministic order)
    order_hint = [
        'author','title','year','date','type','institution','organization',
        'journaltitle','volume','number','pages','edition','location','publisher',
        'note','url','urldate','addendum','issn','isbn','series','doi'
    ]
    keyline = f"@{etype.capitalize()}{{{key},"
    lines = [keyline]
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
    suggested = "\n".join(lines)
    return suggested, issues

# =========================
# CLI
# =========================
def run_cli():
    print("Paste a BibTeX entry. End with Ctrl-D (Linux/Mac) or Ctrl-Z + Enter (Windows).")
    text = sys.stdin.read()
    if not text.strip():
        print("No input provided.", file=sys.stderr)
        sys.exit(1)
    try:
        etype, key, F = parse_entry(text)
        suggested, issues = suggest_entry(etype, key, F.copy())
    except Exception as e:
        print(f"[Parse error] {e}")
        sys.exit(2)

    print("\nBib Audit Report")
    print("="*60)
    print(f"• Entry key: {key}")
    print(f"• Entry type: @{etype}")
    if issues:
        for i in issues:
            print(f"• {i}")
    else:
        print("• No issues found.")

    print("\nSuggested BibTeX")
    print("-"*60)
    print(suggested)

# =========================
# GUI
# =========================
def run_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Bib Audit (Maynooth Harvard helper)")
            self.geometry("1100x750")

            ttk.Label(self, text="Paste a single BibTeX entry below, then click Audit:").pack(anchor='w', padx=10, pady=(10,4))
            self.input = tk.Text(self, height=14, wrap='word')
            self.input.pack(fill='both', expand=False, padx=10, pady=4)

            btns = ttk.Frame(self)
            btns.pack(pady=6)
            ttk.Button(btns, text="Audit", command=self.on_audit).pack(side='left', padx=5)
            ttk.Button(btns, text="Clear", command=self.on_clear).pack(side='left', padx=5)

            frame = ttk.Frame(self)
            frame.pack(fill='both', expand=True, padx=10, pady=4)

            left = ttk.Frame(frame)
            right = ttk.Frame(frame)
            left.pack(side='left', fill='both', expand=True, padx=(0,5))
            right.pack(side='left', fill='both', expand=True, padx=(5,0))

            ttk.Label(left, text="Suggested BibTeX").pack(anchor='w')
            self.out_bib = tk.Text(left, wrap='none')
            self.out_bib.pack(fill='both', expand=True)

            ttk.Label(right, text="Omissions / Gaps Found").pack(anchor='w')
            self.out_issues = tk.Text(right, wrap='word')
            self.out_issues.pack(fill='both', expand=True)

        def on_clear(self):
            self.input.delete("1.0","end")
            self.out_bib.delete("1.0","end")
            self.out_issues.delete("1.0","end")

        def on_audit(self):
            text = self.input.get("1.0", "end").strip()
            self.out_bib.delete("1.0","end")
            self.out_issues.delete("1.0","end")
            if not text:
                messagebox.showwarning("No input", "Please paste a BibTeX entry first.")
                return
            try:
                etype, key, F = parse_entry(text)
                suggested, issues = suggest_entry(etype, key, F.copy())
            except Exception as e:
                messagebox.showerror("Parse error", str(e))
                return
            self.out_bib.insert("1.0", suggested)
            if issues:
                self.out_issues.insert("1.0", "\n".join(f"• {i}" for i in issues))
            else:
                self.out_issues.insert("1.0", "No issues found.")

    App().mainloop()

# =========================
# Entry point
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cli', action='store_true', help='Use stdin instead of GUI')
    args = ap.parse_args()

    if args.cli:
        run_cli()
        return

    # Default: try to open GUI; if Tkinter not available (e.g., headless), fall back to CLI.
    try:
        run_gui()
    except Exception as e:
        print(f"[GUI unavailable, falling back to CLI] {e}", file=sys.stderr)
        run_cli()

if __name__ == "__main__":
    main()
