# Project plan: reef-sfm-mote-keys

This document captures the chat prompts that drive each build layer of the
project, so that the work is reproducible from the prompts themselves.

The project is built in nine chats. Only Chat 1 is captured here at the time
of repository creation — subsequent chats will be appended as they are run.

---

## Chat 1 — Repository scaffold and project bootstrap

> I'm starting a marine science portfolio project: reproducing the Toth et al. 2025
> Florida Keys coral restoration SfM photogrammetry pipeline (USGS data releases
> P1WHKTRD and P13HMEON) on the EasternDryRocks site, with an enterprise data
> management layer (provenance capture, QC against published targets, metric
> reconciliation) that the original USGS/Mote workflow does not include.
>
> Audience for the finished project: Mote Marine Laboratory's restoration program
> (noting that Ian Combs, their SfM lead, recently departed for an Auckland PhD,
> which may create a capability gap), the USGS SPCMSC team (Toth, Johnson), and
> the broader Florida Keys restoration community.
>
> My background: 15 years in clinical research informatics (NIH/NHLBI plus
> industry), comfortable with Python, Jupyter, Git, biomedical data engineering,
> data governance. Transitioning into marine science at my existing technical
> level. NOT a beginner — frame the work at senior-technical level.
>
> Architecture:
> - Local: MacBook with A18 Pro chip running macOS (8 GB RAM). Used for editing,
>   Git, Quarto authoring, Terminal SSH into the EC2 instance, RDP/NICE DCV when
>   Metashape GUI needed.
> - Cloud (set up in Chat 2): single stable AWS EC2 g6.4xlarge instance with
>   NVIDIA L4 GPU, running Windows for best Metashape support.
>
> Software approach: Agisoft Metashape Professional (30-day trial first, then
> node-locked purchase if the trial validates). All Python work uv-managed. Site
> publishes as a Quarto page at velezf.github.io/projects/.
>
> This chat's scope: Layer 1 — repository scaffold ONLY. No AWS, no Metashape, no
> data. Just the empty skeleton.
>
> What I need from this chat:
> 1. Create the GitHub repo locally on my MacBook (~/code/reef-sfm-mote-keys/)
> 2. Directory structure following my three-stage workflow document (see project
>    files): data/raw, data/processed, notebooks, scripts, figures, docs,
>    plus Python package source folder for the provenance/QC code
> 3. .gitignore matching the conventions in my workflow document
> 4. pyproject.toml (uv-managed) with initial dependencies (jupyter, ipykernel,
>    pandas, numpy, matplotlib, pillow, pyyaml — keep it minimal, we'll add as
>    needed)
> 5. .python-version
> 6. references.bib prepopulated with the relevant citations: Combs et al. 2021
>    (PLOS ONE), Toth et al. 2025 (Scientific Reports), Johnson et al. 2025
>    (USGS data release P1WHKTRD), Toth et al. 2025a (USGS data release
>    P13HMEON), the PIFSC SOP (Torres-Pulliza 2024) "parameter reference, not methodological basis,
>    Schönberger SfM technical refs, Bayley & Mogg 2020, Burns et al. 2015
> 7. Initial README.md framed for the senior-technical Mote/USGS audience — not
>    a beginner project, not an apology for being new to marine science
> 8. project-plan.md at the repo root containing all nine chat prompts for this
>    project so I can reference them later
> 9. Initial commit, push to github.com/velezf/reef-sfm-mote-keys
>
> Important framing notes:
> - The README must NOT say "this is my first marine science project" or
>   similar apologetic framing. It should describe the work as what it is: a
>   reproducible reimplementation of the USGS/Mote restoration SfM pipeline
>   with added enterprise data management instrumentation.
> - The PIFSC SOP I uploaded earlier in the project is a REFERENCE for
>   parameter values, not the SOP this project follows. The methodological
>   basis is Combs 2021 + Toth 2025, which use Metashape similarly but at
>   different scales and for different scientific questions.
> - All paths and commands should assume my local environment is macOS, not
>   Linux or Windows.
>
> Project files attached: my three-stage workflow PDF, NOAA PIFSC SOP PDF.
>
> Build the scaffold. Push to GitHub. Don't add anything beyond Layer 1.

---

## Chat 2 — AWS EC2 setup

*To be added when run.*

---

## Chat 3 — Data fetch from USGS releases

*To be added when run.*

---

## Chat 4 — Metashape pipeline configuration

*To be added when run.*

---

## Chat 5 — Provenance capture layer

*To be added when run.*

---

## Chat 6 — QC against published targets

*To be added when run.*

---

## Chat 7 — Carbonate budget and complexity metric reconciliation

*To be added when run.*

---

## Chat 8 — Figures and notebook polish

*To be added when run.*

---

## Chat 9 — Stage 2 migration to Quarto site

*To be added when run.*
