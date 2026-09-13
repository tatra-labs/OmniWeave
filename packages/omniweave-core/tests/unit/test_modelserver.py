"""Seam S3: the spec, the 0600 sentinel, the ladder's attach halves, and the spawn it may not do.

The load-bearing test is `test_an_unhealthy_sentinel_is_not_mutated_by_the_unlocked_path`. It is
surya's subtlest rule and the easiest to delete: *"when many clients cold-start at once, one holds
the lock mid-spawn with its server still loading (so it reads unhealthy here). If an unlocked waiter
deleted the sentinel on that 'unhealthy' read, it would then acquire the lock, find no sentinel, and
spawn a second server."*

`test_seam_s3_may_not_create_a_process_and_the_plan_says_so_twice` is **D179**: 08:1046 requires
this module to spawn, and 02:430 permits only `toolchain.py` and `host/subproc.py` to import
`subprocess`.

The engine-sizing table is transcribed from `08:1108` cell by cell, because every cell of it is the
arithmetic in `engine_sizing()` and a table that drifted from the function would be five worked
examples of the wrong function.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import omniweave_core.modelserver as ms
import pytest
from omniweave_core.errors import ConfigError, DriverHostError
from omniweave_core.limits import MAX_AUTO_PARALLEL
from omniweave_core.modelserver import (
    BASELINE_MAX_BATCHED_TOKENS,
    BASELINE_MAX_NUM_SEQS,
    BASELINE_VRAM_GB,
    HEALTH_PATH,
    LOOPBACK,
    MODELS_PATH,
    PORT_ATTEMPTS,
    SENTINEL_MODE,
    TOKEN_BYTES,
    Attachment,
    Handle,
    Sentinel,
    ServiceHandle,
    ServiceProbe,
    ServiceRegistry,
    ServiceSpec,
    Spawned,
    Spawner,
    _split,
    attach_or_spawn,
    endpoint_env_var,
    engine_sizing,
    mint_token,
    pick_port,
    pinned_endpoint,
    read_sentinel,
    refuse_unverified,
    sentinel_name,
    server_argv,
    service_capacity,
    spawn_env,
    write_sentinel,
)
from omniweave_ports import ServiceHandle as PortsHandle

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from conftest import PlanDocs

DIGEST = "9f8e7d6c5b4a3928"
MODEL = "allenai/olmOCR-7B"
REV = "9f8e7d6c5b4a39281726354453627180a9b8c7d6"


def spec(**kwargs: object) -> ServiceSpec:
    base: dict[str, object] = {
        "name": "vlm",
        "model_id": MODEL,
        "model_revision": REV,
        "server_argv": ("python", "-m", "engine"),
    }
    base.update(kwargs)
    return ServiceSpec(**base)  # type: ignore[arg-type]


class _Probe:
    """A `ServiceProbe` that answers from a script and records what it was asked."""

    def __init__(self, *, healthy: bool = True, reported: str = MODEL) -> None:
        self._healthy = healthy
        self._reported = reported
        self.asked: list[tuple[str, str]] = []

    def healthy(self, base_url: str, *, token: str, timeout_s: float) -> bool:
        del timeout_s
        self.asked.append((base_url, token))
        return self._healthy

    def model_id(self, base_url: str, *, token: str, timeout_s: float) -> str:
        del base_url, token, timeout_s
        return self._reported


def sentinel(port: int = 8000, token: str = "de") -> Sentinel:
    return Sentinel(
        port=port,
        pid=4321,
        create_time=1.5,
        token=token,
        model_id=MODEL,
        model_rev=REV,
        started_ns=1_700_000_000_000_000_000,
    )


# =============================================================================================
# 1. `ServiceSpec` -- 08:948-965, field for field
# =============================================================================================


def printed_spec(plan: PlanDocs) -> str:
    """08:948-965's fence, which is the only place `ServiceSpec`'s shape is written down."""
    return next(
        fence for fence in plan.fences("08-runtime.md", "python") if "class ServiceSpec" in fence
    )


@pytest.mark.parametrize(
    ("field_name", "printed", "value"),
    [
        ("batch_wait_ms", "5", 5),
        ("max_batch", "8", 8),
        ("keep_alive_s", "300", 300),
        ("startup_timeout_s", "600", 600),
        ("request_timeout_s", "600", 600),
        ("vram_floor_mb", "0", 0),
        ("gpu_group", '"default"', "default"),
    ],
)
def test_the_printed_defaults_are_the_shipped_ones(
    plan: PlanDocs, field_name: str, printed: str, value: object
) -> None:
    """The seven fields 08's fence gives an `=` to, read out of the fence rather than memory."""
    plan.require()
    assert re.search(rf"{field_name}: \w+ = {re.escape(printed)}", printed_spec(plan))
    assert getattr(spec(), field_name) == value


def test_the_three_fields_whose_defaults_are_prose_and_not_code(plan: PlanDocs) -> None:
    """`endpoint`, `autostart` and `capacity` carry no `=` in the fence; their comments carry it.

    *"`endpoint: str  # "" = attach-or-spawn on demand"*, *"`autostart: bool  # default true"*,
    *"`capacity: int  # 0 = derive"*. A dataclass cannot have a defaulted field after an
    undefaulted one, so the three either take the comment's value or every construction site
    repeats them. They take the comment's value, and this test is the transcription.
    """
    plan.require()
    fence = printed_spec(plan)
    assert "endpoint: str" in fence and '"" = attach-or-spawn on demand' in fence
    assert "autostart: bool" in fence and "default true" in fence
    assert "capacity: int" in fence and "0 = derive" in fence
    built = spec()
    assert (built.endpoint, built.autostart, built.capacity) == ("", True, 0)


def test_the_fence_declares_fourteen_fields(plan: PlanDocs) -> None:
    """08:948-965. A field added here without a plan edit is a fifteenth nobody specified."""
    plan.require()
    body = printed_spec(plan).split("class ServiceSpec:")[1].split("@dataclass")[0]
    declared = re.findall(r"^    (\w+): ", body, flags=re.MULTILINE)
    assert len(declared) == 14
    assert tuple(declared) == tuple(f.name for f in dataclasses.fields(ServiceSpec))


def test_a_branch_name_is_not_a_revision() -> None:
    """RT14, framework-wide, and this is the one place a spec is built from a config file."""
    with pytest.raises(ConfigError, match="branch and not a revision"):
        spec(model_revision="main")


def test_a_missing_revision_is_refused_too() -> None:
    with pytest.raises(ConfigError, match="no model_revision"):
        spec(model_revision="")


def test_a_service_without_a_model_id_is_refused() -> None:
    """*"A Service's model is on NO card"*, so nothing else in the framework records it."""
    with pytest.raises(ConfigError, match="model_id"):
        spec(model_id="")


def test_a_service_without_a_name_is_refused() -> None:
    with pytest.raises(ConfigError, match="has no name"):
        spec(name="")


def test_an_endpoint_makes_a_service_pinned() -> None:
    assert spec().pinned is False
    assert spec(endpoint=f"http://{LOOPBACK}:8000").pinned is True


# =============================================================================================
# 2. The sentinel
# =============================================================================================


def test_the_sentinel_name_carries_the_config_digest() -> None:
    """Addition 2 of three: two configurations cannot find each other's sentinel."""
    assert sentinel_name("vlm", DIGEST) == f"vlm-{DIGEST}.json"
    assert sentinel_name("vlm", "other") != sentinel_name("vlm", DIGEST)


def test_a_sentinel_needs_both_halves_of_its_identity() -> None:
    with pytest.raises(ConfigError, match="one of them is empty"):
        sentinel_name("vlm", "")


def test_a_sentinel_round_trips() -> None:
    original = sentinel()
    assert Sentinel.parse(original.as_json()) == original


def test_the_payload_is_byte_stable() -> None:
    """Read by another process and by a human, so a rendering that moved would be noise."""
    body = sentinel().as_json()
    assert body == json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"))


def test_the_base_url_is_the_one_sanctioned_form() -> None:
    assert sentinel(port=8123).base_url == f"http://{LOOPBACK}:8123"


def test_an_unparseable_sentinel_is_absent_rather_than_an_error() -> None:
    """A half-written file is what a crash mid-spawn leaves; the locked path repairs it."""
    assert Sentinel.parse("{not json") is None
    assert Sentinel.parse('{"port": 1}') is None
    assert Sentinel.parse("[]") is None


def test_the_sentinel_is_written_at_0600(tmp_path: Path) -> None:
    """The token is the whole of the access control, so the mode is not a second step."""
    path = tmp_path / "vlm.json"
    write_sentinel(path, sentinel())
    assert read_sentinel(path) == sentinel()
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == SENTINEL_MODE


def test_reading_a_sentinel_that_is_not_there_is_absent(tmp_path: Path) -> None:
    assert read_sentinel(tmp_path / "missing.json") is None


def test_a_token_is_thirty_two_bytes_of_urandom_in_hex() -> None:
    """`surya/settings.py:97` is `VLLM_API_KEY = "EMPTY"`; this is the hole that closes."""
    token = mint_token()
    assert len(token) == TOKEN_BYTES * 2
    assert re.fullmatch(r"[0-9a-f]+", token)
    assert token != mint_token()


# =============================================================================================
# 3. Verification -- a refusal, never a retry
# =============================================================================================


def test_a_matching_model_id_verifies() -> None:
    refuse_unverified(spec(), MODEL, where="endpoint")


def test_a_mismatched_model_id_is_fatal_and_names_both() -> None:
    """08:1012: *"retrying attaches to the same wrong server."*"""
    with pytest.raises(ConfigError) as raised:
        refuse_unverified(spec(), "meta-llama/Llama-3", where="endpoint")
    assert MODEL in str(raised.value)
    assert "meta-llama/Llama-3" in str(raised.value)
    assert "never retried" in str(raised.value)


def test_a_server_that_will_not_say_what_it_runs_is_refused() -> None:
    """08:1054's port race makes *"a foreign listener that DID bind"* a case this catches."""
    with pytest.raises(ConfigError, match="no id reported"):
        refuse_unverified(spec(), "", where="endpoint")


def test_the_plan_types_this_refusal_itself(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("08-runtime.md"))
    assert "A model-id mismatch is a FATAL ConfigError, never a retry" in text


# =============================================================================================
# 4. Capacity and sizing
# =============================================================================================


def test_capacity_is_the_three_lines_the_plan_prints() -> None:
    assert service_capacity(spec(), 8) == 8
    assert service_capacity(spec(capacity=4), 8) == 4
    assert service_capacity(spec(capacity=64), 8) == 8, "the server's own report is a ceiling too"


def test_max_auto_parallel_is_a_cap_and_not_a_default() -> None:
    """08:1072: 48 to 96 is +28% on a B200; a flat 96 on a 24 GB card is an OOM."""
    assert service_capacity(spec(capacity=240), 240) == MAX_AUTO_PARALLEL
    assert MAX_AUTO_PARALLEL == 96


def test_a_server_reporting_nothing_still_leaves_the_service_usable() -> None:
    assert service_capacity(spec(), 0) == 1


#: `08:1109-1115`'s table, and the two cells where it disagrees with `08:1104`'s own formula.
#: **D180.** `floor` ships, because the fence is the executable statement and because `ceil` is
#: the OOM direction on a card this section exists to protect.
SIZING = (
    (16, 4_096, 4_096, 16),
    (24, 8_192, 8_192, 32),
    (48, 16_384, 16_384, 64),
    (80, 32_768, 16_384, 104),
    (180, 65_536, 32_768, 240),
)


@pytest.mark.parametrize(("vram_gb", "printed", "computed", "seqs"), SIZING)
def test_the_engine_sizing_table_is_the_arithmetic_except_at_two_cards(
    vram_gb: int, printed: int, computed: int, seqs: int
) -> None:
    """08:1117 claims *"every cell is the arithmetic above"*, and at two cards it is not. D180.

    The three cards that agree are the three whose ratio is a power of two times the baseline,
    which is exactly where `floor` and `ceil` cannot differ. `max_num_seqs` agrees everywhere, and
    it is the only column 08:1117's worked example actually works.
    """
    del printed
    assert engine_sizing(vram_gb) == (computed, seqs)


def test_the_two_disagreeing_cells_are_the_ones_the_defect_names() -> None:
    """If the plan is amended either way, this says which cells moved."""
    disagreeing = [row[0] for row in SIZING if row[1] != row[2]]
    assert disagreeing == [80, 180]


@pytest.mark.parametrize(("vram_gb", "printed", "computed", "seqs"), SIZING)
def test_the_max_num_seqs_column_agrees_at_every_card(
    vram_gb: int, printed: int, computed: int, seqs: int
) -> None:
    del printed, computed
    assert engine_sizing(vram_gb)[1] == seqs


def test_the_baseline_is_the_plans_three_numbers() -> None:
    assert (BASELINE_VRAM_GB, BASELINE_MAX_BATCHED_TOKENS, BASELINE_MAX_NUM_SEQS) == (24, 8192, 32)
    assert engine_sizing(BASELINE_VRAM_GB) == (BASELINE_MAX_BATCHED_TOKENS, BASELINE_MAX_NUM_SEQS)


def test_a_tiny_card_still_gets_the_floors() -> None:
    """`max(1024, ...)` and `max(8, ...)`: an unknown card sizes rather than refusing."""
    assert engine_sizing(1) == (1024, 8)


def test_an_unread_device_is_refused_rather_than_sized() -> None:
    with pytest.raises(ConfigError) as raised:
        engine_sizing(0)
    assert "0 means the device was not read" in raised.value.fix


# =============================================================================================
# 5. argv and the environment
# =============================================================================================


def test_the_checkpoint_is_pinned_so_the_verification_means_something() -> None:
    """08:1058: the child reports the id the client then verifies."""
    argv = server_argv(spec(), port=8000)
    assert argv[:3] == ("python", "-m", "engine")
    assert argv[-2:] == ("--checkpoint", MODEL)
    assert "--host" in argv
    assert argv[argv.index("--host") + 1] == LOOPBACK
    assert argv[argv.index("--port") + 1] == "8000"


def test_the_bind_address_is_not_configurable() -> None:
    """A bind address a config file could widen is a network service nobody asked for."""
    argv = server_argv(spec(server_argv=("python", "--host", "0.0.0.0")), port=1)  # noqa: S104
    assert argv[-6:-4] == ("--host", LOOPBACK), "the framework's --host is appended last"


def test_a_service_with_nothing_to_spawn_is_refused() -> None:
    with pytest.raises(ConfigError, match="nothing to spawn"):
        server_argv(spec(server_argv=()), port=8000)


def test_a_cuda_group_pins_the_device() -> None:
    assert spawn_env(spec(gpu_group="cuda:1"), {})["CUDA_VISIBLE_DEVICES"] == "1"


def test_the_default_group_pins_nothing() -> None:
    """*"`default` means 'whatever the engine picks', which is the single-GPU case."*"""
    assert "CUDA_VISIBLE_DEVICES" not in spawn_env(spec(), {})
    assert "CUDA_VISIBLE_DEVICES" not in spawn_env(spec(gpu_group="big"), {})
    assert "CUDA_VISIBLE_DEVICES" not in spawn_env(spec(gpu_group="cuda:x"), {})


def test_the_base_environment_is_carried_and_not_replaced() -> None:
    env = spawn_env(spec(gpu_group="cuda:0"), {"PATH": "/usr/bin"})
    assert env["PATH"] == "/usr/bin"
    assert env["CUDA_VISIBLE_DEVICES"] == "0"


# =============================================================================================
# 6. The port, and the endpoint parser that refuses to leave the machine
# =============================================================================================


def test_a_picked_port_is_free_and_in_range() -> None:
    port = pick_port()
    assert 1024 < port < 65536


def test_the_port_race_is_handled_in_three_places(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("08-runtime.md"))
    assert "This window is a real race and it is handled, not ignored" in text
    assert PORT_ATTEMPTS == 3


def test_an_endpoint_that_is_not_loopback_cannot_be_dialled() -> None:
    """02:432 sanctions two loopback endpoints and no third; this is the enforcement site."""
    with pytest.raises(ConfigError, match="must be loopback"):
        _split("http://10.0.0.5:8000")


def test_an_endpoint_with_a_path_is_refused() -> None:
    with pytest.raises(ConfigError, match="no path"):
        _split(f"http://{LOOPBACK}:8000/v1")


def test_an_https_endpoint_is_refused() -> None:
    with pytest.raises(ConfigError, match="http://<host>:<port>"):
        _split(f"https://{LOOPBACK}:8000")


def test_an_endpoint_without_a_port_is_refused() -> None:
    with pytest.raises(ConfigError, match="needs a port"):
        _split(f"http://{LOOPBACK}")


def test_a_loopback_endpoint_splits() -> None:
    assert _split(f"http://{LOOPBACK}:8000") == (LOOPBACK, 8000)


# =============================================================================================
# 7. The ladder's attach halves
# =============================================================================================


def test_step_zero_attaches_to_a_pinned_endpoint_and_spawns_nothing(tmp_path: Path) -> None:
    probe = _Probe()
    attached = attach_or_spawn(
        spec(endpoint=f"http://{LOOPBACK}:8000"),
        services_root=tmp_path,
        config_digest=DIGEST,
        probe=probe,
        spawner=None,
    )
    assert attached.how == "pinned"
    assert attached.lifecycle == "attached"
    assert attached.spawned is False
    assert attached.base_url == f"http://{LOOPBACK}:8000"
    assert not list(tmp_path.iterdir()), "no lock, no sentinel, nothing written"


def test_a_pinned_endpoint_that_does_not_answer_names_the_key_and_the_env_var(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError) as raised:
        attach_or_spawn(
            spec(endpoint=f"http://{LOOPBACK}:8000"),
            services_root=tmp_path,
            config_digest=DIGEST,
            probe=_Probe(healthy=False),
        )
    assert "SERVICE_UNREACHABLE" in str(raised.value)
    assert "OMNIWEAVE_SERVICES_VLM_ENDPOINT" in raised.value.fix


def test_a_pinned_endpoint_running_the_wrong_model_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="never retried"):
        attach_or_spawn(
            spec(endpoint=f"http://{LOOPBACK}:8000"),
            services_root=tmp_path,
            config_digest=DIGEST,
            probe=_Probe(reported="meta-llama/Llama-3"),
        )


def test_the_env_twin_wins_over_the_config_file() -> None:
    """14:438: an env-locked endpoint is operator-provisioned and the config value is read-only."""
    env = {"OMNIWEAVE_SERVICES_VLM_ENDPOINT": f"http://{LOOPBACK}:9999"}
    assert pinned_endpoint(spec(endpoint=f"http://{LOOPBACK}:8000"), env) == (
        f"http://{LOOPBACK}:9999"
    )
    assert pinned_endpoint(spec(endpoint=f"http://{LOOPBACK}:8000"), {}) == (
        f"http://{LOOPBACK}:8000"
    )


def test_the_env_var_name_is_the_printed_shape() -> None:
    assert endpoint_env_var("vlm") == "OMNIWEAVE_SERVICES_VLM_ENDPOINT"
    assert endpoint_env_var("page-vlm") == "OMNIWEAVE_SERVICES_PAGE_VLM_ENDPOINT"


def test_step_one_attaches_through_the_sentinel(tmp_path: Path) -> None:
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel(token="abcd"))
    probe = _Probe()
    attached = attach_or_spawn(spec(), services_root=tmp_path, config_digest=DIGEST, probe=probe)
    assert attached.how == "sentinel"
    assert attached.token == "abcd"
    assert probe.asked == [(f"http://{LOOPBACK}:8000", "abcd")], "the token rides on the probe"


def test_an_unhealthy_sentinel_is_not_mutated_by_the_unlocked_path(tmp_path: Path) -> None:
    """Surya's subtlest rule: an unlocked waiter that deleted it would cause a second server.

    *"One holds the lock mid-spawn with its server still loading (so it reads unhealthy here). If
    an unlocked waiter deleted the sentinel on that 'unhealthy' read, it would then acquire the
    lock, find no sentinel, and spawn a second server."*
    """
    path = tmp_path / sentinel_name("vlm", DIGEST)
    write_sentinel(path, sentinel())
    before = path.read_bytes()
    with pytest.raises(DriverHostError):
        attach_or_spawn(
            spec(), services_root=tmp_path, config_digest=DIGEST, probe=_Probe(healthy=False)
        )
    assert path.exists(), "the unlocked path must not delete a sentinel it read as unhealthy"
    assert path.read_bytes() == before


def test_a_sentinel_for_another_config_digest_is_not_found(tmp_path: Path) -> None:
    write_sentinel(tmp_path / sentinel_name("vlm", "other"), sentinel())
    with pytest.raises(DriverHostError):
        attach_or_spawn(spec(), services_root=tmp_path, config_digest=DIGEST, probe=_Probe())


def test_a_sentinel_whose_server_runs_the_wrong_model_is_fatal(tmp_path: Path) -> None:
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel())
    with pytest.raises(ConfigError, match="never retried"):
        attach_or_spawn(
            spec(),
            services_root=tmp_path,
            config_digest=DIGEST,
            probe=_Probe(reported="meta-llama/Llama-3"),
        )


def test_step_two_refuses_when_autostart_is_off(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        attach_or_spawn(
            spec(autostart=False),
            services_root=tmp_path,
            config_digest=DIGEST,
            probe=_Probe(healthy=False),
        )
    assert "SERVICE_NOT_RUNNING" in str(raised.value)
    assert "autostart" in raised.value.fix


# =============================================================================================
# 8. D179 -- seam S3 must spawn and may not spawn
# =============================================================================================


def test_seam_s3_may_not_create_a_process_and_the_plan_says_so_twice(plan: PlanDocs) -> None:
    """D179. 08:1046 requires the spawn; 02:430 permits two modules to, and this is neither."""
    plan.require()
    architecture = " ".join(plan.lines("02-architecture.md"))
    assert "only `omniweave_core.toolchain` and" in architecture
    assert "`omniweave_core.host.subproc` may import `subprocess` (G8)" in architecture
    assert "A fifth seam is a charter amendment." in architecture
    runtime = " ".join(plan.lines("08-runtime.md"))
    assert "4. SPAWN DETACHED" in runtime


def test_this_module_imports_no_subprocess() -> None:
    """What keeps G8 at two exemptions rather than three.

    Over the parsed tree and not the text: the module's own docstring quotes the ban, so a
    substring check would fail on the sentence that explains why the import is absent.
    """
    tree = ast.parse(Path(ms.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    spawns: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            spawns.add(node.func.attr)
    assert "subprocess" not in imported
    assert not {"posix_spawn", "spawnv", "spawnvp", "fork", "forkpty"} & spawns


def test_a_spawn_with_no_spawner_refuses_and_names_the_defect(tmp_path: Path) -> None:
    with pytest.raises(DriverHostError) as raised:
        attach_or_spawn(
            spec(), services_root=tmp_path, config_digest=DIGEST, probe=_Probe(healthy=False)
        )
    assert "D179" in str(raised.value)
    assert "02-architecture.md:430" in str(raised.value)


def test_the_spawner_protocol_is_what_a_host_would_implement() -> None:
    """Declared here, implemented where the exemption lives. Structural, not `runtime_checkable`."""

    class Host:
        def spawn(
            self,
            argv: object,
            *,
            env: object,
            log_path: object,
        ) -> Spawned:
            del argv, env, log_path
            return Spawned(pid=1, create_time=2.0)

    checked: Spawner = Host()
    assert checked.spawn((), env={}, log_path=None) == Spawned(pid=1, create_time=2.0)
    assert getattr(Spawner, "_is_runtime_protocol", False) is False


def test_the_probe_protocol_is_satisfied_by_the_fake_this_file_uses() -> None:
    checked: ServiceProbe = _Probe()
    assert checked.healthy("http://x", token="", timeout_s=1.0) is True


# =============================================================================================
# 9. What the plan says this seam is
# =============================================================================================


def test_a_service_is_named_and_never_routed(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("08-runtime.md"))
    assert "named and never routed" in text
    assert "never enters `resolve()`" in text


def test_the_two_probe_paths_are_the_printed_ones(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("08-runtime.md"))
    assert f"GET {{endpoint}}{HEALTH_PATH}" in text
    assert f"GET {MODELS_PATH}" in text


def test_the_attachment_records_which_branch_produced_it() -> None:
    """`lifecycle` is `attached` for two branches and `spawned` for one. 08:1258."""
    branches = (("pinned", "attached"), ("sentinel", "attached"), ("spawned", "spawned"))
    for how, lifecycle in branches:
        built = Attachment(
            spec=spec(),
            base_url=f"http://{LOOPBACK}:1",
            token="",
            model_id=MODEL,
            model_rev=REV,
            how=how,  # type: ignore[arg-type]
        )
        assert built.lifecycle == lifecycle
        assert built.spawned == (how == "spawned")


def test_only_the_spawning_process_owns_the_reaper(plan: PlanDocs) -> None:
    """08:1213 is inside a fence and wraps, so the whitespace is normalised before matching."""
    plan.require()
    text = re.sub(r"\s+", " ", plan.text("08-runtime.md"))
    assert "A process that ATTACHED never stops a server it did not start." in text


# =============================================================================================
# 10. The handle a driver is given, and the per-run registry that gives it
# =============================================================================================


def registry(tmp_path: Path, **kwargs: object) -> ServiceRegistry:
    base: dict[str, object] = {
        "specs": {"vlm": spec()},
        "services_root": tmp_path,
        "config_digest": DIGEST,
        "probe": _Probe(),
    }
    base.update(kwargs)
    return ServiceRegistry(**base)  # type: ignore[arg-type]


def test_the_handle_is_a_base_url_a_token_and_a_deadline() -> None:
    """*"NOT a client library ... so `omniweave-llm` needs neither torch nor an SDK."*"""
    built = Handle(
        name="vlm",
        base_url=f"http://{LOOPBACK}:8000",
        token="abcd",
        model_id=MODEL,
        model_rev=REV,
        capacity=8,
        traceparent="00-a-b-01",
        deadline_ms=5_000,
    )
    assert built.cancelled() is False
    assert built.capacity == 8


def test_a_handle_reports_cancellation_from_the_token_it_was_given() -> None:
    """Injected, because a handle that computed it would be a second cancellation authority."""
    flag = [False]
    built = Handle(
        name="vlm",
        base_url=f"http://{LOOPBACK}:8000",
        token="abcd",
        model_id=MODEL,
        model_rev=REV,
        capacity=1,
        traceparent="",
        deadline_ms=0,
        _cancelled=lambda: flag[0],
    )
    assert built.cancelled() is False
    flag[0] = True
    assert built.cancelled() is True


def test_the_alias_and_the_class_are_one_thing() -> None:
    """02 row 15 prints `ServiceHandle`; the ports Protocol owns that name for a driver."""
    assert ServiceHandle is Handle


def test_the_shipped_handle_satisfies_the_ports_protocol() -> None:
    """The split `BlobStore` uses: a Protocol in ports, a class in core, one concept."""
    checked: PortsHandle = Handle(
        name="vlm",
        base_url=f"http://{LOOPBACK}:8000",
        token="abcd",
        model_id=MODEL,
        model_rev=REV,
        capacity=1,
        traceparent="",
        deadline_ms=0,
    )
    assert checked.model_id == MODEL


def test_nothing_is_live_until_something_asks(tmp_path: Path) -> None:
    """INV-13's floor: a clean born-digital page starts no model server."""
    reg = registry(tmp_path)
    assert list(reg.live()) == []


def test_a_service_becomes_live_on_the_first_call(tmp_path: Path) -> None:
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel())
    reg = registry(tmp_path)
    reg.handle("vlm")
    assert [s.name for s in reg.live()] == ["vlm"]


def test_the_attachment_is_memoised_per_run(tmp_path: Path) -> None:
    """08:983: *"attach_or_spawn, memoised per run."* The ladder runs once."""
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel())
    probe = _Probe()
    reg = registry(tmp_path, probe=probe)
    first = reg.attach("vlm")
    second = reg.attach("vlm")
    assert first is second
    assert len(probe.asked) == 1


def test_a_name_with_no_table_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="names nothing"):
        registry(tmp_path).handle("missing")


def test_the_handle_carries_the_runs_trace_and_deadline(tmp_path: Path) -> None:
    """Per call, because a registry holding a deadline would issue handles from an expired one."""
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel(token="abcd"))
    got = registry(tmp_path).handle("vlm", traceparent="00-a-b-01", deadline_ms=1_234, capacity=8)
    assert (got.traceparent, got.deadline_ms, got.capacity) == ("00-a-b-01", 1_234, 8)
    assert got.token == "abcd"
    assert got.base_url == f"http://{LOOPBACK}:8000"


def test_get_is_an_alias_for_handle() -> None:
    """02 row 15 prints `get`; 08:983's fence prints `handle`. One method, not two."""
    assert ServiceRegistry.get is ServiceRegistry.handle


def test_eviction_drops_the_memo_and_records_the_reason(tmp_path: Path) -> None:
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel())
    reg = registry(tmp_path)
    reg.attach("vlm")
    reg.evict("vlm", "gpu_group_pressure")
    assert list(reg.live()) == []
    rows = list(reg.observe())
    assert rows == [{"name": "vlm", "lifecycle": "evicted", "reason": "gpu_group_pressure"}]


def test_an_eviction_needs_a_reason() -> None:
    """`service.evict{name, reason}` carries one, so this refuses rather than inventing it."""
    with pytest.raises(ConfigError, match="needs a reason"):
        ServiceRegistry({}, services_root=Path(), config_digest=DIGEST).evict("vlm", "")


def test_re_attaching_after_an_eviction_runs_the_ladder_again(tmp_path: Path) -> None:
    """Eviction is bookkeeping, so group pressure is recoverable rather than terminal."""
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel())
    probe = _Probe()
    reg = registry(tmp_path, probe=probe)
    reg.attach("vlm")
    reg.evict("vlm", "keep_alive_expired")
    reg.attach("vlm")
    assert len(probe.asked) == 2


def test_observe_yields_and_writes_nothing(tmp_path: Path) -> None:
    """`service_observation` is a store table; this hands a writer the columns it can fill."""
    write_sentinel(tmp_path / sentinel_name("vlm", DIGEST), sentinel())
    reg = registry(tmp_path)
    reg.attach("vlm")
    (row,) = list(reg.observe())
    assert row["name"] == "vlm"
    assert row["lifecycle"] == "attached"
    assert row["model_id"] == MODEL
    assert "peak_inflight" not in row, "a 0 for an unmeasured figure reads as measured"
    assert "gpu_ms" not in row


def test_there_is_no_ambient_registry() -> None:
    """*"omniweave takes the injection and does not ship the singleton at all."* 08:990."""
    assert not hasattr(ms, "get_default_manager")
    assert not hasattr(ms, "default_registry")
    assert not [name for name in vars(ms) if name.isupper() and "REGISTRY" in name]
