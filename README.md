# Legion Go Gyro DSU for Decky Loader

A small Decky Loader plugin for starting and stopping the
`LegionGoSGyroDSU` background service from the Steam Quick Access menu.

## Requirements

- Decky Loader
- LegionGoSGyroDSU installed as `lgsdsu.service`
- systemd

The plugin requests Decky's root backend because controlling a system service
requires elevated privileges. Its backend executes only fixed `systemctl`
operations against `lgsdsu.service`; the frontend cannot supply a unit name or
an arbitrary shell command.

## Behavior

- The toggle always reflects the current systemd state.
- Switching it on starts `lgsdsu.service`.
- Switching it off stops `lgsdsu.service`.
- The status is read when the plugin loads, after every toggle, and when the
  user selects **Refresh status**. There is no background polling that would
  create unnecessary wake-ups while the motion server is stopped.
- Errors and a missing LegionGoSGyroDSU installation are shown in the UI.
- Stopping the service does not disable it permanently. It will start again on
  the next boot because the LegionGoSGyroDSU installer enables the unit.

## Development

Install pnpm 9 and build the frontend:

```bash
npm install --global pnpm@9
pnpm install
pnpm run typecheck
pnpm run build
```

Decky Loader expects the distributable plugin to contain:

```text
dist/index.js
main.py
package.json
plugin.json
LICENSE
```

For deployment and packaging, follow the current
[Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).
