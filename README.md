# Legion Go Gyro DSU for Decky Loader

A small Decky Loader plugin for controlling `LegionGoSGyroDSU` from the Steam
Quick Access menu and visualizing the handheld's orientation in real time.

## Required DSU server

This plugin is a companion frontend for
[LegionGoSGyroDSU](https://github.com/Sooly890/LegionGoSGyroDSU), the original
open source project by Sooly890. LegionGoSGyroDSU provides the background
service, reads the motion sensors and exposes their data through a DSU server.
This Decky plugin only controls that service and optionally visualizes its DSU
motion data.

The Legion Go 2 HID motion backend is currently being developed in
[christopherl's LegionGoSGyroDSU fork](https://github.com/christopherl/LegionGoSGyroDSU/tree/feature/legion-hid-motion-source).
Until that work is accepted upstream, Legion Go 2 users need to install the
`feature/legion-hid-motion-source` branch from that fork. Legion Go S users can
use the original upstream project.

## Requirements

- Decky Loader
- [LegionGoSGyroDSU](https://github.com/Sooly890/LegionGoSGyroDSU) installed as
  `lgsdsu.service` (or the Legion Go 2 feature branch linked above)
- systemd

The plugin requests Decky's root backend because controlling a system service
requires elevated privileges. Its backend executes only fixed `systemctl`
operations against `lgsdsu.service`; the frontend cannot supply a unit name or
an arbitrary shell command.

## Behavior

- The toggle always reflects the current systemd state.
- Switching it on starts `lgsdsu.service`.
- Switching it off stops `lgsdsu.service`.
- **Live Rotation** subscribes to controller slot zero on the local DSU server
  and displays the current device orientation as a small 3D model.
- **Recenter orientation** makes the current position the visual origin.
- The status is read when the plugin loads, after every toggle, and when the
  user selects **Refresh status**. There is no background polling that would
  create unnecessary wake-ups while the motion server is stopped.
- The DSU client and 3D rendering run only while **Live Rotation** is switched
  on. Closing/unloading the plugin or stopping the service closes the client.
- Motion packets stay on the device: the client connects only to
  `127.0.0.1:26760`.
- Errors and a missing LegionGoSGyroDSU installation are shown in the UI.
- Stopping the service does not disable it permanently. It will start again on
  the next boot because the LegionGoSGyroDSU installer enables the unit.

## Live rotation details

The Python backend implements the public DSU/Cemuhook UDP protocol directly.
It validates the server header, packet size, message type, controller state and
CRC before using a sample. A one-second subscription keepalive lets the server
remove abandoned clients promptly.

The orientation estimator integrates the gyroscope and uses gravity measured by
the accelerometer to limit roll and pitch drift. DSU does not provide a compass,
so yaw is relative and can drift over time; use **Recenter orientation** when
needed. Frontend updates are capped at 30 Hz to avoid unnecessary Quick Access
menu rendering and battery usage.

## Development

Install pnpm 9 and build the frontend:

```bash
npm install --global pnpm@9
pnpm install
pnpm run typecheck
pnpm run build

python3 -m unittest discover -s tests -v
```

Decky Loader expects the distributable plugin to contain:

```text
dist/index.js
main.py
py_modules/dsu_client.py
package.json
plugin.json
LICENSE
```

For deployment and packaging, follow the current
[Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).
