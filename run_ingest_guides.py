#!/usr/bin/env python3
"""
Batch ingest runner — all 33 AUTO DOC CLUB VW CC (358) repair guides.

Pre-loaded with the correct file paths from AUTO_DOC_CLUB_File_List.csv.
All files live under:
  C:\\Users\\Desktop\\OneDrive\\Documents\\Projects\\VW CC Repair Video Guide AUTO DOC CLUB\\

Usage:
  python run_ingest_guides.py               # ingest all, local embedder
  python run_ingest_guides.py --embedder ollama --out ./out
  python run_ingest_guides.py --skip-embed  # fast run, embed later
  python run_ingest_guides.py --dry-run     # show what would be ingested
  python run_ingest_guides.py --force       # re-ingest even if already indexed

  # After ingesting, review any torque values found in the guides:
  python ingest_guide.py conflicts --out ./out
  python ingest_guide.py list-guides --out ./out
"""

import argparse
import os
import sys

# ──────────────────────────────────────────── guide registry

BASE = r"C:\Users\Desktop\OneDrive\Documents\Projects\VW CC Repair Video Guide AUTO DOC CLUB"

GUIDES = [
    # ── Engine ────────────────────────────────────────────────────────────────
    {
        "pdf_path":    os.path.join(BASE, "How to change air filter on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_air_filter_autodoc",
        "title":       "How to change air filter on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Intake",
        "diesel_only": False,
        "notes":       "Applies to both TSI and TDI variants — verify part number for TSI",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change engine oil and filter on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_oil_filter_autodoc",
        "title":       "How to change engine oil and filter on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Lubrication",
        "diesel_only": False,
        "notes":       "Oil spec and capacity differs between TSI and TDI — always cross-check factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change engine thermostat on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_thermostat_autodoc",
        "title":       "How to change engine thermostat on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Cooling",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change ignition coil on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_ignition_coil_autodoc",
        "title":       "How to change ignition coil on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Ignition",
        "diesel_only": False,
        "notes":       "Petrol (TSI) only — CC (358) 2.0T has 4 coils, one per cylinder",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change spark plugs on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_spark_plugs_autodoc",
        "title":       "How to change spark plugs on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Ignition",
        "diesel_only": False,
        "notes":       "Petrol (TSI) only — gap and torque spec MUST be verified against factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change lambda sensor on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_lambda_sensor_autodoc",
        "title":       "How to change lambda sensor on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Emissions",
        "diesel_only": False,
        "notes":       "O2 / lambda sensor; 2.0T TSI has upstream and downstream sensors",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change fuel filter on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_fuel_filter_autodoc",
        "title":       "How to change fuel filter on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Fuel",
        "diesel_only": False,
        "notes":       "Location and procedure differs between TSI (tank-mounted) and TDI (engine bay) — verify for TSI",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change serpentine belt on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_serpentine_belt_autodoc",
        "title":       "How to change serpentine belt on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Engine/Accessories",
        "diesel_only": False,
        "notes":       "Aux/accessory drive belt; verify routing diagram against factory manual",
    },
    {
        # DIESEL ONLY — glow plugs are not fitted to petrol/TSI engines
        "pdf_path":    os.path.join(BASE, "How to change glow plugs on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_glow_plugs_autodoc",
        "title":       "How to change glow plugs on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "VW CC (358) TDI (diesel variants only)",
        "system":      "Engine/Ignition",
        "diesel_only": True,
        "notes":       "DIESEL ONLY — glow plugs are not fitted to 2.0T TSI. Indexed for completeness but excluded from TSI queries.",
    },

    # ── Brakes ────────────────────────────────────────────────────────────────
    {
        "pdf_path":    os.path.join(BASE, "How to change front brake caliper on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_brake_caliper_autodoc",
        "title":       "How to change front brake caliper on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Brakes/Front",
        "diesel_only": False,
        "notes":       "Caliper bolt torque MUST be verified against factory manual (brakes are safety-critical)",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front brake discs on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_brake_discs_autodoc",
        "title":       "How to change front brake discs on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Brakes/Front",
        "diesel_only": False,
        "notes":       "Wheel bolt torque and hub bolt torque MUST come from factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front brake pads on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_brake_pads_autodoc",
        "title":       "How to change front brake pads on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Brakes/Front",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear brake discs on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_brake_discs_autodoc",
        "title":       "How to change rear brake discs on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Brakes/Rear",
        "diesel_only": False,
        "notes":       "Rear discs integrate with handbrake mechanism on CC — verify procedure against factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear brake pads on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_brake_pads_autodoc",
        "title":       "How to change rear brake pads on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Brakes/Rear",
        "diesel_only": False,
        "notes":       "Rear piston must be wound in (not pushed) on CC — confirm in factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front ABS sensor on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_abs_sensor_autodoc",
        "title":       "How to change front ABS sensor on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Brakes/ABS",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear ABS sensor on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_abs_sensor_autodoc",
        "title":       "How to change rear ABS sensor on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Brakes/ABS",
        "diesel_only": False,
        "notes":       "",
    },

    # ── Suspension / Steering ─────────────────────────────────────────────────
    {
        "pdf_path":    os.path.join(BASE, "How to change front suspension strut on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_strut_autodoc",
        "title":       "How to change front suspension strut on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Front",
        "diesel_only": False,
        "notes":       "Strut top nut and hub carrier bolts are likely stretch — verify in factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front strut mount on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_strut_mount_autodoc",
        "title":       "How to change front strut mount on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Front",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front coil springs on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_coil_springs_autodoc",
        "title":       "How to change front coil springs on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Front",
        "diesel_only": False,
        "notes":       "Spring compressor required — safety-critical procedure",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front lower arm on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_lower_arm_autodoc",
        "title":       "How to change front lower arm on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Front",
        "diesel_only": False,
        "notes":       "Lower arm bolt must be torqued with suspension at ride height — verify in factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front anti roll bar links on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_arb_links_autodoc",
        "title":       "How to change front anti roll bar links on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Front",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front wheel bearing on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_front_wheel_bearing_autodoc",
        "title":       "How to change front wheel bearing on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Front",
        "diesel_only": False,
        "notes":       "Hub/driveshaft nut is a stretch bolt (single use) — torque spec from factory manual is mandatory",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear shock absorbers on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_shocks_autodoc",
        "title":       "How to change rear shock absorbers on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Rear",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear strut mount on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_strut_mount_autodoc",
        "title":       "How to change rear strut mount on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Rear",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear suspension lower control arm on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_lower_control_arm_autodoc",
        "title":       "How to change rear suspension lower control arm on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Rear",
        "diesel_only": False,
        "notes":       "Must be torqued at ride height — verify in factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear suspension lower trailing arm on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_trailing_arm_autodoc",
        "title":       "How to change rear suspension lower trailing arm on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Rear",
        "diesel_only": False,
        "notes":       "Must be torqued at ride height — verify in factory manual",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear anti roll bar links on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_arb_links_autodoc",
        "title":       "How to change rear anti roll bar links on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Rear",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change rear wheel bearing on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_rear_wheel_bearing_autodoc",
        "title":       "How to change rear wheel bearing on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Suspension/Rear",
        "diesel_only": False,
        "notes":       "",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change track rod end on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_track_rod_end_autodoc",
        "title":       "How to change track rod end on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Steering",
        "diesel_only": False,
        "notes":       "Wheel alignment required after — note pre-removal position of track rod",
    },

    # ── Drivetrain ────────────────────────────────────────────────────────────
    {
        "pdf_path":    os.path.join(BASE, "How to change CV joint on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_cv_joint_autodoc",
        "title":       "How to change CV joint on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Drivetrain/Driveshaft",
        "diesel_only": False,
        "notes":       "Driveshaft nut is stretch bolt (single use) — torque and angle from factory manual mandatory",
    },

    # ── Electrical / Body ─────────────────────────────────────────────────────
    {
        "pdf_path":    os.path.join(BASE, "How to change headlight bulb on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_headlight_bulb_autodoc",
        "title":       "How to change headlight bulb on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Electrical/Lighting",
        "diesel_only": False,
        "notes":       "Verify bulb type (H7 / D3S / LED depending on trim level) before ordering",
    },
    {
        "pdf_path":    os.path.join(BASE, "How to change front windshield wipers on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_wiper_blades_autodoc",
        "title":       "How to change front windshield wipers on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "Body/Exterior",
        "diesel_only": False,
        "notes":       "",
    },

    # ── HVAC / Cabin ──────────────────────────────────────────────────────────
    {
        "pdf_path":    os.path.join(BASE, "How to change pollen filter on VW CC (358) ? replacement guide.pdf"),
        "guide_id":    "vw_cc_pollen_filter_autodoc",
        "title":       "How to change pollen filter on VW CC (358)",
        "channel":     "AUTO DOC CLUB",
        "vehicle":     "2014 VW CC 2.0T TSI",
        "system":      "HVAC/Cabin",
        "diesel_only": False,
        "notes":       "Also known as cabin air filter / microfilter",
    },
]

# ──────────────────────────────────────────── runner

def main():
    parser = argparse.ArgumentParser(
        description="Ingest all 33 AUTO DOC CLUB VW CC repair guide PDFs."
    )
    parser.add_argument("--out",         default="./out",  help="Output directory")
    parser.add_argument("--embedder",    default="local",  choices=["local", "ollama"])
    parser.add_argument("--ollama-base", default="http://localhost:11434")
    parser.add_argument("--skip-embed",  action="store_true",
                        help="Skip embedding — fast, embed later with --force")
    parser.add_argument("--force",       action="store_true",
                        help="Re-ingest even if already indexed")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Print what would be ingested without doing it")
    parser.add_argument("--system",      default=None,
                        help="Only ingest guides matching this system substring (e.g. 'Brakes')")
    args = parser.parse_args()

    # Add ingest_guide.py to path (assumes same directory as this script)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    from ingest_guide import ingest_guide

    guides_to_run = GUIDES
    if args.system:
        guides_to_run = [g for g in GUIDES if args.system.lower() in g["system"].lower()]
        print(f"Filtered to {len(guides_to_run)} guides matching system '{args.system}'")

    if args.dry_run:
        print(f"\nDRY RUN — {len(guides_to_run)} guides would be ingested:\n")
        print(f"  {'guide_id':<45} {'D':1}  system")
        print("  " + "-"*70)
        for g in guides_to_run:
            d = "D" if g["diesel_only"] else " "
            missing = "" if os.path.isfile(g["pdf_path"]) else "  ⚠ FILE NOT FOUND"
            print(f"  {g['guide_id']:<45} {d}  {g['system']}{missing}")
        diesel = sum(1 for g in guides_to_run if g["diesel_only"])
        missing = sum(1 for g in guides_to_run if not os.path.isfile(g["pdf_path"]))
        print(f"\nTotal: {len(guides_to_run)}  Diesel-only: {diesel}  Missing files: {missing}")
        return

    # Check for missing files before starting
    missing = [g for g in guides_to_run if not os.path.isfile(g["pdf_path"])]
    if missing:
        print(f"\n⚠  {len(missing)} file(s) not found:")
        for g in missing:
            print(f"  {g['pdf_path']}")
        print("\nContinuing with files that exist…\n")

    ok = err = skipped = 0
    for i, g in enumerate(guides_to_run, 1):
        print(f"\n[{i}/{len(guides_to_run)}] {g['guide_id']}")
        if g["diesel_only"]:
            print(f"  ⚠  diesel_only — will be tagged and indexed but excluded from TSI queries")
        if not os.path.isfile(g["pdf_path"]):
            print(f"  ✗ skipped — file not found")
            err += 1
            continue
        success = ingest_guide(
            pdf_path    = g["pdf_path"],
            guide_id    = g["guide_id"],
            title       = g["title"],
            channel     = g["channel"],
            vehicle     = g["vehicle"],
            system      = g["system"],
            diesel_only = g["diesel_only"],
            notes       = g["notes"],
            out_dir     = args.out,
            embedder    = args.embedder,
            ollama_base = args.ollama_base,
            skip_embed  = args.skip_embed,
            force       = args.force,
        )
        if success:
            ok += 1
        else:
            err += 1

    print(f"\n{'='*60}")
    print(f"DONE: {ok} ingested, {err} failed/missing")
    print(f"\nNext steps:")
    print(f"  python ingest_guide.py list-guides --out {args.out}")
    print(f"  python ingest_guide.py conflicts   --out {args.out}")


if __name__ == "__main__":
    main()
