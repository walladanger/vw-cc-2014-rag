# CC-T002–CC-T004 interface proposal

Preparation only. This freezes callable boundaries before implementation; it does not change application code.

## Package surface

```python
# cc_workshop/contracts.py
@dataclass(frozen=True, slots=True)
class VehicleContext:
    vin: str
    profile_revision: int
    library_revision: str
    approved_source_ids: tuple[str, ...]
    request_id: str

class ApplicabilityState(StrEnum):
    CONFIRMED_MATCH = "confirmed_match"
    CONFIRMED_MISMATCH = "confirmed_mismatch"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class ApplicabilityResult:
    state: ApplicabilityState
    reasons: tuple[str, ...] = ()
    evaluated_profile_revision: int = 0
    evaluated_source_revision: str = ""

@dataclass(frozen=True, slots=True)
class Unavailable:
    code: str
    message: str
    retryable: bool = False
```

The context constructor validates normalized VIN, positive profile revision, non-empty library revision and request ID, and copies/deduplicates source IDs into an ordered tuple. No mutable mappings or lists enter the object.

## Runtime and safe paths

```python
# cc_workshop/operations/config.py
@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    data_root: Path
    bind_host: str = "127.0.0.1"
    port: int = 5000

def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig: ...

# cc_workshop/operations/paths.py
def default_data_root(env: Mapping[str, str] | None = None) -> Path: ...
def initialize_data_root(root: Path) -> DataPaths: ...
def resolve_within(root: Path, *parts: str, must_exist: bool = False) -> Path: ...

@dataclass(frozen=True, slots=True)
class DataPaths:
    root: Path
    registry_db: Path
    configuration: Path
    models: Path
    shared_sources: Path
    staging: Path
    jobs: Path
    logs: Path
    backups: Path
    garages: Path

# cc_workshop/operations/instance_lock.py
class InstanceLock:
    def __init__(self, data_root: Path): ...
    def acquire(self) -> None: ...
    def release(self) -> None: ...
    def __enter__(self) -> "InstanceLock": ...
    def __exit__(self, *exc_info: object) -> None: ...
```

`default_data_root` uses `CC_WORKSHOP_DATA_ROOT` when set; otherwise `%LOCALAPPDATA%\CC Workshop`. `initialize_data_root` creates the planned writable tree before log files are opened. `resolve_within` rejects absolute child components, `..`, NULs, reserved device names, paths outside the resolved root, and existing reparse-point/symlink escapes. The server and Flask development entry points default to `127.0.0.1`; an explicit environment override is required for any broader bind.

## Garage registry and repository

```python
# cc_workshop/garage/registry.py
class GarageRegistry:
    def __init__(self, data_root: Path): ...
    def create(self, vin: str, *, display_name: str, request_id: str) -> GarageRecord: ...
    def list(self) -> tuple[GarageRecord, ...]: ...
    def get(self, vin: str) -> GarageRecord: ...
    def context(self, vin: str, request_id: str) -> VehicleContext: ...

# cc_workshop/garage/repository.py
class GarageRepository:
    def __init__(self, registry: GarageRegistry): ...
    @classmethod
    def from_data_root(cls, data_root: Path) -> "GarageRepository": ...
    def open(self, context: VehicleContext) -> ScopedGarageRepository: ...

class ScopedGarageRepository:
    @property
    def context(self) -> VehicleContext: ...
    def get_profile(self) -> VehicleProfile: ...
    def update_profile(self, patch: ProfilePatch) -> VehicleProfile: ...
    def associate_source(self, association: SourceAssociation) -> None: ...
    def get_record(self, record_id: str) -> GarageRecordPayload: ...
```

The registry owns `<data_root>/registry.sqlite`. Each confirmed normalized VIN owns `<data_root>/garages/<VIN>/garage.sqlite` plus `originals`, `derivatives`, `vectors`, and `exports`. The registry stores trusted relative paths; callers never supply a storage path to `open`. `GarageRepository.open` re-resolves the registry record, compares every context revision and approved source association, and raises a structured stale-context error before returning a scoped repository. Every private table includes `vin`, and every read/update query constrains it even though the database is already per VIN. Another Garage's ID returns scoped not-found.

VIN normalization removes surrounding whitespace and uppercases ASCII. Activation accepts only a 17-character VIN using letters/digits excluding I, O and Q. It does not enforce a US check digit globally. Identification drafts use a separate registry table and cannot produce `VehicleContext`.

## Profiles, evidence and invalidation

```python
class ConfirmationState(StrEnum):
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class FieldEvidence:
    evidence_id: str
    source_type: str
    source_ref: str
    exact_value: str
    recorded_at: str

@dataclass(frozen=True, slots=True)
class ConfirmedField:
    value: str | int | tuple[str, ...] | None
    state: ConfirmationState
    evidence: tuple[FieldEvidence, ...] = ()

@dataclass(frozen=True, slots=True)
class VehicleProfile:
    vin: str
    revision: int
    display_name: str
    year: ConfirmedField
    engine_code: ConfirmedField
    transmission_code: ConfirmedField
    market: ConfirmedField
    pr_codes: ConfirmedField
    mileage: ConfirmedField
    modifications: tuple[str, ...]
```

Each configuration field stores its own state and evidence. Historical free-text descriptions may create draft values but never `CONFIRMED` fields. Updating a profile increments `profile_revision` transactionally. Source association changes update a deterministic `library_revision`. Procedure approvals and other dependent records store both revisions; a mismatch makes them stale without deleting history.

Applicability evaluation uses only confirmed fields. A confirmed contradiction in engine, transmission, market, year, or required PR code yields `CONFIRMED_MISMATCH`. A source with sufficient confirmed constraints and no contradiction yields `CONFIRMED_MATCH`. Missing source metadata or missing required confirmed profile fields yields `UNKNOWN`. Repair paths admit only `CONFIRMED_MATCH`; supplementary discovery may display `UNKNOWN` with an explicit label.

## Legacy compatibility and dependencies

- Add the missing `vehicle_profile=None` parameter to `ChromaLibrary.retrieve` and apply the same filter contract as the in-memory libraries. Preserve legacy callers while the new `VehicleContext` service boundary is introduced.
- Remove or disable cloud/Gemini embedding selection from the required runtime path. Unsupported backends return `Unavailable` rather than terminating the process.
- Keep `requirements.txt` as the required runtime set without Torch, Transformers, Whisper, yt-dlp or ingestion tools. Add `requirements-ingest.txt`, `requirements-dev.txt`, and `requirements-packaging.txt`; produce resolved lock files from a clean environment after tests pass.
- Desktop logs, databases and caches resolve below the data root. Installation/source directories remain read-only at runtime.

## Acceptance tests to implement first

`tests/acceptance/test_runtime_contracts.py`

- Chroma and in-memory retrieval accept the same profile argument and return results or structured unavailable state.
- Selecting required runtime modes never imports or selects a cloud embedding backend.
- Empty data root initialization creates logs before desktop logging opens.
- Default bind is loopback for development and Waitress launchers; explicit configuration can opt into another host.
- Runtime requirements omit Torch, Transformers, Whisper and yt-dlp; ingestion and packaging extras remain separate.

`tests/acceptance/test_garage_isolation.py`

- Create two VINs, assert separate real SQLite files and vector roots, write conflicting records, restart registry, and read each value only in its original Garage.
- A record ID from Garage A is scoped not-found under Garage B.
- `../`, absolute paths, and symlink/reparse escapes are rejected.
- `VehicleContext` cannot be mutated and concurrent request contexts never alter each other.
- Opening a repository with a stale profile or library revision fails.
- A second `InstanceLock` for the same data root fails while the first owns it and succeeds after release.

`tests/acceptance/test_vehicle_applicability.py`

- Missing metadata is `UNKNOWN`, never a match.
- Confirmed mismatches for engine, transmission, market, year, and PR code are excluded independently.
- Unconfirmed historical prose does not satisfy an applicability constraint.
- Per-field evidence round-trips through SQLite.
- A profile update increments the revision and makes an approval tied to the old revision stale.
- Strict repair filtering admits only `CONFIRMED_MATCH` while retaining an explicit unknown state for review/discovery.

Tests use temporary on-disk roots and reopen connections to prove persistence. They do not replace SQLite or filesystem behavior with mocks.
