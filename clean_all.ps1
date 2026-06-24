# VW CC — Batch dewatermark all original PDFs into a clean reading-copy tree.
# Output: C:\Users\Desktop\OneDrive\Documents\Projects\VW CC Clean\<folder>\
# Source PDFs are never modified.

$SCRIPT = "dewatermark_pdf.py"
$ORIG   = "C:\Users\Desktop\OneDrive\Documents\Official VW Manuuals"
$CLEAN  = "C:\Users\Desktop\OneDrive\Documents\Projects\VW CC Clean"

$folders = @(
    "Body and Structual"
    "Electrical"
    "Engine"
    "Maintenance Procedures. ODIS and OBD"
    "Misc Context and Non Important"
    "Not My Car"
)

foreach ($folder in $folders) {
    $inDir  = "$ORIG\$folder"
    $outDir = "$CLEAN\$folder"
    Write-Host ""
    Write-Host "── $folder ──" -ForegroundColor Cyan
    python $SCRIPT "$inDir" -o "$outDir"
}

Write-Host ""
Write-Host "All done. Clean copies in: $CLEAN" -ForegroundColor Green
