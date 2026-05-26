# EC2 bootstrap — Chat 3

Bringing the EC2 instance from "first SSH login" to "ready to start the
Metashape trial." Picks up where `docs/aws-setup.md` (Chat 2) left off.

## Decisions baked into this chat

Full records in `docs/decisions/`. One-line summaries:

- **DCV is Amazon DCV 2025.0**, the renamed-but-same product formerly
  called NICE DCV. Server packages still named `nice-dcv-*`. [[ADR-0001]](decisions/0001-amazon-dcv-not-nice-dcv.md)
- **Metashape is pinned to Pro 2.3.1** to preserve the PIFSC SOP
  parameter mapping. Do not bump mid-project. [[ADR-0002]](decisions/0002-metashape-pinned-2-3-1.md)
- **Trial activation is isolated** in `04_activate_trial.sh`, never
  triggered by other scripts; activation requires explicit consent. [[ADR-0003]](decisions/0003-trial-activation-isolated.md)
- **QGIS is from the official LTR repo**, not the Ubuntu archive. [[ADR-0004]](decisions/0004-qgis-from-ltr-repo.md)
- **Chat 5 uses the bundled Metashape Python** at
  `/opt/metashape-pro/python/bin/python3`; everything else uses the
  project venv. Two interpreters, files-on-disk handoff. [[ADR-0005]](decisions/0005-bundled-metashape-python.md)

## Resources from Chat 2

Concrete IDs for this project (canonical source: `docs/aws-resources.md`,
which is gitignored — these are not secrets but are specific to this
account so they don't belong in the public repo):

| Resource | Value |
|---|---|
| Instance ID | `i-06fe7879a0e713c2f` |
| Instance type | `g6.4xlarge` |
| Region / AZ | `us-east-1` / `us-east-1c` |
| AMI ID | `ami-0643f16ddd1e628f4` (DLAMI Base OSS Nvidia GPU Ubuntu 24.04 20260522) |
| Elastic IP | `52.5.136.119` |
| Security group | `sg-0f252e1df4b0fd9af` (port 22 + 8443 from your IP) |
| Secondary ENI | `eni-0f576095ae0c469ae` |
| Secondary ENI MAC | `0a:ff:fc:67:89:8f` ← **license fingerprint binds here** |
| Data volume | `vol-08bcf0ab11df2c9ed` (1 TB gp3, 974 GB free, mounted at `/data`) |
| Launch template | `lt-0673a3230668b47f6` v3 |
| Pre-Chat-3 baseline boot snapshot | `snap-02b52e53f4ad274b7` |
| Pre-Chat-3 baseline data snapshot | `snap-0cd200217026bda4a` |
| Metashape trial | not activated (activates at end of Chat 3) |

The DLAMI ships NVIDIA driver **595.71.05** and **CUDA 13.2** as of the
20260522 snapshot used here. That's newer than what Metashape's release
notes have explicitly tested against (Metashape Pro 2.3.1 was validated
against driver 570.x), but newer NVIDIA drivers are backward-compatible
to older CUDA toolkits and have not historically broken Metashape. The
`05_validate.sh` script confirms Metashape sees the L4 at API level
before the trial is activated — if it doesn't, we'll know before
burning trial days.

Also confirm before running anything in this chat:

- SSH config alias `reef-ec2` resolves to `52.5.136.119` with your
  private key.
- The instance is currently **stopped**. Start it first:
  `aws ec2 start-instances --instance-ids i-06fe7879a0e713c2f`
  (or use the console.) Wait ~60 seconds for it to reach `running`.

## Why Ubuntu 24.04 specifically

Ubuntu 20.04 hit its five-year LTS end-of-life in May 2025, so the matching
DLAMI is no longer receiving security updates. Ubuntu 22.04 still works but
ships an older kernel that lacks recent fixes for G6/L4 instances. The
Ubuntu 24.04 DLAMI ships kernel 6.14-aws, NVIDIA driver 595.71.05, and
CUDA 13.2 — current enough to handle the L4 cleanly and patched enough
to be defensible in the writeup.

## What this chat installs

Layered atop the DLAMI:

| Component | Source | Why |
|---|---|---|
| `apt upgrade` baseline | Ubuntu archive | Pick up post-AMI CVE fixes |
| build-essential, tmux, jq, etc. | apt | Quality of life over SSH |
| Python 3.12 dev headers + venv | apt | For uv to build native deps |
| `uv` package manager | astral.sh installer | Project dependency mgmt |
| Project repo clone | GitHub | On `/data`, not the boot volume |
| Project venv via `uv sync` | pyproject.toml | Reproducible deps |
| Jupyter kernel | `ipykernel install --user` | Cursor + Jupyter discovery |
| QGIS LTR | qgis.org apt repo | Chat 7 GIS work |
| XFCE desktop | apt | Display surface for DCV |
| Amazon DCV server 2025.0 | d1uj6qtbmh3dt5.cloudfront.net | Remote GUI for Metashape |
| Metashape Pro 2.3.1 | download.agisoft.com | Photogrammetry engine |

**Not installed in this chat:**

- The Metashape trial is **not** activated. That's a separate, explicit
  step (`04_activate_trial.sh`) that you only run when you're ready to
  start the 30-day clock. The script will refuse to run silently.
- Cursor / VS Code Remote-SSH server is installed automatically by the
  IDE on first connect from the MacBook — there's nothing to install
  server-side ahead of time.

## Files

```
scripts/bootstrap/
├── 01_bootstrap.sh          # orchestrator + most apt installs
├── 02_install_metashape.sh  # Metashape binary install (no activation)
├── 03_install_dcv.sh        # Amazon DCV server + XFCE
├── 04_activate_trial.sh     # starts the 30-day Metashape clock — LAST
└── 05_validate.sh           # end-to-end check; gate before activation
```

The orchestrator in `01_bootstrap.sh` is sourced or invoked. Every step is a
bash function so you can rerun individual steps after a crash:

```bash
# Run everything (default)
./scripts/bootstrap/01_bootstrap.sh

# Run a single step (use this when something crashed mid-install)
./scripts/bootstrap/01_bootstrap.sh step_qgis

# Or source the file and call functions interactively
. ./scripts/bootstrap/01_bootstrap.sh
step_apt_essentials
step_python
```

All steps are designed to be idempotent: running them twice doesn't break
anything. If a step has already produced its outputs, it short-circuits.

## Timing

Rough wall-clock estimates on a fresh `g6.4xlarge`:

| Step | Time | Notes |
|---|---|---|
| `step_apt_update` | 3–6 min | depends on age of AMI snapshot |
| `step_verify_gpu_stack` | <30 s | just queries — no install |
| `step_verify_eni` | <5 s | informational |
| `step_apt_essentials` | 1–2 min | small package set |
| `step_python` | 30–60 s | venv + dev headers |
| `step_uv` | 10–20 s | single binary download |
| `step_git` | <10 s | + manual GitHub key registration |
| `step_clone_repo` | <10 s | empty-ish repo from Chat 1 |
| `step_uv_sync` | 1–3 min | minimal deps from Chat 1 pyproject |
| `step_jupyter_kernel` | <10 s | just writes a kernel spec |
| `step_qgis` | 3–6 min | pulls a lot of GIS deps |
| `step_dcv` | 5–10 min | XFCE + DCV server |
| `step_metashape_install` | 2–5 min | mostly the tarball download |
| `step_validate` | 1–2 min | runs all checks |

**Total: roughly 30–45 minutes of wall clock,** with one human-in-the-loop
pause to register the SSH key with GitHub. If you see a step run much
longer than this, something has hung — Ctrl-C and check the
`~/bootstrap-logs/bootstrap.log` for the last line.

## Order of operations

1. SSH in: `ssh reef-ec2`
2. `git clone` the bootstrap scripts into your home directory (you can't
   clone the repo yet — that's `step_clone_repo` and needs SSH-key
   registration first):
   ```bash
   mkdir -p ~/scratch && cd ~/scratch
   curl -O https://raw.githubusercontent.com/velezf/reef-sfm-mote-keys/main/scripts/bootstrap/01_bootstrap.sh
   # ... or scp them from MacBook if the repo isn't pushed yet
   chmod +x 01_bootstrap.sh
   ```
3. `./01_bootstrap.sh`
4. When it pauses for the SSH key, copy the printed public key, paste it
   into github.com/settings/ssh/new with title `reef-ec2`, run
   `ssh -T git@github.com` to verify, then press ENTER to continue.
5. Let it run through to `step_validate`.
6. **Take the pre-trial snapshot.** See below.
7. When you're ready to start the 30-day clock, run
   `./04_activate_trial.sh`.

## Resuming after a failure

Every step writes timestamps and `[STEP] OK/FAIL` lines to
`~/bootstrap-logs/bootstrap.log`. To resume:

1. Find the last `>>> START` line without a matching `<<< OK`. That's
   the failed step.
2. Read the error above it, fix it, and re-run just that step:
   `./01_bootstrap.sh step_<name>`
3. Then re-run `run_all` from the start — already-completed steps will
   short-circuit.

Common failure modes and what they look like:

- **`apt-get update` hangs on `archive.ubuntu.com`** — IPv6 + a transient
  network issue. Retry; if persistent, edit `/etc/apt/sources.list` to
  force `http://` and retry.
- **GitHub clone fails with `Permission denied (publickey)`** — the SSH
  key isn't registered yet. Look at the output of `step_git` for the
  public key and register it.
- **DCV install fails to find the deb** — version may have moved. Update
  `DCV_VERSION` in `03_install_dcv.sh` to the current one from
  https://download.nice-dcv.com/.
- **Metashape tarball 404** — Agisoft moved the version. Update
  `METASHAPE_VERSION` in `02_install_metashape.sh`. Check
  https://www.agisoft.com/downloads/installer/ for the current Linux
  build.

## Verification at each component

Validation isn't just one script at the end — verify as you go:

| After step | Verify with |
|---|---|
| `step_apt_update` | `cat /etc/os-release` and `uname -r` |
| `step_verify_gpu_stack` | `nvidia-smi`, `nvcc --version` |
| `step_python` | `python3.12 --version` |
| `step_uv` | `uv --version` |
| `step_clone_repo` | `ls -la /data/reef-sfm-mote-keys/.git` |
| `step_uv_sync` | `/data/reef-sfm-mote-keys/.venv/bin/python --version` |
| `step_jupyter_kernel` | `jupyter kernelspec list` lists the project |
| `step_qgis` | `qgis --version` |
| `step_dcv` | `systemctl is-active dcvserver` and connect from MacBook |
| `step_metashape_install` | `/opt/metashape-pro/metashape.sh --version` |

The final `05_validate.sh` runs all of these as one pass and exits
non-zero on any failure — use it as a gate before activating the trial.

## VS Code Remote-SSH workflow

This is the primary development environment from Chat 4 onward.

**Cost: $0.** This setup uses VS Code (free) plus the Microsoft
**Remote - SSH** extension (free, no GitHub account upgrade or Copilot
subscription required). Some Microsoft remote products are paid —
GitHub Codespaces in particular runs Microsoft's managed VMs and bills
GitHub for compute. That is a different product. What you want is
plain Remote-SSH, which connects to *your* EC2 instance over plain SSH
with your existing key. Nothing about this workflow involves a
subscription.

Setup on the MacBook side:

1. Install **VS Code** from `https://code.visualstudio.com/`.
2. Open VS Code, go to the Extensions panel (`⌘⇧X`), search for
   "Remote - SSH" (publisher: Microsoft, identifier
   `ms-vscode-remote.remote-ssh`), install.
3. Open the command palette (`⌘⇧P`) → **Remote-SSH: Connect to Host…**
   → pick `reef-ec2` (the alias from Chat 2's `~/.ssh/config`).
4. First connect installs the VS Code server under
   `~/.vscode-server/` on the EC2 instance — about 30 seconds,
   automatic, no input needed from you.
5. **File → Open Folder…** → `/data/reef-sfm-mote-keys`.
6. When you open a `.ipynb`, VS Code will prompt for a kernel. Pick
   **Python (reef-sfm-mote-keys)** — that's the kernel registered in
   `step_jupyter_kernel`. (You may need to install the **Python** and
   **Jupyter** extensions on first use; both are free Microsoft
   extensions, they'll appear in a prompt.)
7. The integrated terminal in VS Code runs on the EC2 instance. The
   file explorer shows EC2 files. Notebook execution happens against
   the remote kernel against the GPU.

For day-to-day work this is enough — you don't need a separate SSH
terminal alongside VS Code. The terminal panel inside VS Code is a
real shell on the remote instance.

### When to use Terminal.app instead

Two situations call for a regular `ssh reef-ec2` from Terminal.app:

1. **Parallel sessions during setup.** Terminal.app's tabs
   (`⌘T` for a new tab) give you multiple concurrent SSH sessions.
   No need for iTerm2. While `01_bootstrap.sh` runs in one tab you
   can monitor `htop` or tail `~/bootstrap-logs/bootstrap.log` in
   another.
2. **The overnight Chat 5 reconstruction.** See the tmux section
   below — you'll want a plain SSH session for `tmux attach`, not
   VS Code's integrated terminal.

### tmux for long-running jobs

Dense-cloud reconstruction in Chat 5 runs for 6–15 hours. If your
laptop sleeps, the wifi flickers, or you close the lid, the SSH
session dies — and any plain foreground process dies with it. tmux
keeps the process running on the EC2 instance regardless of what your
laptop is doing.

Three commands cover the workflow:

```bash
# Start a named session
tmux new -s reef

# Inside the session: run your long-running job
/opt/metashape-pro/python/bin/python3 scripts/process_easterndryrocks.py

# Detach (process keeps running)
# Press: Ctrl-b, then d

# Later, from any SSH session: reattach
tmux attach -t reef

# List sessions (if you forget the name)
tmux ls
```

Use tmux for any Chat 5 process expected to run more than ~10 minutes.
The bootstrap install steps are short enough not to need it.

## DCV from macOS

The macOS Amazon DCV client is already installed locally — connect with:

- **Server:** `52.5.136.119:8443`
- **User:** `ubuntu`
- **Password:** whatever you set with `sudo passwd ubuntu` after
  `03_install_dcv.sh` ran

If a future MacBook ever needs the client installed fresh, it's at
`https://download.nice-dcv.com/` (the download URL still uses the
pre-rename `nice-dcv` domain even for the renamed product).

Reserve DCV for Metashape GUI work (error reduction with Gradual
Selection in Chat 5, marker placement, manual quality review) and QGIS
annotation (Chat 7). Day-to-day editing, terminal, and notebooks
should stay in VS Code Remote-SSH — it's faster, lower-bandwidth, and
won't fight your laptop's display scaling.

## Pre-trial snapshot

After `05_validate.sh` passes and **before** running
`04_activate_trial.sh`, take a boot-volume snapshot. The 8-step stability
pattern from Chat 2 calls this "baseline configured." It lets you roll
back to a fully-configured-but-pre-trial state if the trial activation
binds to the wrong fingerprint or you need to rebuild for any other
reason.

Note that Chat 2 already produced a pre-Chat-3 baseline snapshot
(`snap-02b52e53f4ad274b7` for the boot volume,
`snap-0cd200217026bda4a` for the data volume). That's the
*pre-bootstrap* baseline. The snapshot taken here is the
*post-bootstrap, pre-trial* baseline — different point in time, used
for a different rollback scenario.

From your MacBook:

```bash
INSTANCE_ID=i-06fe7879a0e713c2f

# Boot volume snapshot
ROOT_VOL=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[].Instances[].BlockDeviceMappings[?DeviceName==`/dev/sda1`].Ebs.VolumeId' \
  --output text)

aws ec2 create-snapshot \
  --volume-id "$ROOT_VOL" \
  --description "reef-sfm-mote-keys post-bootstrap-pre-trial boot" \
  --tag-specifications 'ResourceType=snapshot,Tags=[
    {Key=Project,Value=reef-sfm-mote-keys},
    {Key=Stage,Value=post-bootstrap-pre-trial},
    {Key=Chat,Value=3}
  ]'

# Data volume snapshot (lightweight — should be near-empty at this point)
aws ec2 create-snapshot \
  --volume-id vol-08bcf0ab11df2c9ed \
  --description "reef-sfm-mote-keys post-bootstrap-pre-trial data" \
  --tag-specifications 'ResourceType=snapshot,Tags=[
    {Key=Project,Value=reef-sfm-mote-keys},
    {Key=Stage,Value=post-bootstrap-pre-trial},
    {Key=Chat,Value=3}
  ]'
```

Save the returned `SnapshotId` values to `docs/aws-resources.md` under
the Snapshots section.

## Why the trial activation is its own script

The single biggest risk to this project is wasting trial days on
infrastructure. By isolating activation in `04_activate_trial.sh` and
making it require typing `ACTIVATE` in capital letters, the script makes
it impossible to start the clock by accident — if you re-run `01_bootstrap.sh`
later (e.g. after rebuilding the box), the trial is not silently
re-activated.

When you do run it, the timeline you're committing to is roughly:

| Calendar | Chat | Work |
|---|---|---|
| Day 0 | — | Activate trial; take post-activation snapshot |
| Day 0–2 | Chat 4 | USGS data acquisition + intake QC |
| Day 2–10 | Chat 5 | Metashape processing (overnight dense recon) |
| Day 10–20 | Chat 6 | Provenance / QC / reconciliation layer |
| Day 20–25 | Chat 7 | QGIS annotation |
| Day 25–30 | — | Buffer for re-runs |
| Day 30 | — | Trial expires |

Chats 8 and 9 (Quarto writeup, outreach) can happen after the trial
expires — Metashape isn't needed for those.

## Costs while bootstrapping

`g6.4xlarge` runs at about $1.32/hour on-demand. A 45-minute bootstrap is
~$1. Stop the instance between work sessions to drop to EBS-only
(`~$10–30/month` for the boot + data volumes combined). The bootstrap
itself is cheap; the irreversible decision is activating the trial, not
spending the hour to set up.
