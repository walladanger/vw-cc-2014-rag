"""Vehicle applicability stamping, shared by the ingest entry points.

`retrieve.applies_to_vehicle` admits any chunk with nothing stamped, so that
turning on vehicle scoping could not silently empty an index built before
applicability was enforced. The price of failing open is that an unstamped
manual or guide matches EVERY car -- the cross-vehicle bleed the filter exists
to prevent, arriving through ingest rather than retrieval.

Both halves are required and neither is safe alone: retrieval stays permissive
so an existing index cannot be emptied, and ingest stays strict so that
permissiveness cannot be exploited by new material.

The rule lives here rather than in each ingest script because a safety check
kept in two copies eventually weakens in one of them. `ingest_manual.py` imports
fitz at module scope while `ingest_guide.py` imports it lazily, so neither can
import the other without a side effect -- this module deliberately depends on
nothing but the standard library.
"""

import argparse

BLANK_REASON = (
    'cannot be blank -- name the vehicle this material applies to, e.g. '
    '"2014 VW CC 2.0T TSI", or a generic marque like "VW (multi-model)" for '
    "shared references. Retrieval admits chunks with no vehicle stamped, so a "
    "blank value would make this material match every car."
)

VEHICLE_HELP = (
    'vehicle this material applies to, e.g. "2014 VW CC 2.0T TSI", or a '
    'generic marque like "VW (multi-model)" for shared references. '
    "Required -- retrieval scoping fails open on unstamped chunks."
)


def validate_vehicle(value):
    """Return the stripped vehicle string. Raise ValueError when it is missing,
    empty, or whitespace only -- all three stamp nothing and so fail open."""
    text = (value or "").strip()
    if not text:
        raise ValueError(BLANK_REASON)
    return text


def vehicle_arg(value):
    """argparse `type=` adapter for validate_vehicle, so the explanation reaches
    the user through argparse's own error channel instead of a traceback."""
    try:
        return validate_vehicle(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
