# 0003 — Isolate Metashape trial activation in its own script

- **Status:** Accepted
- **Date:** 2026-05-25
- **Chat:** 3 (EC2 bootstrap)

## Context

The Metashape Professional 30-day trial begins the moment the trial is
activated against an Agisoft account, and cannot be paused, extended,
or transferred. The trial fingerprint binds to the network interface
MAC of the activating machine, which makes a rebuild expensive even if
days remain on the original trial.

The single biggest risk to a 6–8 weekend portfolio project of this
shape is spending trial days on infrastructure. If the bootstrap
script — which installs DCV, QGIS, Python, system packages, and
several gigabytes of dependencies — silently activated the trial as
part of its end-of-run validation, then a re-bootstrap after any later
failure (data corruption, AMI rebuild, instance type change) would
burn additional days against the original 30.

A second concern: a single monolithic `bootstrap.sh` that ends with
trial activation is easy to read top-to-bottom and accidentally accept
the activation it implies. Separating activation into a discrete
script with an explicit consent prompt makes the irreversible step
hard to take by accident.

## Decision

Trial activation lives in `04_activate_trial.sh`. The script:

- Refuses to run unless the operator types `ACTIVATE` in capital
  letters at a prompt.
- Records the activation timestamp, instance ID, and active MAC to
  `~/bootstrap-logs/metashape-trial-activation.log` so the trial
  start can be cited precisely in the Chat 6 provenance manifest.
- Documents the manual GUI step required (trial registration in the
  Agisoft activation dialog is not reliably scriptable headlessly in
  Metashape 2.x — it requires an email-entry form). The script walks
  the operator through doing that step over DCV.

The other four bootstrap scripts (`01_bootstrap.sh`,
`02_install_metashape.sh`, `03_install_dcv.sh`, `05_validate.sh`) can
all be rerun arbitrarily many times without consuming trial days.

## Consequences

- `01_bootstrap.sh run_all` does not start the trial. Operator must
  separately invoke `04_activate_trial.sh` when ready.
- Validation (`05_validate.sh`) is positioned as a gate before
  activation: all checks must pass first.
- The pre-trial boot-volume snapshot recommended in
  `docs/ec2-bootstrap.md` is the rollback target if activation binds
  to the wrong MAC.
- If a purchased node-locked license is acquired later (post-trial),
  the activation flow uses `metashape.sh --activate <key>` and is
  scriptable headlessly. A future ADR will document that path.

## Notebook narrative

> The processing pipeline ran under a 30-day Agisoft Metashape
> Professional trial. The trial clock cannot be paused, and the
> trial fingerprint binds to a network-interface MAC, so the project
> infrastructure was designed around protecting trial days. In
> particular, all system bootstrap (system updates, Python toolchain,
> DCV server, QGIS, Metashape binary install) ran to completion and
> was independently validated *before* the trial was activated. This
> separation is mechanical, not stylistic: the bootstrap orchestrator
> and the trial-activation script are different files, and activation
> requires explicit operator consent. The activation timestamp is
> captured in the project provenance log (Chat 6) so the trial window
> can be cited precisely against processing timestamps.
