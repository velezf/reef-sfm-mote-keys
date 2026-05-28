# Downloads & tool acquisition — one place for everything

Every external thing the project needs to download or install, with the
**correct current** source for each and an explicit note where a name or URL is
deprecated. Organized by *where it installs*. Verified 2026-05-28.

The deprecation traps worth knowing up front:

- **"NICE DCV" is now "Amazon DCV."** Same product, renamed. The `nice-dcv-*`
  package names and `download.nice-dcv.com` URLs still resolve for now, but new
  material uses Amazon DCV / `d1uj6qtbmh3dt5.cloudfront.net`. Don't mix versions.
- **Claude Code no longer needs Node/npm.** The npm package
  (`@anthropic-ai/claude-code`) still works, but the **native installer is the
  recommended path and bundles its own runtime** — no Node 18+ prerequisite.
  Your Chat 3 doc predates this; see the Claude Code note below.
- **The Logan error-reduction repo is on USGS GitLab, not GitHub.** And the
  workflow-relevant code is the **v2.0** tag, not `legacy_scripts/`.
- **Metashape 2.x** — make sure the tarball is the 2.x line (Python API used by
  the pipeline is Pro-only and the 1.x API differs).

---

## On the MacBook (local)

| Tool | How to get it | Notes |
|---|---|---|
| Homebrew | `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` | Prereq for the rest. |
| AWS CLI v2 | `brew install awscli` | Chat 2 infra scripts need this. |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Python env manager; all Python work is uv-managed. |
| Git | `brew install git` | Usually already present. |
| iTerm2 | `brew install --cask iterm2` | Recommended over Terminal.app for tabbed long-running SSH. |
| Amazon DCV client (macOS) | https://www.amazondcv.com → Clients | For Metashape GUI (Chat 5) and QGIS (Chat 7) over DCV. **Was "NICE DCV client."** |
| Cursor *or* VS Code | https://cursor.com or https://code.visualstudio.com | Remote-SSH dev. Either works. |
| Remote-SSH extension | Inside Cursor/VS Code extensions panel | Installs the remote server on the EC2 box on first connect. |
| Quarto CLI | `brew install --cask quarto` | Chat 8 writeup. |
| Claude Code (optional, local) | `curl -fsSL https://claude.ai/install.sh \| bash` | Native installer, no Node needed. See Claude Code note. |

---

## On the EC2 instance (Ubuntu 24.04, `ubuntu` user)

### Already on the AWS Deep Learning AMI (verify, don't reinstall)

The DLAMI (Ubuntu 24.04, OSS NVIDIA driver) you pinned in Chat 2 ships these —
confirm with the validation commands rather than reinstalling:

| Component | Verify with | Expected |
|---|---|---|
| NVIDIA driver | `nvidia-smi` | L4 listed, driver loaded |
| CUDA toolkit | `nvcc --version` | CUDA 12.x |

### apt packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  build-essential git curl wget unzip p7zip-full htop tmux \
  python3.12 python3.12-venv python3.12-dev \
  qgis qgis-plugin-grass \
  octave            # for Hatcher color-correction script (ESM Step 9), if adopted
```

`octave` is the free MATLAB substitute for the Hatcher script — only needed if
you adopt color correction (ADR-0010 marks it OPTIONAL; evaluate on a subset).

### uv (Python manager, on the instance too)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Amazon DCV server (Ubuntu)

The DLAMI may include it; check `dcv version` first. If absent:

```bash
# Amazon DCV server — was "NICE DCV server". Current download portal:
#   https://www.amazondcv.com  (Server → Linux → Ubuntu 24.04)
# Also install a lightweight desktop for DCV to display:
sudo apt install -y xfce4 xfce4-goodies
```

Pull the exact server tarball/deb from the portal (version-pinned) rather than a
hard-coded URL here, because the build number changes; the portal is the stable
entry point. Set it up under systemd per your Chat 3 doc.

### Agisoft Metashape Professional 2.x

```bash
# Download the 2.x Linux tarball from Agisoft (account/trial required):
#   https://www.agisoft.com/downloads/installer/
#   file: metashape-pro_2_x_x_amd64.tar.gz   (confirm 2.x, not 1.x)
cd /opt && sudo tar -xzf ~/metashape-pro_2_*_amd64.tar.gz
sudo mv metashape-pro /opt/metashape-pro
sudo ln -s /opt/metashape-pro/metashape.sh /usr/local/bin/metashape.sh
```

The 30-day Pro trial activates at the **end** of Chat 3 bootstrap, not before.
The Python API used by `run_pipeline.py` is Pro-only and the trial exposes it.

### USGS-released tools (ADR-0010)

All four are USGS public-domain software releases. Clone into the repo's
`vendor/` on the data volume. **Note the host is `code.usgs.gov` (GitLab).**

```bash
cd ~/code/reef-sfm-mote-keys/vendor

# 1. Logan error-reduction — REQUIRED (ADR-0010). Use the v2.0 line, not legacy.
git clone https://code.usgs.gov/pcmsc/AgisoftAlignmentErrorReduction.git
#   DOI: 10.5066/P9DGS5B9
#   After clone: read DISCLAIMER (public domain, no usage restriction),
#   confirm the threshold-mode args, then `uv add --editable` or PYTHONPATH it.

# 2. Jenkins Alignment Helper — REQUIRED if Chat 6 compares to published DSMs
git clone https://code.usgs.gov/spcmsc/metashape-alignment-helper.git
#   DOI: 10.5066/P9YN4KDX

# 3. Jenkins Export Helper — OPTIONAL (can be replicated in plain Python)
#   DOI: 10.5066/P1C7KKAP
#   Resolve the repo URL from the DOI landing page (spcmsc group on code.usgs.gov)

# 4. Hatcher color correction — OPTIONAL (Octave). NOT a code.usgs.gov repo —
#   the script ships INSIDE the data release's orthoimagery metadata:
#   https://doi.org/10.5066/P93RIIG9  → file OrthoImage_Color_Correction_Procedure.m
```

If `code.usgs.gov` is blocked by your instance's egress rules, add it to the
allowlist or clone on the MacBook and `scp` up — the repos are small.

### Claude Code on the EC2 instance (see discussion below)

```bash
# Native installer — no Node needed, auto-updates, recommended path:
curl -fsSL https://claude.ai/install.sh | bash
# new shell, then:
claude doctor      # verifies install, auth, PATH
# Auth via the browser prompt on first `claude` run. If ANTHROPIC_API_KEY is set
# in the env, Claude Code uses the API (metered) instead of your subscription —
# unset it first if you want subscription auth.
```

---

## Data downloads (not tools)

| Dataset | DOI / source | What | Chat |
|---|---|---|---|
| USGS P1WHKTRD | https://doi.org/10.5066/P1WHKTRD via IDS viewer | EDR raw imagery (TIFF), CC0 | 4 (done) |
| USGS P13HMEON | https://doi.org/10.5066/P13HMEON | Companion products: topographic complexity (reconciliation targets), percent cover | 4 / 6 |

Both are already acquired per Chat 4b; listed here for completeness.

---

## R tooling for Chat 6 (heads-up, not Chat 5)

The longitudinal doc flags that reconciliation needs the **MultiscaleDTM** R
package (Ilich et al. 2023), which the current `pyproject.toml` does not cover.
Chat 6 will add either `rpy2` or an R-subprocess path. Not needed for Chat 5, but
noting it here so the full download picture is in one place:

```bash
# Chat 6, on the EC2 instance:
sudo apt install -y r-base
R -e 'install.packages("MultiscaleDTM", repos="https://cloud.r-project.org")'
# plus rpy2 if going the Python-binding route:  uv add rpy2
```

---

## Quick verification after a fresh EC2 bootstrap

```bash
nvidia-smi && nvcc --version           # GPU + CUDA
metashape.sh --version                 # Metashape 2.x
python3 -c "import Metashape; print(Metashape.app.version)"   # Pro API
uv --version && qgis --version         # env + GIS
dcv version                            # Amazon DCV server
claude --version                       # Claude Code (if installed)
ls vendor/                             # USGS tools cloned
```
