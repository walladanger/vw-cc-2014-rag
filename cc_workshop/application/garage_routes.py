"""Garage CRUD and request-scoped vehicle identity."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from cc_workshop.garage import GarageError, GarageNotFound, GarageRegistry, GarageRepository, thaw_payload
from cc_workshop.contracts import normalize_vin
from cc_workshop.vehicle_profiles import VehicleProfileStore

garage_api = Blueprint("garage_api", __name__)


def configure(app, data_root: Path) -> None:
    app.extensions["garage_registry"] = GarageRegistry(Path(data_root))
    if garage_api.name not in app.blueprints:
        app.register_blueprint(garage_api)


def _registry() -> GarageRegistry:
    return current_app.extensions["garage_registry"]


def request_vehicle_context():
    data = request.get_json(silent=True) if request.is_json else None
    vin = request.headers.get("X-Vehicle-VIN") or request.args.get("vin")
    if not vin and isinstance(data, dict):
        vin = data.get("vin")
    if not vin:
        return None, (jsonify({"error": "needs_identification", "message": "Select a confirmed Garage VIN."}), 409)
    try:
        return _registry().context(vin, request.headers.get("X-Request-ID") or uuid.uuid4().hex), None
    except (ValueError, GarageNotFound):
        return None, (jsonify({"error": "needs_identification", "message": "The VIN is not a confirmed Garage."}), 409)


def _record_json(record):
    return {
        "id": record.id, "kind": record.kind, "payload": thaw_payload(record.payload),
        "schema_version": record.schema_version,
        "profile_revision": record.profile_revision, "library_revision": record.library_revision,
    }


def _path_context(vin):
    data = request.get_json(silent=True) if request.is_json else None
    active_vin = request.headers.get("X-Vehicle-VIN") or request.args.get("vin")
    if not active_vin and isinstance(data, dict):
        active_vin = data.get("vin")
    try:
        normalized_path = normalize_vin(vin)
        if active_vin and normalize_vin(active_vin) != normalized_path:
            raise GarageNotFound("active Garage does not match route Garage")
        return _registry().context(normalized_path, request.headers.get("X-Request-ID") or uuid.uuid4().hex), None
    except (ValueError, GarageNotFound):
        return None, (jsonify({"error": "record_not_found"}), 404)


@garage_api.post("/api/garages")
def create_garage():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_garage", "message": "Request body must be a JSON object."}), 400
    try:
        garage = _registry().create(data.get("vin", ""), display_name=data.get("display_name", ""), request_id=uuid.uuid4().hex)
    except (ValueError, GarageError) as exc:
        return jsonify({"error": "invalid_garage", "message": str(exc)}), 400
    return jsonify({"vin": garage.vin, "display_name": garage.display_name}), 201


@garage_api.get("/api/garages")
def list_garages():
    return jsonify({"garages": [{"vin": item.vin, "display_name": item.display_name} for item in _registry().list()]})


@garage_api.post("/api/garages/<vin>/records")
def create_record(vin):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_record", "message": "Request body must be a JSON object."}), 400
    context, context_error = _path_context(vin)
    if context_error:
        return context_error
    try:
        scoped = GarageRepository(_registry()).open(context)
        record = scoped.put_record(data.get("kind", ""), data.get("payload", {}), record_id=data.get("id"))
    except (ValueError, GarageNotFound) as exc:
        return jsonify({"error": "invalid_record", "message": str(exc)}), 400
    return jsonify(_record_json(record)), 201


@garage_api.get("/api/garages/<vin>/records/<record_id>")
def get_record(vin, record_id):
    context, context_error = _path_context(vin)
    if context_error:
        return context_error
    try:
        scoped = GarageRepository(_registry()).open(context)
        return jsonify(_record_json(scoped.get_record(record_id)))
    except (ValueError, GarageNotFound):
        return jsonify({"error": "record_not_found"}), 404


def _profile_json(profile):
    return {
        "vin": profile.vin,
        "revision": profile.revision,
        "fields": {
            name: {
                "value": field.value,
                "evidence": dict(field.evidence),
                "confirmed_at": field.confirmed_at,
            }
            for name, field in profile.fields.items()
        },
    }


@garage_api.get("/api/garages/<vin>/profile")
def get_vehicle_profile(vin):
    context, context_error = _path_context(vin)
    if context_error:
        return context_error
    return jsonify(_profile_json(VehicleProfileStore(_registry(), context).profile()))


@garage_api.put("/api/garages/<vin>/profile/<field_name>")
def confirm_vehicle_profile_field(vin, field_name):
    context, context_error = _path_context(vin)
    if context_error:
        return context_error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_profile", "message": "Request body must be a JSON object."}), 400
    try:
        store = VehicleProfileStore(_registry(), context)
        store.confirm(field_name, data.get("value"), data.get("evidence"))
        return jsonify(_profile_json(store.profile()))
    except (TypeError, ValueError, GarageError) as exc:
        return jsonify({"error": "invalid_profile", "message": str(exc)}), 400


@garage_api.post("/api/garages/<vin>/identification-drafts")
def create_identification_draft(vin):
    context, context_error = _path_context(vin)
    if context_error:
        return context_error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_draft", "message": "Request body must be a JSON object."}), 400
    try:
        VehicleProfileStore(_registry(), context).add_identification_draft(
            data.get("id", ""), data.get("description", ""), data.get("evidence")
        )
    except (TypeError, ValueError, GarageError) as exc:
        return jsonify({"error": "invalid_draft", "message": str(exc)}), 400
    return jsonify({"status": "draft_saved"}), 201


@garage_api.post("/api/garages/<vin>/applicability")
def evaluate_source_applicability(vin):
    context, context_error = _path_context(vin)
    if context_error:
        return context_error
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("requirements"), dict):
        return jsonify({"error": "invalid_applicability", "message": "requirements must be a JSON object."}), 400
    result = VehicleProfileStore(_registry(), context).evaluate(data["requirements"])
    return jsonify({
        "state": result.state.value,
        "reasons": list(result.reasons),
        "profile_revision": result.evaluated_profile_revision,
        "source_revision": result.evaluated_source_revision,
    })
