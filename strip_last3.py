#!/usr/bin/env python3
"""Strip the last 3 pages (watermark/copyright boilerplate) from every PDF in a folder tree.
Writes stripped copies to a parallel output tree, preserving subfolder structure."""
import os
import sys
import fitz  # PyMuPDF

SRC  = r"C:\Users\Desktop\OneDrive\Documents\Projects\No Watermark VW CC"
DST  = r"C:\Users\Desktop\OneDrive\Documents\Projects\No Watermark VW CC Stripped"
SKIP = 3  # pages to remove from the end

ok = err = skipped = 0
for root, dirs, files in os.walk(SRC):
    # Skip the nested duplicate subfolder
    dirs[:] = [d for d in dirs if d != "No Watermark VW CC"]
    for fn in files:
        if not fn.lower().endswith(".pdf"):
            continue
        src_path = os.path.join(root, fn)
        rel      = os.path.relpath(src_path, SRC)
        dst_path = os.path.join(DST, rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)

        try:
            doc = fitz.open(src_path)
            n   = len(doc)
            if n <= SKIP:
                print(f"  SKIP (only {n} pages): {rel}")
                skipped += 1
                doc.close()
                continue
            # Check the last page is actually the boilerplate before stripping
            last_text = doc[n - 1].get_text().replace("\n", " ")[:80]
            if "Protected by copyright" not in last_text and "copyright" not in last_text.lower():
                print(f"  WARN last page not copyright, stripping anyway: {rel}")
            # Delete last SKIP pages (delete from end to avoid index shift)
            for i in range(n - 1, n - 1 - SKIP, -1):
                doc.delete_page(i)
            doc.save(dst_path, garbage=4, deflate=True)
            doc.close()
            print(f"  OK  {n}p -> {n-SKIP}p  {rel}")
            ok += 1
        except Exception as e:
            print(f"  ERR {rel}: {e}")
            err += 1

print(f"\nDone: {ok} stripped, {skipped} skipped (too short), {err} errors")
print(f"Output: {DST}")
