# VW CC — Batch dewatermark all original PDFs into a clean reading-copy tree.
# Output: C:\Users\Desktop\OneDrive\Documents\Projects\VW CC Clean Rebuilt v3\
# Source PDFs are never modified.

$SCRIPT = "dewatermark_pdf.py"
$ORIG   = "C:\Users\Desktop\OneDrive\Documents\Official VW Manuuals"
$CLEAN  = "C:\Users\Desktop\OneDrive\Documents\Projects\VW CC Clean Rebuilt v3"

$folders = @(
    "Body and Structual"
    "Electrical"
    "Engine"
    "Maintenance Procedures. ODIS and OBD"
    "Misc Context and Non Important"
    "Not My Car"
)

python rebuild_clean_manuals.py --source $ORIG --output $CLEAN --force

Write-Host ""
Write-Host "All done. Clean copies in: $CLEAN" -ForegroundColor Green
