"""
Addendum Merger — Architectural Drawings
-----------------------------------------
Merges two addendum PDFs into one up-to-date set using Bluebeam page labels.

HOW IT WORKS:
  1. Reads page labels from both PDFs.
  2. Matches pages by sheet number (everything before the last space-separated
     tag, e.g. "A-111A" from "A-111A ADD04" or "A-111A IFB01").
  3. Replaces matching pages in the base with the update version.
     Replaced pages keep the update's tag (e.g. ADD04).
  4. Inserts brand-new sheets from the update in sequential sheet-number order
     (e.g. G-120 is inserted between G-113A and G-201).
  5. Unchanged pages keep their original tag exactly as-is.
  6. Saves one merged PDF — same order as base, updated pages swapped in.

HOW TO USE:
1. Make sure Python is installed on your computer.
2. Install the required library:
       pip install pypdf
3. Run this script:
       python addendum_mergerv5.py
4. Select Base PDF, Update PDF, output folder, click Merge.
"""

import os
import re
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, DictionaryObject, NameObject,
    NumberObject, TextStringObject
)


# ── Label helpers ──────────────────────────────────────────────────────────

def get_page_labels(reader: PdfReader) -> list:
    """Return a list of page label strings, one per page."""
    try:
        raw = list(reader.page_labels)
    except Exception:
        return [""] * len(reader.pages)
    labels = []
    for i in range(len(reader.pages)):
        label = raw[i].strip() if i < len(raw) and raw[i] else ""
        labels.append(label)
    return labels


def detect_tag(labels: list) -> str:
    """Return the tag (last space-separated token) from the first labeled page."""
    for label in labels:
        parts = label.rsplit(" ", 1)
        if len(parts) == 2 and parts[1]:
            return parts[1]
    return ""


def strip_tag(label: str) -> str:
    """Remove the trailing tag token to get the bare sheet key.

    e.g. 'A-111A ADD04' -> 'A-111A'
         'G-001 IFB01'  -> 'G-001'
    """
    parts = label.rsplit(" ", 1)
    if len(parts) == 2:
        return parts[0].strip()
    return label.strip()


def sheet_sort_key(key: str) -> list:
    """Return a sortable key for a sheet number string."""
    parts = re.split(r'[-.]', key)
    result = []
    for part in parts:
        for chunk in re.findall(r'[A-Za-z]+|\d+', part):
            if chunk.isdigit():
                result.append((0, int(chunk)))
            else:
                result.append((1, chunk.upper()))
    return result


def get_prefix(key: str) -> str:
    """Extract the discipline prefix (e.g. 'G-', 'A-', 'FH-A', 'FH-I')."""
    m = re.match(r'^([A-Za-z]+-[A-Za-z]*)', key)
    return m.group(1) if m else key


def find_insert_after(merged_labels: list, new_key: str) -> int:
    """Find the index after which to insert a new sheet.

    1. Last same-prefix page sorting strictly before new_key -> insert after it.
    2. New key sorts before all same-prefix pages -> insert just before first one.
    3. Prefix absent -> insert after last page of preceding discipline group,
       respecting the file's existing discipline order.
    """
    new_prefix = get_prefix(new_key)
    new_sort   = sheet_sort_key(new_key)

    # Pass 1: last same-prefix page < new_key
    best_same_prefix = -1
    for m_idx, m_label in enumerate(merged_labels):
        m_key = strip_tag(m_label)
        if get_prefix(m_key) == new_prefix and sheet_sort_key(m_key) < new_sort:
            best_same_prefix = m_idx
    if best_same_prefix != -1:
        return best_same_prefix

    # Pass 2: new key sorts before all existing same-prefix pages
    for m_idx, m_label in enumerate(merged_labels):
        if get_prefix(strip_tag(m_label)) == new_prefix:
            return m_idx - 1

    # Pass 3: prefix absent — use file's discipline order
    prefix_last_idx = {}
    prefix_order    = []
    seen_prefixes   = set()
    for m_idx, m_label in enumerate(merged_labels):
        p = get_prefix(strip_tag(m_label))
        prefix_last_idx[p] = m_idx
        if p not in seen_prefixes:
            prefix_order.append(p)
            seen_prefixes.add(p)

    insert_after = -1
    for p in prefix_order:
        rep_key = next(strip_tag(ml) for ml in merged_labels
                       if get_prefix(strip_tag(ml)) == p)
        if sheet_sort_key(rep_key) < new_sort:
            insert_after = prefix_last_idx[p]
    return insert_after


def set_page_labels_on_writer(writer: PdfWriter, labels: list):
    """Write per-page labels into the PDF so Bluebeam picks them up."""
    nums = ArrayObject()
    for i, label in enumerate(labels):
        nums.append(NumberObject(i))
        entry = DictionaryObject()
        entry[NameObject("/P")] = TextStringObject(label)
        nums.append(entry)
    page_labels_dict = DictionaryObject()
    page_labels_dict[NameObject("/Nums")] = nums
    writer._root_object[NameObject("/PageLabels")] = page_labels_dict


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


# ── Changelog builder ──────────────────────────────────────────────────────

def build_changelog_text(result, base_path, update_path, output_path) -> str:
    """Build a plain-text changelog string suitable for saving to a .txt file."""
    replaced_list = result["replaced"]
    appended_list = result["appended"]
    lines = []
    lines.append("=" * 52)
    lines.append("ADDENDUM MERGER — CHANGELOG")
    lines.append("=" * 52)
    lines.append(f"Date:        {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    lines.append(f"Base PDF:    {os.path.basename(base_path)}")
    lines.append(f"Update PDF:  {os.path.basename(update_path)}")
    lines.append(f"Output PDF:  {os.path.basename(output_path)}")
    lines.append("")
    lines.append(f"Total pages:  {result['total']}")
    lines.append(f"Replaced:     {len(replaced_list)}")
    lines.append(f"New sheets:   {len(appended_list)}")
    lines.append(f"Unchanged:    {result['unchanged']}")
    lines.append("")
    lines.append("-" * 52)
    lines.append("REPLACED SHEETS")
    lines.append("-" * 52)
    if replaced_list:
        for l in replaced_list:
            lines.append(f"  {l}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("-" * 52)
    lines.append("NEW SHEETS")
    lines.append("-" * 52)
    if appended_list:
        for l in appended_list:
            lines.append(f"  {l}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"Output saved to:")
    lines.append(f"  {output_path}")
    lines.append("")
    return "\n".join(lines)


# ── Core merge ─────────────────────────────────────────────────────────────

def merge_addendums(base_path, update_path, output_path, progress_cb=None):
    """
    True replacement merge:
    - Walks the base page-by-page in order.
    - Where the sheet key matches an update page, swaps in the update page
      (which carries the update's own tag, e.g. ADD04).
    - Unchanged base pages keep their original label/tag exactly.
    - New pages (not in base) are inserted at their correct sequential
      position based on sheet number sort order.
    Returns summary dict.
    """
    base_reader   = PdfReader(base_path)
    update_reader = PdfReader(update_path)

    base_labels   = get_page_labels(base_reader)
    update_labels = get_page_labels(update_reader)

    # Validate
    missing_base   = sum(1 for l in base_labels   if not l)
    missing_update = sum(1 for l in update_labels if not l)
    if missing_base or missing_update:
        raise ValueError(
            f"Some pages are missing Bluebeam page labels:\n"
            f"  Base PDF:   {missing_base} unlabeled page(s)\n"
            f"  Update PDF: {missing_update} unlabeled page(s)\n\n"
            f"Please set page labels in Bluebeam before merging."
        )

    # Build ordered update list and a quick lookup by sheet key
    update_entries = []   # [(key, page, label), ...] in update order
    update_key_set = set()
    for i, label in enumerate(update_labels):
        key = strip_tag(label)
        update_entries.append((key, update_reader.pages[i], label))
        update_key_set.add(key)

    base_key_set = set(strip_tag(l) for l in base_labels)

    total = len(base_reader.pages) + len(update_reader.pages)
    replaced  = []
    unchanged = []
    appended  = []

    # Build a lookup for quick replacement: key -> (page, label)
    update_map = {key: (page, label) for key, page, label in update_entries}

    # Walk base pages, swapping in update pages where keys match.
    # Labels flow through as-is — no tag rewriting.
    merged_pages  = []
    merged_labels = []

    for i, (page, label) in enumerate(zip(base_reader.pages, base_labels)):
        key = strip_tag(label)
        if key in update_map:
            merged_pages.append(update_map[key][0])
            merged_labels.append(update_map[key][1])
            replaced.append(label)
        else:
            merged_pages.append(page)
            merged_labels.append(label)
            unchanged.append(label)

        if progress_cb:
            progress_cb(i + 1, total,
                        f"Processing base sheet {i + 1} of {len(base_reader.pages)}: {label}…")

    # Insert new pages at their correct sequential position.
    new_entries = [(key, page, label)
                   for key, page, label in update_entries
                   if key not in base_key_set]

    for j, (new_key, new_page, new_label) in enumerate(new_entries):
        insert_after = find_insert_after(merged_labels, new_key)
        insert_at = insert_after + 1
        merged_pages.insert(insert_at, new_page)
        merged_labels.insert(insert_at, new_label)
        appended.append(new_label)

        if progress_cb:
            progress_cb(len(base_reader.pages) + j + 1, total,
                        f"Inserting new sheet: {new_label}…")

    # Write output — labels are used exactly as they came from each source PDF
    writer = PdfWriter()
    for page in merged_pages:
        writer.add_page(page)
    set_page_labels_on_writer(writer, merged_labels)

    with open(output_path, "wb") as f:
        writer.write(f)

    return {
        "total":     len(merged_pages),
        "replaced":  replaced,
        "appended":  appended,
        "unchanged": len(unchanged),
    }


# ── GUI ────────────────────────────────────────────────────────────────────

class ResultDialog(tk.Toplevel):
    """Scrollable merge-result dialog with changelog export and reset-on-OK."""

    def __init__(self, parent, result, base_path, update_path, output_path):
        super().__init__(parent)
        self.title("Merge Complete")
        self.resizable(False, True)
        self.configure(bg="#1e1e2e")
        self.grab_set()

        self._parent      = parent
        self._result      = result
        self._base_path   = base_path
        self._update_path = update_path
        self._output_path = output_path

        BG     = "#1e1e2e"
        CARD   = "#2a2a3d"
        ACCENT = "#7c6af7"
        FG     = "#e0e0f0"
        MUTED  = "#888aaa"
        GREEN  = "#50c878"
        ORANGE = "#f07050"
        FONT   = ("Segoe UI", 10)
        FONT_B = ("Segoe UI", 10, "bold")

        replaced_list = result["replaced"]
        appended_list = result["appended"]

        # ── Header stats ──
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 8))

        tk.Label(header, text="Merged PDF saved!", font=("Segoe UI", 13, "bold"),
                 bg=BG, fg=FG).pack(anchor="w")

        stats = [
            (f"📄 Total pages:   {result['total']}",  FG),
            (f"🔄 Replaced:      {len(replaced_list)}", GREEN),
            (f"➕ New sheets:    {len(appended_list)}", ORANGE),
            (f"✓  Unchanged:    {result['unchanged']}", MUTED),
        ]
        for text, color in stats:
            tk.Label(header, text=text, font=FONT, bg=BG, fg=color).pack(anchor="w")

        # ── Scrollable body ──
        body_frame = tk.Frame(self, bg=BG)
        body_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        scrollbar = tk.Scrollbar(body_frame, bg=CARD, troughcolor=BG,
                                 activebackground=ACCENT)
        scrollbar.pack(side="right", fill="y")

        text = tk.Text(body_frame, font=FONT, bg=CARD, fg=FG,
                       relief="flat", wrap="none", width=44, height=18,
                       yscrollcommand=scrollbar.set,
                       state="normal", cursor="arrow",
                       padx=10, pady=8)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text.yview)

        # Color tags
        text.tag_config("heading", foreground=FG,    font=("Segoe UI", 10, "bold"))
        text.tag_config("green",   foreground=GREEN)
        text.tag_config("orange",  foreground=ORANGE)
        text.tag_config("muted",   foreground=MUTED)

        def insert(txt, tag=""):
            text.insert("end", txt, tag)

        insert("Replaced sheets:\n", "heading")
        if replaced_list:
            for l in replaced_list:
                insert(f"  • {l}\n", "green")
        else:
            insert("  (none)\n", "muted")

        insert("\nNew sheets:\n", "heading")
        if appended_list:
            for l in appended_list:
                insert(f"  • {l}\n", "orange")
        else:
            insert("  (none)\n", "muted")

        insert("\nSaved to:\n", "heading")
        insert(f"  {output_path}\n", "muted")

        text.config(state="disabled")

        # ── Buttons ──
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(pady=(4, 16))

        tk.Button(btn_frame, text="Export Changelog…", font=FONT_B,
                  bg=CARD, fg=FG, relief="flat", padx=16, pady=6,
                  cursor="hand2", command=self._export).pack(side="left", padx=(0, 8))

        tk.Button(btn_frame, text="OK", font=FONT_B,
                  bg=ACCENT, fg="white", relief="flat", padx=32, pady=6,
                  cursor="hand2", command=self._ok).pack(side="left")

        # Size and center over parent
        self.update_idletasks()
        w, h = 420, 500
        px = parent.winfo_rootx() + (parent.winfo_width()  - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{px}+{py}")

    def _export(self):
        """Save the changelog to a .txt file."""
        # Default filename mirrors the output PDF name with _changelog suffix
        base_name = os.path.splitext(os.path.basename(self._output_path))[0]
        default_name = f"{base_name}_changelog.txt"
        default_dir  = os.path.dirname(self._output_path)

        save_path = filedialog.asksaveasfilename(
            parent=self,
            title="Save Changelog",
            initialdir=default_dir,
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not save_path:
            return

        changelog = build_changelog_text(
            self._result, self._base_path, self._update_path, self._output_path
        )
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(changelog)
            messagebox.showinfo("Saved", f"Changelog saved to:\n{save_path}", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save changelog:\n{e}", parent=self)

    def _ok(self):
        """Close the dialog and reset the main window for the next merge."""
        self._parent._reset()
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Addendum Merger — Architectural Drawings")
        self.resizable(False, False)
        self.configure(bg="#1e1e2e")
        self._base_path   = None
        self._update_path = None
        self._out_dir     = None
        self._build_ui()

    def _build_ui(self):
        PAD    = 18
        BG     = "#1e1e2e"
        CARD   = "#2a2a3d"
        ACCENT = "#7c6af7"
        FG     = "#e0e0f0"
        MUTED  = "#888aaa"
        GREEN  = "#50c878"
        ORANGE = "#f07050"
        YELLOW = "#f0c060"
        FONT   = ("Segoe UI", 10)
        FONT_B = ("Segoe UI", 10, "bold")

        tk.Label(self, text="Addendum Merger", font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=FG).grid(row=0, column=0, columnspan=3,
                                    padx=PAD*2, pady=(PAD*1.5, 2), sticky="w")
        tk.Label(self,
                 text="Replaces matching pages from the update into the base.\n"
                      "Updated pages keep the update tag; unchanged pages keep their original tag.",
                 font=("Segoe UI", 9), bg=BG, fg=MUTED).grid(
                 row=1, column=0, columnspan=3, padx=PAD*2, pady=(0, PAD), sticky="w")

        # Flow diagram
        flow = tk.Frame(self, bg=BG)
        flow.grid(row=2, column=0, columnspan=3, padx=PAD*2, pady=(0, PAD))
        for col, (text, color) in enumerate([
            ("Base PDF", GREEN), (" + ", MUTED), ("Update PDF", ORANGE),
            (" → ", MUTED), ("Merged PDF", ACCENT)
        ]):
            bg = CARD if text not in (" + ", " → ") else BG
            tk.Label(flow, text=text, font=FONT_B, bg=bg,
                     fg=color, padx=10, pady=6).grid(row=0, column=col)

        # File rows
        def file_row(row, label, color, attr, cmd):
            tk.Label(self, text=label, font=FONT_B, bg=BG, fg=color).grid(
                row=row, column=0, padx=(PAD*2, 8), pady=4, sticky="w")
            var = tk.StringVar(value="No file selected")
            setattr(self, attr, var)
            tk.Label(self, textvariable=var, font=FONT, bg=CARD, fg=MUTED,
                     width=36, anchor="w", padx=8, pady=6, relief="flat").grid(
                     row=row, column=1, padx=4, pady=4)
            tk.Button(self, text="Browse…", font=FONT, bg=ACCENT, fg="white",
                      relief="flat", padx=10, cursor="hand2",
                      command=cmd).grid(row=row, column=2, padx=(4, PAD*2), pady=4)

        file_row(3, "Base PDF",   GREEN,  "base_var",   self._pick_base)
        file_row(4, "Update PDF", ORANGE, "update_var", self._pick_update)

        # Output folder
        tk.Label(self, text="Output Folder", font=FONT_B, bg=BG, fg=FG).grid(
            row=5, column=0, padx=(PAD*2, 8), pady=4, sticky="w")
        self.dir_var = tk.StringVar(value="No folder selected")
        tk.Label(self, textvariable=self.dir_var, font=FONT, bg=CARD, fg=MUTED,
                 width=36, anchor="w", padx=8, pady=6, relief="flat").grid(
                 row=5, column=1, padx=4, pady=4)
        tk.Button(self, text="Browse…", font=FONT, bg=ACCENT, fg="white",
                  relief="flat", padx=10, cursor="hand2",
                  command=self._pick_dir).grid(row=5, column=2, padx=(4, PAD*2), pady=4)

        # Output filename
        tk.Label(self, text="Output Filename", font=FONT_B, bg=BG, fg=FG).grid(
            row=6, column=0, padx=(PAD*2, 8), pady=4, sticky="w")
        self.name_var = tk.StringVar(value="merged_addendum.pdf")
        tk.Entry(self, textvariable=self.name_var, font=FONT,
                 bg=CARD, fg=FG, insertbackground=FG,
                 width=36, relief="flat").grid(row=6, column=1, padx=4, pady=4, ipady=6)

        # Separator
        tk.Frame(self, bg="#3a3a5a", height=1).grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=PAD*2, pady=(PAD, 8))

        # Detected tags (read-only info display)
        tk.Label(self, text="Detected Tags", font=("Segoe UI", 11, "bold"),
                 bg=BG, fg=FG).grid(row=8, column=0, columnspan=3,
                                    padx=PAD*2, sticky="w")
        tk.Label(self,
                 text="Auto-detected from each PDF when selected.",
                 font=("Segoe UI", 8), bg=BG, fg=MUTED).grid(
                 row=9, column=0, columnspan=3, padx=PAD*2, pady=(0, 6), sticky="w")

        def tag_display_row(row, label, color, attr):
            tk.Label(self, text=label, font=FONT_B, bg=BG, fg=color).grid(
                row=row, column=0, padx=(PAD*2, 8), pady=4, sticky="w")
            var = tk.StringVar(value="—")
            setattr(self, attr, var)
            tk.Label(self, textvariable=var, font=FONT, bg=CARD, fg=color,
                     width=16, anchor="w", padx=8, pady=6, relief="flat").grid(
                     row=row, column=1, padx=4, pady=4, sticky="w")

        tag_display_row(10, "Base tag",   GREEN,  "base_tag_var")
        tag_display_row(11, "Update tag", ORANGE, "update_tag_var")

        tk.Label(self,
                 text="ℹ  Unchanged pages keep the base tag. Replaced/new pages keep the update tag.",
                 font=("Segoe UI", 8), bg=BG, fg=YELLOW, justify="left").grid(
                 row=12, column=0, columnspan=3, padx=PAD*2, pady=(0, PAD), sticky="w")

        # Progress
        self.progress = ttk.Progressbar(self, length=510, mode="determinate")
        self.progress.grid(row=13, column=0, columnspan=3, padx=PAD*2, pady=(4, 2))

        self.status_var = tk.StringVar(value="Ready — select both PDFs and an output folder.")
        tk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9),
                 bg=BG, fg=MUTED, wraplength=500, justify="left").grid(
                 row=14, column=0, columnspan=3, padx=PAD*2, pady=(0, 4), sticky="w")

        self.btn = tk.Button(self, text="✦  Merge Addendums", font=FONT_B,
                             bg=ACCENT, fg="white", relief="flat",
                             padx=24, pady=10, cursor="hand2",
                             command=self._run)
        self.btn.grid(row=15, column=0, columnspan=3, pady=(8, PAD*1.5))

    # ── Reset ────────────────────────────────────────────────────────────

    def _reset(self):
        """Clear all selections so the tool is ready for the next merge."""
        self._base_path   = None
        self._update_path = None
        # Leave _out_dir intact — user likely wants the same output folder
        self.base_var.set("No file selected")
        self.update_var.set("No file selected")
        self.base_tag_var.set("—")
        self.update_tag_var.set("—")
        self.name_var.set("merged_addendum.pdf")
        self.progress["value"] = 0
        self.status_var.set("Ready — select both PDFs and an output folder.")

    # ── Pickers ──────────────────────────────────────────────────────────

    def _pick_base(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self._base_path = path
            self.base_var.set(os.path.basename(path))
            try:
                tag = detect_tag(get_page_labels(PdfReader(path)))
                self.base_tag_var.set(tag or "—")
            except Exception:
                pass

    def _pick_update(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self._update_path = path
            self.update_var.set(os.path.basename(path))
            try:
                tag = detect_tag(get_page_labels(PdfReader(path)))
                self.update_tag_var.set(tag or "—")
            except Exception:
                pass

    def _pick_dir(self):
        path = filedialog.askdirectory()
        if path:
            self._out_dir = path
            self.dir_var.set(path)

    # ── Run ──────────────────────────────────────────────────────────────

    def _run(self):
        if not self._base_path:
            messagebox.showwarning("Missing Input", "Please select the Base PDF.")
            return
        if not self._update_path:
            messagebox.showwarning("Missing Input", "Please select the Update PDF.")
            return
        if not self._out_dir:
            messagebox.showwarning("Missing Output", "Please select an output folder.")
            return

        filename = self.name_var.get().strip() or "merged_addendum.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        output_path = os.path.join(self._out_dir, filename)

        # Capture paths now — _reset() will clear them after OK is clicked
        base_path   = self._base_path
        update_path = self._update_path

        self.btn.config(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("Starting…")

        def worker():
            def on_progress(current, total, label):
                self.progress["value"] = int(current / total * 100)
                self.status_var.set(label)

            try:
                result = merge_addendums(
                    base_path, update_path, output_path, on_progress
                )
                self.progress["value"] = 100
                self.status_var.set(
                    f"Done — {result['total']} pages in merged PDF "
                    f"({len(result['replaced'])} replaced, "
                    f"{len(result['appended'])} new, "
                    f"{result['unchanged']} unchanged)."
                )
                self.after(0, lambda: ResultDialog(
                    self, result, base_path, update_path, output_path
                ))
            except Exception as e:
                messagebox.showerror("Error", str(e))
                self.status_var.set("An error occurred — see error message.")
            finally:
                self.btn.config(state="normal")

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = App()
    app.mainloop()
