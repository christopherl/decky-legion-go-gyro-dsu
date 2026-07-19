import asyncio
from dataclasses import asdict, dataclass

import decky


SERVICE_NAME = "lgsdsu.service"
COMMAND_TIMEOUT_SECONDS = 10


@dataclass
class ServiceStatus:
    installed: bool
    active: bool
    state: str
    error: str | None = None


async def run_systemctl(*arguments: str) -> tuple[int, str, str]:
    """Run systemctl without a shell and return its exit code and output."""
    process = await asyncio.create_subprocess_exec(
        "systemctl",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=COMMAND_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("systemctl timed out") from None

    return (
        process.returncode,
        stdout.decode(errors="replace").strip(),
        stderr.decode(errors="replace").strip(),
    )


async def read_service_status() -> ServiceStatus:
    load_code, load_state, load_error = await run_systemctl(
        "show", SERVICE_NAME, "--property=LoadState", "--value"
    )
    if load_code != 0 or load_state in {"", "not-found"}:
        message = load_error or f"{SERVICE_NAME} is not installed"
        return ServiceStatus(False, False, "not-installed", message)

    active_code, active_state, active_error = await run_systemctl(
        "is-active", SERVICE_NAME
    )
    active = active_code == 0 and active_state == "active"
    error = active_error if active_code not in {0, 3} and active_error else None
    return ServiceStatus(True, active, active_state or "unknown", error)


class Plugin:
    async def get_service_status(self) -> dict:
        try:
            return asdict(await read_service_status())
        except Exception as error:
            decky.logger.exception("Unable to read %s status", SERVICE_NAME)
            return asdict(ServiceStatus(False, False, "error", str(error)))

    async def set_service_enabled(self, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            return asdict(
                ServiceStatus(False, False, "error", "enabled must be a boolean")
            )

        current = await read_service_status()
        if not current.installed:
            return asdict(current)

        action = "start" if enabled else "stop"
        code, _, error = await run_systemctl(action, SERVICE_NAME)
        if code != 0:
            message = error or f"systemctl {action} failed with exit code {code}"
            decky.logger.error("Unable to %s %s: %s", action, SERVICE_NAME, message)
            return asdict(ServiceStatus(True, current.active, "error", message))

        result = await read_service_status()
        if result.active != enabled:
            expected = "active" if enabled else "inactive"
            result.error = f"Expected {expected}, but service is {result.state}"
        return asdict(result)

    async def _main(self):
        decky.logger.info("Legion Go Gyro DSU controller loaded")

    async def _unload(self):
        decky.logger.info("Legion Go Gyro DSU controller unloaded")
