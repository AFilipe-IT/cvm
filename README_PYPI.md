# CVM — Configuration Vulnerability Meter

**Quantitative, reproducible scoring of the risk a system's configuration
introduces**, based on CCSS (NISTIR 7502). CASPAR is the reference
implementation.

Configuration scanners tend to answer *pass or fail against a checklist*.
Vulnerability scanners answer *which known CVEs apply*. CVM sits between them:
it scores how much risk a configuration actually introduces, on a comparable
scale, and detects **attack chains** — combinations of individually moderate
weaknesses that together are severe.

```bash
pip install cvm-caspar
caspar init                      # restore the built-in knowledge base
caspar demo                      # write example configurations
caspar scan caspar-demo/apache-vulnerable.conf
```

`caspar init` is required once and only for pip installs: it restores the same
canonical knowledge base that the Docker image and the repository installer
ship, so scores are comparable across all three.

## What it assesses

Twelve targets out of the box — Apache HTTP Server, nginx, SSH, MySQL,
PostgreSQL, Redis, Tomcat, Docker, Dockerfile, Kubernetes, Ubuntu and Azure IaC
— from knowledge derived from public CIS Benchmarks and DISA STIGs, with the
provenance of every rule recorded.

```bash
caspar scan /etc/apache2/                # a directory
caspar scan --live apache2               # the installed service
caspar scan docker://httpd:2.4           # an image
caspar scan k8s-manifest.yaml            # IaC
```

Every scan ends with a `reproducible: … kb sha256:…` line. Scores are only
comparable between identical knowledge bases, so that hash is what makes a
result checkable by someone else.

## The web console

```bash
pip install "cvm-caspar[api]"
caspar serve                             # http://127.0.0.1:2027
```

Both consoles ship built inside the package — no Node toolchain needed. The v2
console answers at `/app`, v1 at `/v1/app`, and the REST API with its Swagger UI
at `/api/v1` and `/docs`.

## Extras

| Extra | For |
|---|---|
| *(none)* | the CLI: scan, report, diff, explain |
| `[api]` | `caspar serve` — REST API + both web consoles |
| `[publish]` | pushing results to an external endpoint |
| `[dev]` | running the test suite |

## Build-time knowledge extraction

Adding a target from a benchmark PDF uses an LLM with RAG and is a build-time
operation, separate from scanning:

```bash
caspar plugin add --source benchmark.pdf --target nginx
caspar build --provider anthropic        # or ollama (local), openai
```

Hosted providers read `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` **from the
environment only** — never a command-line flag or an API field, which would put
the key in shell history or in a stored job record. Scanning itself uses no LLM
and is fully deterministic.

## Scope

Single instance, self-hosted. No multi-tenancy, no user accounts, no hosted
service. CVM runs where the systems it assesses are, which is also why it needs
no agents and no third-party SSH credentials.

## Provenance

The knowledge base derives from public CIS Benchmarks and DISA STIGs, with
provenance declared per target, plus the SCAP Security Guide
(ComplianceAsCode/content) pinned by version with its SHA recorded in the
reproducibility manifest.

Source, documentation and the Docker images:
**https://github.com/AFilipe-IT/cvm**
