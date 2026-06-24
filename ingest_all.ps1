# VW CC 2014 -- Full Manual Ingest Batch (v2)
# Source: No Watermark VW CC Stripped (last 3 copyright pages removed)
# Run from: C:\Users\Desktop\OneDrive\Documents\Projects\vw_rag_phase2b\
# Usage: .\ingest_all.ps1

$ORIG   = "C:\Users\Desktop\OneDrive\Documents\Projects\No Watermark VW CC Stripped"
$OUT    = ".\out"
$SCRIPT = "ingest_manual.py"
$V      = "2014 VW CC 2.0T TSI"
$ENG    = "CBFA"
$YEAR   = "2014"

$jobs = @(

    # -- BODY & STRUCTURAL
    @{ pdf="$ORIG\Body\D3E8012ED37 Body Repairs.pdf";           id="vw_cc_body_repairs";       title="VW CC Body Repairs Manual";                                           system="Body" }
    @{ pdf="$ORIG\Body\D3E8012ED5B Body Exterior.pdf";          id="vw_cc_body_exterior";      title="VW CC Body Exterior Manual";                                          system="Body" }
    @{ pdf="$ORIG\Body\D3E80493E9D-Body_Interior_reversed_trimmed_reversed.pdf"; id="vw_cc_body_interior"; title="VW CC Body Interior Manual"; system="Body" }
    @{ pdf="$ORIG\Body\D4B80298F53 Paint General STILL HAS WATERMARK.pdf"; id="vw_cc_paint_general"; title="VW CC Paint General Information"; system="Body" }
    @{ pdf="$ORIG\Body\D4B803E2F68-2014_CC_Body_QSB_reversed_trimmed_reversed.pdf"; id="vw_cc_2014_body_qsb"; title="2014 VW CC Body Quick Reference Specification Book"; system="Body" }
    @{ pdf="$ORIG\Body\D4B80859D9B Body Repair Body Collision Repair.pdf"; id="vw_cc_body_collision"; title="VW CC Body Collision Repair Manual"; system="Body" }
    # SKIP: D3E8012ED37 Body Interior.pdf -- duplicate of D3E80493E9D
    # SKIP: D4B803E2F68 2014 CC Body QSB.pdf -- duplicate of reversed_trimmed_reversed version

    # -- ELECTRICAL
    @{ pdf="$ORIG\Electrical\D3E800230E1-Electrical_Equipment_General_Information_reversed_trimmed_reversed.pdf"; id="vw_cc_elec_general_info"; title="VW CC Electrical Equipment General Information"; system="Electrical" }
    @{ pdf="$ORIG\Electrical\D3E8013DB90-Electrical_Equipment_reversed_trimmed_reversed.pdf"; id="vw_cc_electrical_2018"; title="VW CC Electrical Equipment Repair Manual"; system="Electrical" }
    @{ pdf="$ORIG\Electrical\K0059040021-Wiring_Diagrams_and_Component_Locations_reversed_trimmed_reversed.pdf"; id="vw_cc_wiring_diagrams"; title="VW CC Wiring Diagrams and Component Locations"; system="Electrical" }

    # -- ENGINE
    @{ pdf="$ORIG\Engine\D3E8001F4DC-Heating__Ventilation_and_Air_Conditioning_reversed_trimmed_reversed.pdf"; id="vw_cc_hvac"; title="VW CC Heating Ventilation and Air Conditioning Manual"; system="HVAC" }
    @{ pdf="$ORIG\Engine\D3E801297ED-Communication_reversed_trimmed_reversed.pdf"; id="vw_cc_communication"; title="VW CC Communication Systems Manual"; system="Electrical" }
    @{ pdf="$ORIG\Engine\D3E801297EE-Suspension__Wheels__Steering_reversed_trimmed_reversed.pdf"; id="vw_cc_suspension"; title="VW CC Suspension Wheels and Steering Manual"; system="Suspension" }
    @{ pdf="$ORIG\Engine\D3E8012ED5C-Brake_System_reversed_trimmed_reversed.pdf"; id="vw_cc_brakes_2011"; title="VW CC Brake System Repair Manual"; system="Brakes" }
    @{ pdf="$ORIG\Engine\D3E8012ED6C-Refrigerant_R134a_General_Information_reversed_trimmed_reversed.pdf"; id="vw_cc_r134a_general"; title="VW CC Refrigerant R134a General Information"; system="HVAC" }
    @{ pdf="$ORIG\Engine\D3E8045E545-Wheel_and_Tire_Guide_General_Information_reversed_trimmed_reversed.pdf"; id="vw_cc_wheel_tire_general"; title="VW CC Wheel and Tire Guide General Information"; system="Wheels/Tires" }
    @{ pdf="$ORIG\Engine\D3E8045E548-Wheel_and_Tire_Guide_reversed_trimmed_reversed.pdf"; id="vw_cc_wheel_tire"; title="VW CC Wheel and Tire Guide"; system="Wheels/Tires" }
    @{ pdf="$ORIG\Engine\D3E8045F6AB-1998-2012_DTC_List_reversed_trimmed_reversed.pdf"; id="vw_dtc_1998_2012"; title="VW 1998-2012 DTC List (multi-engine)"; vehicle="VW"; engine="multi"; year="1998-2012"; system="Diagnostics" }
    @{ pdf="$ORIG\Engine\D3E8047211F-Immobilizer_Self_Study_Program_reversed_trimmed_reversed.pdf"; id="vw_immobilizer_ssp"; title="VW Immobilizer Self Study Program"; system="Electrical" }
    @{ pdf="$ORIG\Engine\D3E80475DEC-Fuel_Supply_-_Gasoline_Engines_reversed_trimmed_reversed.pdf"; id="vw_cc_fuel_supply"; title="VW Fuel Supply Gasoline Engines Manual"; system="Engine" }
    @{ pdf="$ORIG\Engine\D3E80480D47-4-Cylinder_Direct_Injection_(1_8L_and_2_0L_Engine__4V__Turbocharger__Chain_Drive)_reversed_trimmed_reversed.pdf"; id="vw_ea888_18_20_repair"; title="VW 4-Cyl 1.8L/2.0L TSI (4V Turbo Chain Drive) Engine Repair Manual"; system="Engine" }
    @{ pdf="$ORIG\Engine\D3E804894E8-6-Speed_Automatic_Transmission_09M_reversed_trimmed_reversed.pdf"; id="vw_09m_auto_trans"; title="VW 6-Speed Automatic Transmission 09M Repair Manual"; system="Transmission" }
    @{ pdf="$ORIG\Engine\D4B803E2F69-2014_CC_Engine-Transmission_QSB_reversed_trimmed_reversed.pdf"; id="vw_cc_2014_qsb"; title="2014 VW CC Engine-Transmission Quick Reference Spec Book"; system="Specifications" }
    @{ pdf="$ORIG\Engine\D4B805DD592-Noise_Detection_and_Diagnosis_Guide_reversed_trimmed_reversed.pdf"; id="vw_cc_noise_diagnosis"; title="VW CC Noise Detection and Diagnosis Guide"; system="Diagnostics" }
    @{ pdf="$ORIG\Engine\D4B805DD593-Guide_for_Locating_Water_Leaks_reversed_trimmed_reversed.pdf"; id="vw_cc_water_leaks"; title="VW CC Guide for Locating Water Leaks"; system="Body" }
    @{ pdf="$ORIG\Engine\D4B8067BE5F-Refrigerant_R1234yf_Servicing_reversed_trimmed_reversed.pdf"; id="vw_ac_r1234yf_servicing"; title="VW A/C Refrigerant R1234yf Servicing Manual"; system="HVAC" }
    @{ pdf="$ORIG\Engine\D4B80934A20-Fuel_System_Testing_with_VAS523005_reversed_trimmed_reversed.pdf"; id="vw_cc_fuel_test_vas"; title="VW Fuel System Testing with VAS523005"; system="Engine" }
    @{ pdf="$ORIG\Engine\D4D80B3CD60-2014_VW_Fluid_Capacity_Tables_reversed_trimmed_reversed.pdf"; id="vw_cc_fluid_capacity"; title="2014 VW Fluid Capacity Tables"; system="Maintenance" }

    # -- MAINTENANCE / ODIS / OBD
    @{ pdf="$ORIG\Maintenance procedurees\D3E800050F0-Maintenance_reversed_trimmed_reversed.pdf"; id="vw_passat_cc_maint_2023"; title="VW Passat CC Maintenance Manual"; system="Maintenance" }
    @{ pdf="$ORIG\Maintenance procedurees\D3E8024D0E6-2000_-_2017_Volkswagen_Service_reversed_trimmed_reversed.pdf"; id="vw_service_2000_2017"; title="2000-2017 Volkswagen Service Manual"; system="Maintenance" }
    @{ pdf="$ORIG\Maintenance procedurees\D3E8024FFEB-Maintenance_Procedures_reversed_trimmed_reversed.pdf"; id="vw_cc_maint_proc_a"; title="VW CC Maintenance Procedures A"; system="Maintenance" }
    @{ pdf="$ORIG\Maintenance procedurees\D3E803B616F-Maintenance_Procedures_reversed_trimmed_reversed.pdf"; id="vw_cc_maint_proc_b"; title="VW CC Maintenance Procedures B"; system="Maintenance" }
    # SKIP: D3E80482474-VAS_6150_Laptops -- VAS tool recovery, no vehicle content
    @{ pdf="$ORIG\Maintenance procedurees\D3E804F2326-Generic_Scan_Tool_reversed_trimmed_reversed.pdf"; id="vw_generic_scan_tool"; title="VW Generic Scan Tool Guide"; system="Diagnostics" }
    @{ pdf="$ORIG\Maintenance procedurees\D4B802CE040-ODIS_Study_Guide_reversed_trimmed_reversed.pdf"; id="vw_odis_study_guide"; title="VW ODIS Study Guide"; system="Diagnostics" }
    @{ pdf="$ORIG\Maintenance procedurees\D4B802CE041-ODIS_Workbook_reversed_trimmed_reversed.pdf"; id="vw_odis_workbook_a"; title="VW ODIS Workbook A"; system="Diagnostics" }
    @{ pdf="$ORIG\Maintenance procedurees\D4B802CE072-ODIS_Workbook_reversed_trimmed_reversed.pdf"; id="vw_odis_workbook_b"; title="VW ODIS Workbook B"; system="Diagnostics" }
    @{ pdf="$ORIG\Maintenance procedurees\D4B803E2F67-2014_CC_DTC_QSB_reversed_trimmed_reversed.pdf"; id="vw_cc_2014_dtc_qsb"; title="2014 VW CC DTC Quick Reference Specification Book"; system="Diagnostics" }
    # SKIP: D4B80405EF4 -- 0 pages after stripping (was 3-page boilerplate only)
    @{ pdf="$ORIG\Maintenance procedurees\D4B804120A7-Maintenance_Procedures_reversed_trimmed_reversed.pdf"; id="vw_cc_maint_proc_c"; title="VW CC Maintenance Procedures C"; system="Maintenance" }
    # SKIP: D4B80676C49 -- 0 pages after stripping (was 2-page boilerplate only)
    @{ pdf="$ORIG\Maintenance procedurees\D4B807F0CD1-VW_ODIS_Offboard_Diagnostics_Reference_Guide_reversed_trimmed_reversed.pdf"; id="vw_odis_offboard_ref"; title="VW ODIS Offboard Diagnostics Reference Guide"; system="Diagnostics" }
    # SKIP: D4B807F0CD2 -- 0 pages after stripping (was 3-page boilerplate only)
    # SKIP: D4B80802A21 -- 1 page after stripping, VAS tablet recovery

    # -- TRANSMISSION
    @{ pdf="$ORIG\Manual Transmission\D3E8046F9CB-6-Speed_Dual_Clutch_Transmission_02E_reversed_trimmed_reversed.pdf"; id="vw_dq250_02e_dsg"; title="VW 6-Speed Dual Clutch Transmission 02E DSG DQ250 Repair Manual"; system="DSG/DQ250" }
    @{ pdf="$ORIG\Manual Transmission\D3E8046FA55-Rear_Final_Drive_reversed_trimmed_reversed.pdf"; id="vw_cc_rear_final_drive"; title="VW CC Rear Final Drive Manual"; system="Drivetrain" }
    @{ pdf="$ORIG\Manual Transmission\D3E80473FAF-6-Speed_Manual_Transmission_02Q__0BB_and_0FB_reversed_trimmed_reversed.pdf"; id="vw_manual_trans_02q"; title="VW 6-Speed Manual Transmission 02Q 0BB 0FB Repair Manual"; system="Transmission" }
)

$total = $jobs.Count
$i = 0
$failed = @()

New-Item -ItemType Directory -Force $OUT | Out-Null

foreach ($j in $jobs) {
    $i++
    Write-Host ""
    Write-Host "[$i/$total] $($j.id)" -ForegroundColor Cyan
    Write-Host "  $($j.pdf)" -ForegroundColor DarkGray

    if (-not (Test-Path $j.pdf)) {
        Write-Host "  MISSING -- skipping" -ForegroundColor Yellow
        $failed += $j.id
        continue
    }

    $veh = if ($j.vehicle) { $j.vehicle } else { $V }
    $eng = if ($j.engine)  { $j.engine }  else { $ENG }
    $yr  = if ($j.year)    { $j.year }    else { $YEAR }

    & "C:\Python314\python.exe" $SCRIPT ingest $j.pdf `
        --manual-id $j.id `
        --title $j.title `
        --vehicle $veh `
        --engine $eng `
        --year $yr `
        --system $j.system `
        --out $OUT `
        --no-render

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
        $failed += $j.id
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "Done: $($total - $failed.Count)/$total ingested" -ForegroundColor Green
if ($failed.Count -gt 0) {
    Write-Host "Failed/skipped: $($failed -join ', ')" -ForegroundColor Yellow
}
Write-Host "Next: restore diagram renders from diagrams_backup/" -ForegroundColor Cyan
