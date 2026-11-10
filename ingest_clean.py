#!/usr/bin/env python3
"""
Batch-ingest the clean (no-watermark) manual edition.

Usage:
    python ingest_clean.py <folder-of-clean-pdfs> [--out ./out] [--no-render] [--only <id>]

Files are matched by their VW document number (the part before the first "-"),
so renamed copies still map to the same manual_id. Already-ingested files are
skipped by ingest_manual.py via library_index.json (dedup by source_hash).
"""
import argparse
import os
import subprocess
import sys

V, ENG, YEAR = "2014 VW CC 2.0T TSI", "CBFA", "2014"

# doc number -> (manual_id, title, system[, vehicle, engine, year])
JOBS = {
    # Body
    "D3E8012ED37": ("vw_cc_body_repairs", "VW CC Body Repairs Manual", "Body"),
    "D3E8012ED5B": ("vw_cc_body_exterior", "VW CC Body Exterior Manual", "Body"),
    "D3E80493E9D": ("vw_cc_body_interior", "VW CC Body Interior Manual", "Body"),
    "D4B80298F53": ("vw_cc_paint_general", "VW CC Paint General Information", "Body"),
    "D4B803E2F68": ("vw_cc_2014_body_qsb", "2014 VW CC Body Quick Reference Specification Book", "Body"),
    "D4B80859D9B": ("vw_cc_body_collision", "VW CC Body Collision Repair Manual", "Body"),
    "D4B805DD593": ("vw_cc_water_leaks", "VW CC Guide for Locating Water Leaks", "Body"),
    # Electrical
    "D3E800230E1": ("vw_cc_elec_general_info", "VW CC Electrical Equipment General Information", "Electrical"),
    "D3E8013DB90": ("vw_cc_electrical_2018", "VW CC Electrical Equipment Repair Manual", "Electrical"),
    "K0059040021": ("vw_cc_wiring_diagrams", "VW CC Wiring Diagrams and Component Locations", "Electrical"),
    "D3E801297ED": ("vw_cc_communication", "VW CC Communication Systems Manual", "Electrical"),
    "D3E8047211F": ("vw_immobilizer_ssp", "VW Immobilizer Self Study Program", "Electrical"),
    "E0000000007": ("vw_immobilizer_independent", "VW Revised Immobilizer Service Program for Independent Workshops", "Electrical"),
    # HVAC
    "D3E8001F4DC": ("vw_cc_hvac", "VW CC Heating Ventilation and Air Conditioning Manual", "HVAC"),
    "D3E8012ED6C": ("vw_cc_r134a_general", "VW CC Refrigerant R134a General Information", "HVAC"),
    "D4B8067BE5F": ("vw_ac_r1234yf_servicing", "VW A/C Refrigerant R1234yf Servicing Manual", "HVAC"),
    # Chassis
    "D3E801297EE": ("vw_cc_suspension", "VW CC Suspension Wheels and Steering Manual", "Suspension"),
    "D3E8012ED5C": ("vw_cc_brakes_2011", "VW CC Brake System Repair Manual", "Brakes"),
    "D3E8045E545": ("vw_cc_wheel_tire_general", "VW CC Wheel and Tire Guide General Information", "Wheels/Tires"),
    "D3E8045E548": ("vw_cc_wheel_tire", "VW CC Wheel and Tire Guide", "Wheels/Tires"),
    "D3E804595BC": ("vw_towing_guide_2016", "VW Towing Guide through MY 2016", "Maintenance"),
    # Engine
    "D3E80475DEC": ("vw_cc_fuel_supply", "VW Fuel Supply Gasoline Engines Manual", "Engine"),
    "D3E80480D47": ("vw_ea888_18_20_repair", "VW 4-Cyl 1.8L/2.0L TSI (4V Turbo Chain Drive) Engine Repair Manual", "Engine"),
    "D4B80934A20": ("vw_cc_fuel_test_vas", "VW Fuel System Testing with VAS523005", "Engine"),
    "D4B803E2F69": ("vw_cc_2014_qsb", "2014 VW CC Engine-Transmission Quick Reference Spec Book", "Specifications"),
    "D4D80B3CD60": ("vw_cc_fluid_capacity", "2014 VW Fluid Capacity Tables", "Maintenance"),
    "D4B805DD592": ("vw_cc_noise_diagnosis", "VW CC Noise Detection and Diagnosis Guide", "Diagnostics"),
    # Transmission
    "D3E8046F9CB": ("vw_dq250_02e_dsg", "VW 6-Speed Dual Clutch Transmission 02E DSG DQ250 Repair Manual", "DSG/DQ250"),
    "D3E8046FA55": ("vw_cc_rear_final_drive", "VW CC Rear Final Drive Manual", "Drivetrain"),
    "D3E80473FAF": ("vw_manual_trans_02q", "VW 6-Speed Manual Transmission 02Q 0BB 0FB Repair Manual", "Transmission"),
    "D3E804894E8": ("vw_09m_auto_trans", "VW 6-Speed Automatic Transmission 09M Repair Manual", "Transmission"),
    # Maintenance
    "D3E800050F0": ("vw_passat_cc_maint_2023", "VW Passat CC Maintenance Manual", "Maintenance"),
    "D3E8024D0E6": ("vw_service_2000_2017", "2000-2017 Volkswagen Service Manual", "Maintenance"),
    "D3E8024FFEB": ("vw_cc_maint_proc_a", "VW CC Maintenance Procedures A", "Maintenance"),
    "D3E803B616F": ("vw_cc_maint_proc_b", "VW CC Maintenance Procedures B", "Maintenance"),
    "D4B804120A7": ("vw_cc_maint_proc_c", "VW CC Maintenance Procedures C", "Maintenance"),
    "E0000000005": ("vw_obd2_drive_cycle", "VW New OBD II Drive Cycle Procedure", "Diagnostics"),
    # Diagnostics / ODIS (general reading; no DTC lookup feature)
    "D3E804F2326": ("vw_generic_scan_tool", "VW Generic Scan Tool Guide", "Diagnostics"),
    "D4B802CE040": ("vw_odis_study_guide", "VW ODIS Study Guide", "Diagnostics"),
    "D4B802CE041": ("vw_odis_workbook_a", "VW ODIS Workbook A", "Diagnostics"),
    "D4B802CE072": ("vw_odis_workbook_b", "VW ODIS Workbook B", "Diagnostics"),
    "D4B807F0CD1": ("vw_odis_offboard_ref", "VW ODIS Offboard Diagnostics Reference Guide", "Diagnostics"),
    "D4B80405EF4": ("vw_odis_service_intro", "VW ODIS Service Introduction", "Diagnostics"),
    "D4B80676C49": ("vw_odis_error_codes", "VW ODIS Error Codes", "Diagnostics"),
    "D4B80526693": ("vw_training_materials", "Volkswagen Training Materials", "Diagnostics"),
    "EN": ("vw_cr4688", "VW CR4688", "Diagnostics"),
    "VW": ("vw_erwin_build_guide", "VW erWin Build Guide", "Diagnostics"),
    "D3E8045F6AB": ("vw_dtc_1998_2012", "VW 1998-2012 DTC List (multi-engine)", "Diagnostics", "VW", "multi", "1998-2012"),
    "E0000000012": ("vw_engine_trans_fault_codes", "Volkswagen Engine & Transmission Fault Codes", "Diagnostics", "VW", "multi", None),
}

# Deliberately not ingested.
SKIP = {
    "D4B803E2F67": "2014 CC DTC QSB - dropped (per-engine thresholds need ENGINE_CODE tagging)",
    "D3E80482474": "VAS 6150 laptop recovery - no vehicle content",
    "D4B807F0CD2": "VAS 6150E laptop recovery - no vehicle content",
    "D4B80802A21": "VAS 6160E tablet recovery - no vehicle content",
    "D4D80B61146": "High-voltage MEB PPE - EV only, not this car",
}


def doc_number(fname: str) -> str:
    return os.path.basename(fname).split("-")[0].split("_")[0].strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--out", default="./out")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--only", default=None, help="ingest just this manual_id")
    args = ap.parse_args()

    pdfs = sorted(f for f in os.listdir(args.folder) if f.lower().endswith(".pdf"))
    done, failed, unknown = 0, [], []
    for f in pdfs:
        num = doc_number(f)
        if num in SKIP:
            print(f"SKIP  {f}  ({SKIP[num]})")
            continue
        job = JOBS.get(num)
        if not job:
            unknown.append(f)
            continue
        mid, title, system, *rest = job
        if args.only and mid != args.only:
            continue
        veh, eng, yr = (rest + [None] * 3)[:3] if rest else (None, None, None)
        cmd = [sys.executable, "ingest_manual.py", "ingest", os.path.join(args.folder, f),
               "--manual-id", mid, "--title", title, "--system", system,
               "--vehicle", veh or V, "--engine", eng or ENG, "--year", yr or YEAR,
               "--out", args.out]
        if args.no_render:
            cmd.append("--no-render")
        print(f"\n=== {mid}  <-  {f}", flush=True)
        if subprocess.run(cmd).returncode == 0:
            done += 1
        else:
            failed.append(mid)

    print(f"\nDone: {done} ingested, {len(failed)} failed")
    if failed:
        print("Failed:", ", ".join(failed))
    if unknown:
        print("Not mapped (add to JOBS or SKIP):", *unknown, sep="\n  ")


if __name__ == "__main__":
    main()
