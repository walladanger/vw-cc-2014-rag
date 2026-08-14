# VW CC 2014 -- Ingest batch for the flat "UnProcessed VW CC Manuals" folder
#
# Companion to ingest_all.ps1. Same manual_ids -- do NOT rename them, they are
# the citation keys already recorded in library_index.json and in any existing
# out/ index. Two things differ from ingest_all.ps1:
#
#   1. Source layout. ingest_all.ps1 expects the categorised tree
#      "No Watermark VW CC Stripped\{Body,Electrical,Engine,...}" with every
#      filename carrying a "_reversed_trimmed_reversed" suffix. This script
#      targets the FLAT folder of untouched originals, whose names have no
#      such suffix -- so running ingest_all.ps1 against it reports
#      "MISSING -- skipping" for all 41 jobs.
#
#   2. File resolution. Files are matched by their VW document-code prefix
#      (e.g. D3E8046F9CB*) rather than by literal filename. Several originals
#      contain en-dashes and doubled spaces that break exact matching, and
#      prefix matching also works if the files are later renamed or
#      re-suffixed.
#
# Usage:
#   .\ingest_unprocessed.ps1 -CheckOnly     # resolve every file, ingest nothing
#   .\ingest_unprocessed.ps1                # run the ingest
#
# Always run -CheckOnly first. Resolving 40+ PDFs costs a second; discovering a
# bad path 30 minutes into a render pass does not.

[CmdletBinding()]
param(
    [string] $Source   = "$env:USERPROFILE\OneDrive\Documents\Projects\vw-cc-2014-rag\UnProcessed VW CC Manuals",
    [string] $Out      = ".\out",
    [string] $Python   = "",
    [switch] $CheckOnly,
    [switch] $Render      # omit --no-render, i.e. render diagram-page PNGs
)

$ErrorActionPreference = "Stop"

# PowerShell 7.4+ defaults $PSNativeCommandUseErrorActionPreference to $true,
# which turns a non-zero exit from python into a terminating error. That would
# abort the whole batch on the first unreadable PDF instead of recording it and
# continuing, so opt out and let the $LASTEXITCODE checks below do the work.
if (Test-Path Variable:\PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

Set-Location $PSScriptRoot

$SCRIPT = "ingest_manual.py"
$V      = "2014 VW CC 2.0T TSI"
$ENG    = "CBFA"
$YEAR   = "2014"

# Resolve the interpreter rather than hardcoding C:\Python314\python.exe the
# way ingest_all.ps1 does -- that path is machine-specific and silently wrong
# on a reinstall. Prefer the project venv, then -Python, then PATH.
if (-not $Python) {
    if (Test-Path ".\.venv\Scripts\python.exe") { $Python = ".\.venv\Scripts\python.exe" }
    else                                        { $Python = "python" }
}

# ---------------------------------------------------------------------------
# Jobs, in ingest priority order. `code` is the VW document-code prefix.
# ---------------------------------------------------------------------------
$jobs = @(

    # -- TIER 1: the known gap ------------------------------------------------
    # The 2014 CC is DSG. vw_09m_auto_trans covers the Aisin 09M automatic --
    # a different gearbox. This is the manual that actually applies to the car.
    @{ code="D3E8046F9CB"; id="vw_dq250_02e_dsg";        title="VW 6-Speed Dual Clutch Transmission 02E DSG DQ250 Repair Manual"; system="DSG/DQ250" }

    # -- TIER 2: specifications and capacities --------------------------------
    @{ code="D4D80B3CD60"; id="vw_cc_fluid_capacity";    title="2014 VW Fluid Capacity Tables";                        system="Maintenance" }
    @{ code="D4B803E2F69"; id="vw_cc_2014_qsb";          title="2014 VW CC Engine-Transmission Quick Reference Spec Book"; system="Specifications" }
    @{ code="D3E8045E548"; id="vw_cc_wheel_tire";        title="VW CC Wheel and Tire Guide";                           system="Wheels/Tires" }
    @{ code="D3E8045E545"; id="vw_cc_wheel_tire_general";title="VW CC Wheel and Tire Guide General Information";        system="Wheels/Tires" }
    # Not present in ingest_all.ps1 at all -- genuine vehicle content, was missed.
    @{ code="D3E804595BC"; id="vw_cc_towing_guide";      title="VW Towing Guide through MY 2016";                      system="Towing" }

    # -- TIER 3: core repair manuals ------------------------------------------
    @{ code="D3E801297EE"; id="vw_cc_suspension";        title="VW CC Suspension Wheels and Steering Manual";          system="Suspension" }
    @{ code="D3E8046FA55"; id="vw_cc_rear_final_drive";  title="VW CC Rear Final Drive Manual";                        system="Drivetrain" }
    @{ code="D3E80473FAF"; id="vw_manual_trans_02q";     title="VW 6-Speed Manual Transmission 02Q 0BB 0FB Repair Manual"; system="Transmission" }
    @{ code="D3E80475DEC"; id="vw_cc_fuel_supply";       title="VW Fuel Supply Gasoline Engines Manual";               system="Engine" }
    @{ code="D3E8001F4DC"; id="vw_cc_hvac";              title="VW CC Heating Ventilation and Air Conditioning Manual"; system="HVAC" }
    @{ code="D3E8012ED6C"; id="vw_cc_r134a_general";     title="VW CC Refrigerant R134a General Information";          system="HVAC" }
    @{ code="D3E801297ED"; id="vw_cc_communication";     title="VW CC Communication Systems Manual";                   system="Electrical" }
    @{ code="D3E800230E1"; id="vw_cc_elec_general_info"; title="VW CC Electrical Equipment General Information";       system="Electrical" }
    @{ code="K0059040021"; id="vw_cc_wiring_diagrams";   title="VW CC Wiring Diagrams and Component Locations";        system="Electrical" }
    @{ code="D3E80493E9D"; id="vw_cc_body_interior";     title="VW CC Body Interior Manual";                           system="Body" }
    @{ code="D3E8012ED5B"; id="vw_cc_body_exterior";     title="VW CC Body Exterior Manual";                           system="Body" }
    @{ code="D3E8012ED37"; id="vw_cc_body_repairs";      title="VW CC Body Repairs Manual";                            system="Body" }
    @{ code="D4B80859D9B"; id="vw_cc_body_collision";    title="VW CC Body Collision Repair Manual";                   system="Body" }
    @{ code="D4B80298F53"; id="vw_cc_paint_general";     title="VW CC Paint General Information";                      system="Body" }
    @{ code="D3E8047211F"; id="vw_immobilizer_ssp";      title="VW Immobilizer Self Study Program";                    system="Electrical" }

    # -- TIER 4: maintenance --------------------------------------------------
    # Four separate documents all titled some variant of "Maintenance".
    # A/B/C suffixes match ingest_all.ps1; they are distinct doc codes, not dupes.
    @{ code="D3E8024FFEB"; id="vw_cc_maint_proc_a";      title="VW CC Maintenance Procedures A";                       system="Maintenance" }
    @{ code="D3E803B616F"; id="vw_cc_maint_proc_b";      title="VW CC Maintenance Procedures B";                       system="Maintenance" }
    @{ code="D4B804120A7"; id="vw_cc_maint_proc_c";      title="VW CC Maintenance Procedures C";                       system="Maintenance" }
    @{ code="D3E8024D0E6"; id="vw_service_2000_2017";    title="2000-2017 Volkswagen Service Manual";                  system="Maintenance" }

    # -- TIER 5: diagnostics / tooling ----------------------------------------
    # Reference material, not a torque-spec source. Still worth indexing for
    # procedure and fault-code lookups.
    @{ code="D3E804F2326"; id="vw_generic_scan_tool";    title="VW Generic Scan Tool Guide";                           system="Diagnostics" }
    @{ code="D4B807F0CD1"; id="vw_odis_offboard_ref";    title="VW ODIS Offboard Diagnostics Reference Guide";         system="Diagnostics" }
    @{ code="D4B802CE040"; id="vw_odis_study_guide";     title="VW ODIS Study Guide";                                  system="Diagnostics" }
    @{ code="D4B802CE041"; id="vw_odis_workbook_a";      title="VW ODIS Workbook A";                                   system="Diagnostics" }
    @{ code="D4B802CE072"; id="vw_odis_workbook_b";      title="VW ODIS Workbook B";                                   system="Diagnostics" }
    @{ code="D4B80934A20"; id="vw_cc_fuel_test_vas";     title="VW Fuel System Testing with VAS523005";                system="Engine" }
    @{ code="D4B805DD592"; id="vw_cc_noise_diagnosis";   title="VW CC Noise Detection and Diagnosis Guide";            system="Diagnostics" }
    @{ code="D4B805DD593"; id="vw_cc_water_leaks";       title="VW CC Guide for Locating Water Leaks";                 system="Body" }
    @{ code="E0000000005"; id="vw_obd2_drive_cycle";     title="VW OBD-II Drive Cycle Procedure";                      system="Diagnostics" }

    # Multi-engine, multi-year reference. Overriding vehicle/engine/year here
    # matters: tagging a 1998-2012 all-model code list as a 2014 CBFA document
    # would let CC-specific queries pull generic entries as if vehicle-matched.
    @{ code="D3E8045F6AB"; id="vw_dtc_1998_2012";        title="VW 1998-2012 DTC List (multi-engine)";                 system="Diagnostics"; vehicle="VW (multi-model)"; engine="multi"; year="1998-2012" }
    @{ code="E0000000012"; id="vw_engine_trans_faults";  title="Volkswagen Engine and Transmission Fault Codes";       system="Diagnostics"; vehicle="VW (multi-model)"; engine="multi"; year="multi" }
)

# ---------------------------------------------------------------------------
# HELD BACK -- do not add without doing the work described below.
# ---------------------------------------------------------------------------
#
#   D4B803E2F67  2014_CC_DTC_QSB.pdf   -> vw_cc_2014_dtc_qsb
#
# ingest_all.ps1 line ~59 ingests this with the default engine tag (CBFA) and
# no per-chunk engine qualifier. That is the cross-contamination bug called out
# in CLAUDE_CODE_HANDOVER.md: within this document the SAME fault code carries
# DIFFERENT threshold values for CBFA vs CCTA vs CNNA. Flattening them to one
# engine tag means a query can retrieve a threshold belonging to an engine the
# car does not have, and specverify cannot catch it -- it verifies numbers
# against the cited chunk, so a chunk that is internally consistent but tagged
# with the wrong engine passes.
#
# Before enabling: tag each chunk with its governing ENGINE_CODE during ingest
# and filter on it at retrieval. Then add:
#   @{ code="D4B803E2F67"; id="vw_cc_2014_dtc_qsb"; title="2014 VW CC DTC Quick Reference Specification Book"; system="Diagnostics" }
#
# ---------------------------------------------------------------------------
# NOT INGESTED -- no vehicle content. Listed so nobody re-adds them later.
# ---------------------------------------------------------------------------
#   D3E80482474  VAS 6150 laptop recovery      -- diagnostic-tool PC recovery
#   D4B807F0CD2  VAS 6150E laptop recovery     -- ditto
#   D4B80802A21  VAS 6160E tablet recovery     -- ditto
#   D4B80405EF4  ODIS Service Introduction     -- boilerplate (0 pages stripped)
#   D4B80676C49  ODIS Error codes              -- boilerplate (0 pages stripped)
#   D4D80B61146  High Voltage MEB PPE          -- MEB is the EV platform, not CC
#   D4B80526693  VW Training Materials         -- course catalogue
#   E0000000007  Immobilizer Service Program   -- policy/admin, not procedure
#   VW_Erwin_Build_Guide                       -- ERWIN portal how-to
#   EN_VW_CR4688                               -- identified 2026-08-14: "erWin:
#                                                 Free access to the Digital
#                                                 Service Schedule". Portal
#                                                 walkthrough (login, VIN lookup,
#                                                 print service certificates) for
#                                                 the VW/Audi/Skoda/SEAT erWin
#                                                 stores. No vehicle content.
#                                                 See note below re: the planned
#                                                 maintenance page.
#
# Already indexed per library_index.json (source_hash dedup should skip them,
# but they are excluded here so a re-run does not depend on that):
#   D3E8012ED5C Brake_System            -> vw_cc_brakes_2011
#   D3E8013DB90 Electrical_Equipment    -> vw_cc_electrical_2018
#   D3E80480D47 4-Cyl Direct Injection  -> vw_ea888_18_20_repair
#   D3E804894E8 6-Speed Auto 09M        -> vw_09m_auto_trans      (wrong gearbox)
#   D4B803E2F68 2014 CC Body QSB        -> vw_cc_2014_body_qsb
#   D4B8067BE5F Refrigerant R1234yf     -> vw_ac_r1234yf_servicing
#   D3E800050F0 Maintenance             -> vw_passat_cc_maint_2023
# ---------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Source folder not found: $Source`nPass -Source '<path>' with the folder holding the original PDFs."
}

Write-Host ""
Write-Host "Source : $Source"
Write-Host "Out    : $Out"
Write-Host "Python : $Python"
Write-Host "Jobs   : $($jobs.Count)"
Write-Host ""

# -- resolve every document code to exactly one file before ingesting anything
$resolved = @()
$problems = @()

foreach ($j in $jobs) {
    $hits = @(Get-ChildItem -LiteralPath $Source -Filter "$($j.code)*.pdf" -File -ErrorAction SilentlyContinue)

    if ($hits.Count -eq 0) {
        $problems += "MISSING   $($j.code)  $($j.id)"
    }
    elseif ($hits.Count -gt 1) {
        # Ambiguity is a real risk here: a folder holding both "X.pdf" and
        # "X_clean.pdf" would match twice, and silently picking one could index
        # a de-watermarked derivative under a canonical manual_id.
        $problems += "AMBIGUOUS $($j.code)  $($j.id)  -> $($hits.Count) matches: $($hits.Name -join ' | ')"
    }
    else {
        $resolved += @{ job = $j; path = $hits[0].FullName; name = $hits[0].Name }
    }
}

if ($problems.Count -gt 0) {
    Write-Host "Resolution problems:" -ForegroundColor Yellow
    $problems | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    Write-Host ""
}

Write-Host "Resolved $($resolved.Count)/$($jobs.Count) documents." -ForegroundColor Cyan

if ($CheckOnly) {
    Write-Host ""
    $resolved | ForEach-Object {
        Write-Host ("  {0,-28} {1}" -f $_.job.id, $_.name) -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "-CheckOnly: nothing ingested." -ForegroundColor Cyan
    exit 0
}

if ($problems.Count -gt 0) {
    $answer = Read-Host "Continue and ingest the $($resolved.Count) resolved documents anyway? (y/N)"
    if ($answer -ne "y") { Write-Host "Aborted."; exit 1 }
}

New-Item -ItemType Directory -Force $Out | Out-Null

$i      = 0
$failed = @()
$total  = $resolved.Count

foreach ($r in $resolved) {
    $i++
    $j = $r.job
    Write-Host ""
    Write-Host "[$i/$total] $($j.id)" -ForegroundColor Cyan
    Write-Host "  $($r.name)" -ForegroundColor DarkGray

    $veh = if ($j.vehicle) { $j.vehicle } else { $V }
    $eng = if ($j.engine)  { $j.engine }  else { $ENG }
    $yr  = if ($j.year)    { $j.year }    else { $YEAR }

    $renderArgs = if ($Render) { @() } else { @("--no-render") }

    & $Python $SCRIPT ingest $r.path `
        --manual-id $j.id `
        --title $j.title `
        --vehicle $veh `
        --engine $eng `
        --year $yr `
        --system $j.system `
        --out $Out `
        @renderArgs

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
        $failed += $j.id
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "Done: $($total - $failed.Count)/$total ingested" -ForegroundColor Green
if ($failed.Count -gt 0) {
    Write-Host "Failed: $($failed -join ', ')" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "REQUIRED NEXT STEP -- torque extraction is regex-tuned to the" -ForegroundColor Yellow
Write-Host "previously indexed manuals and has not been validated against these:" -ForegroundColor Yellow
Write-Host "    python specverify.py audit" -ForegroundColor Cyan
Write-Host "Then re-check retrieval quality:" -ForegroundColor Yellow
Write-Host "    python retrieve.py --selftest" -ForegroundColor Cyan
