#!/usr/bin/env python3
"""Batch ingest all Auto Doc Club VW CC (358) repair guides as community-tier manuals."""
import os
import re
import subprocess
import sys

SRC = r"C:\Users\Desktop\OneDrive\Documents\Projects\VW CC Repair Video Guide AUTO DOC CLUB"
OUT = r".\out"
PY  = r"C:\Python314\python.exe"

VEHICLE = "2014 VW CC 2.0T TSI"
YEAR    = "2014"
ENGINE  = "CBFA"

# Map keywords in filename -> (manual_id_suffix, system)
SYSTEM_MAP = [
    ("air filter",                   "air_filter",              "Engine"),
    ("cv joint",                     "cv_joint",                "Drivetrain"),
    ("engine oil",                   "engine_oil",              "Engine"),
    ("thermostat",                   "thermostat",              "Engine"),
    ("front abs sensor",             "front_abs_sensor",        "Brakes"),
    ("rear abs sensor",              "rear_abs_sensor",         "Brakes"),
    ("front anti roll bar",          "front_arb_links",         "Suspension"),
    ("rear anti roll bar",           "rear_arb_links",          "Suspension"),
    ("front brake caliper",          "front_brake_caliper",     "Brakes"),
    ("front brake discs",            "front_brake_discs",       "Brakes"),
    ("front brake pads",             "front_brake_pads",        "Brakes"),
    ("rear brake discs",             "rear_brake_discs",        "Brakes"),
    ("rear brake pads",              "rear_brake_pads",         "Brakes"),
    ("front coil springs",           "front_coil_springs",      "Suspension"),
    ("front lower arm",              "front_lower_arm",         "Suspension"),
    ("front strut mount",            "front_strut_mount",       "Suspension"),
    ("front suspension strut",       "front_strut",             "Suspension"),
    ("front wheel bearing",          "front_wheel_bearing",     "Suspension"),
    ("rear shock absorbers",         "rear_shocks",             "Suspension"),
    ("rear strut mount",             "rear_strut_mount",        "Suspension"),
    ("rear suspension lower control arm", "rear_lower_control_arm", "Suspension"),
    ("rear suspension lower trailing arm", "rear_trailing_arm",  "Suspension"),
    ("rear wheel bearing",           "rear_wheel_bearing",      "Suspension"),
    ("windshield wipers",            "wipers",                  "Body"),
    ("fuel filter",                  "fuel_filter",             "Engine"),
    ("glow plugs",                   "glow_plugs",              "Engine"),
    ("headlight bulb",               "headlight_bulb",          "Electrical"),
    ("ignition coil",                "ignition_coil",           "Engine"),
    ("lambda sensor",                "lambda_sensor",           "Engine"),
    ("pollen filter",                "pollen_filter",           "HVAC"),
    ("front lower arm",              "front_lower_arm",         "Suspension"),
    ("serpentine belt",              "serpentine_belt",         "Engine"),
    ("spark plugs",                  "spark_plugs",             "Engine"),
    ("track rod end",                "track_rod_end",           "Suspension"),
]

def classify(filename):
    fn = filename.lower()
    for keyword, id_suffix, system in SYSTEM_MAP:
        if keyword in fn:
            return id_suffix, system
    return None, None

def clean_title(filename):
    """Strip leading 'How to change ' and trailing ' (358) - replacement guide.pdf'"""
    t = filename
    t = re.sub(r'^How to change ', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*\(\d+\)\s*', ' ', t)
    t = re.sub(r'\s*[–—-]+\s*replacement guide\.pdf\s*$', '', t, flags=re.IGNORECASE)
    t = t.strip()
    return f"Auto Doc Club — VW CC {t.title()}"

def main():
    pdfs = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".pdf"))
    print(f"Found {len(pdfs)} PDFs in Auto Doc Club folder\n")

    ok = fail = skip = 0
    for fn in pdfs:
        id_suffix, system = classify(fn)
        if not id_suffix:
            print(f"  SKIP (unclassified): {fn}")
            skip += 1
            continue

        manual_id = f"autodoc_{id_suffix}"
        title     = clean_title(fn)
        pdf_path  = os.path.join(SRC, fn)

        print(f"\n[{manual_id}]  {system}")
        print(f"  {fn}")

        cmd = [
            PY, "ingest_manual.py", "ingest", pdf_path,
            "--manual-id", manual_id,
            "--title",     title,
            "--vehicle",   VEHICLE,
            "--engine",    ENGINE,
            "--year",      YEAR,
            "--system",    system,
            "--out",       OUT,
            "--no-render",
        ]
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode == 0:
            ok += 1
        else:
            print(f"  FAILED (exit {result.returncode})")
            fail += 1

    print(f"\n{'='*50}")
    print(f"Done: {ok} ingested, {fail} failed, {skip} unclassified")

if __name__ == "__main__":
    main()
