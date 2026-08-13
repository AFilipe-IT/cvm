"""
config_assessment/fetch/benchmark_fetcher.py
--------------------------------------------
Automatic discovery and download of security benchmarks for a CASPAR service.

`caspar plugin add --source benchmark.pdf` already installs a plugin from a local
CIS PDF or DISA STIG XCCDF file. This module supplies the *fetch* half: given a
service name (e.g. "nginx"), find the right public benchmark and download it,
producing a file that `plugin add` can consume unchanged.

Investigation (2026-07-01) established the only reliable per-service source is
stigviewer.com, which exposes structured STIG JSON at

    https://www.stigviewer.com/stigs/<slug>/export/json

ComplianceAsCode/content (GitHub) only ships OS-level content (RHEL, Ubuntu, …),
and public.cyber.mil is a JS-rendered SPA with no static links — neither works
for individual services. See config_assessment/fetch/catalog.json for the
service→slug map.

UPDATE (2026-08-13): **stigviewer.com now requires authentication.** Every slug
returns HTTP 401 — verified against canonical_ubuntu_2204_lts, f5_nginx and
kubernetes — so all catalogued stigviewer sources are unreachable. The failure
is reported explicitly (see `_SOURCE_UNAVAILABLE`) rather than as a generic
network error, because "the source closed" and "this target does not exist" call
for different responses from the user.

For OS-level targets the replacement is the SCAP Security Guide
(ComplianceAsCode releases), reached through source type "ssg" and implemented
in ssg_source.py. It is public, needs no authentication, and carries the
expected value structurally — see that module for why that matters. Per-service
benchmarks (nginx, redis, …) have no confirmed replacement yet and must be
installed from a local file via `plugin add --source`.

The fetcher converts the JSON to a DISA-style XCCDF 1.1 XML file. That file goes
straight through the existing XCCDF branch of `plugin add`
(config_assessment.build.benchmark_extractor.XCCDFExtractor), so no new parser is
needed. Network access uses only the stdlib (urllib) — no third-party deps, in
keeping with the rest of CASPAR.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

# XCCDF 1.1 — the namespace XCCDFExtractor defaults to and DISA STIGs use.
_XCCDF_NS = "http://checklists.nist.gov/xccdf/1.1"
_STIGVIEWER_EXPORT = "https://www.stigviewer.com/stigs/{slug}/export/json"
_USER_AGENT = "caspar/0.1 (+benchmark-fetch)"
_TIMEOUT = 30

# Raised in place of a bare "HTTP 401" so the user is not left guessing whether
# they typed the wrong service name.
_SOURCE_UNAVAILABLE = (
    "stigviewer.com now requires authentication (verified 2026-08-13) and no "
    "longer serves '{slug}' — or any other slug — anonymously. For OS targets "
    "use an 'ssg' source (SCAP Security Guide); for a single service, download "
    "the STIG or CIS PDF manually and run: plugin add --source <file>")


class FetchError(RuntimeError):
    """A benchmark could not be discovered or downloaded."""


class BenchmarkFetcher:
    """Discover and download public benchmarks for CASPAR services.

    Parameters
    ----------
    catalog_path:
        Path to catalog.json. Defaults to the one shipped beside this module.
    """

    def __init__(self, catalog_path: str | Path | None = None) -> None:
        self.catalog_path = Path(catalog_path) if catalog_path else (
            Path(__file__).with_name("catalog.json"))
        self._catalog = self._load_catalog(self.catalog_path)

    # ── public API ────────────────────────────────────────────────────
    def list_available(self) -> list[dict]:
        """Return the catalogued services with their sources, sorted by name."""
        out: list[dict] = []
        for service, entry in sorted(self._catalog.items()):
            out.append({
                "service": service,
                "service_name": entry.get("service_name", service),
                "sources": [
                    {"type": s.get("type"), "title": s.get("title", ""),
                     "format": s.get("format", "")}
                    for s in entry.get("sources", [])
                ],
            })
        return out

    def fetch(self, service: str, dest_dir: str | Path) -> str:
        """Download the benchmark for `service` into `dest_dir`.

        Returns the path to the written file (XCCDF XML). Tries each catalogued
        source in order; raises FetchError if the service is unknown or every
        source fails.
        """
        entry = self._catalog.get(service.lower())
        if entry is None:
            known = ", ".join(sorted(self._catalog)) or "(none)"
            raise FetchError(
                f"Unknown service '{service}'. Available: {known}")

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)

        errors: list[str] = []
        for source in entry.get("sources", []):
            stype = source.get("type")
            try:
                if stype == "ssg":
                    return self._fetch_ssg(source, dest, service.lower())
                if stype == "stigviewer":
                    return self._fetch_stigviewer(source, dest, service.lower())
                if stype == "github_release":
                    return self._fetch_github_release(source, dest)
                if stype == "disa_stig":
                    return self._fetch_disa_stig(source, dest)
                errors.append(f"{stype}: unsupported source type")
            except FetchError as exc:
                errors.append(f"{stype}: {exc}")

        raise FetchError(
            f"All sources failed for '{service}': " + " | ".join(errors))

    # ── source implementations ────────────────────────────────────────
    def _fetch_ssg(self, source: dict, dest_dir: Path, service: str) -> str:
        """Download a SCAP Security Guide release and emit it as XCCDF.

        Unlike the STIG path, the rules carry a resolved (identifier, value)
        pair for roughly half the benchmark, recovered from the SSG template
        blocks without an LLM. That pair is written into the <fixtext> so the
        existing XCCDF extractor sees an unambiguous instruction, and is also
        emitted as attributes so a later build can tell derived values from
        inferred ones. See ssg_source.py.
        """
        from config_assessment.fetch.ssg_source import (
            SSGArchive, SSGError, ssg_download_url)

        product = source.get("product")
        if not product:
            raise FetchError("ssg source needs a 'product' (e.g. 'ubuntu2204')")

        version = source.get("version", "")
        level = source.get("level", "l1_server")
        url = source.get("url") or ssg_download_url(
            version or None) if version else ssg_download_url()

        archive = dest_dir / f"scap-security-guide-{version or 'pinned'}.tar.bz2"
        if not archive.exists():
            archive.write_bytes(_http_get(url, binary=True))

        try:
            rules = SSGArchive(archive).resolve(product, level=level)
        except SSGError as exc:
            raise FetchError(f"SSG archive unusable: {exc}") from exc
        if not rules:
            raise FetchError(
                f"SSG product '{product}' yielded no rules at level '{level}'")

        title = source.get("title") or f"{service} CIS Benchmark ({product})"
        xml = _ssg_rules_to_xccdf(title, version, rules)
        out = dest_dir / f"SSG_{product}_{level}.xml"
        out.write_text(xml, encoding="utf-8")
        return str(out)

    def _fetch_stigviewer(self, source: dict, dest_dir: Path, service: str) -> str:
        """Download the stigviewer STIG JSON and write it as XCCDF XML.

        `service` is the canonical CASPAR service key; it is prepended to the
        XCCDF <title> so plugin_add's extract_service_name() names the plugin
        after the service (e.g. "nginx") rather than the vendor in the STIG
        title (e.g. "F5 NGINX ..." → "f5").
        """
        slug = source.get("slug")
        if not slug:
            raise FetchError("stigviewer source has no 'slug'")

        url = _STIGVIEWER_EXPORT.format(slug=slug)
        try:
            raw = _http_get(url)
        except FetchError as exc:
            # Distinguish "the source closed" from "this target is missing":
            # the first is nothing the user can fix by picking another name.
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                raise FetchError(_SOURCE_UNAVAILABLE.format(slug=slug)) from exc
            raise
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FetchError(f"stigviewer returned non-JSON for '{slug}': {exc}")

        stig = data.get("stig", data)
        groups = stig.get("groups") or []
        if not groups:
            raise FetchError(f"stigviewer STIG '{slug}' has no rules")

        stig_title = stig.get("title") or source.get("title") or slug
        # Lead the title with the canonical service so target_id derivation is
        # correct, but keep the real STIG title for readability/reporting.
        title = (stig_title if stig_title.lower().startswith(service.lower())
                 else f"{service} {stig_title}")
        version = _clean_version_label(stig.get("version") or "")
        xml = _stig_json_to_xccdf(title, version, groups)

        # Name the file so plugin_add's V<n>R<n> regex and service detection fire.
        safe = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_")
        vpart = f"_{version}" if version else ""
        out = dest_dir / f"U_{safe}{vpart}_STIG.xml"
        out.write_text(xml, encoding="utf-8")
        return str(out)

    def _fetch_github_release(self, source: dict, dest_dir: Path) -> str:
        """Download a matching asset from a GitHub release.

        Kept for catalog extensibility (e.g. ComplianceAsCode). No CASPAR
        service currently uses it — investigation found only OS-level content
        there — so it is exercised only when a catalog entry opts in.
        """
        repo = source.get("repo")
        pattern = source.get("asset_pattern")
        if not repo or not pattern:
            raise FetchError("github_release source needs 'repo' and 'asset_pattern'")

        tag = source.get("tag", "latest")
        api = (f"https://api.github.com/repos/{repo}/releases/latest"
               if tag == "latest"
               else f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
        rel = json.loads(_http_get(api))
        rx = re.compile(pattern, re.IGNORECASE)
        for asset in rel.get("assets", []):
            if rx.search(asset.get("name", "")):
                blob = _http_get(asset["browser_download_url"], binary=True)
                out = dest_dir / asset["name"]
                out.write_bytes(blob)
                return str(out)
        raise FetchError(
            f"no asset matching /{pattern}/ in {repo}@{tag}")

    def _fetch_disa_stig(self, source: dict, dest_dir: Path) -> str:
        """Download a STIG zip from a direct DoD URL declared in the catalog.

        DISA has no confirmed JSON API and its filenames are unpredictable, so
        this only works when the catalog carries a verified direct 'url'.
        """
        url = source.get("url")
        if not url:
            raise FetchError(
                "disa_stig source needs a verified direct 'url' "
                "(no public DISA API exists)")
        blob = _http_get(url, binary=True)
        out = dest_dir / (source.get("filename") or url.rsplit("/", 1)[-1])
        out.write_bytes(blob)
        return str(out)

    # ── internals ─────────────────────────────────────────────────────
    @staticmethod
    def _load_catalog(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FetchError(f"catalog not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise FetchError(f"catalog is not valid JSON: {exc}") from exc
        # Drop documentation keys (leading underscore).
        return {k: v for k, v in data.items() if not k.startswith("_")}


# ── module-level helpers ──────────────────────────────────────────────

def _http_get(url: str, binary: bool = False) -> bytes | str:
    """GET a URL with the stdlib. Returns text (utf-8) or bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error for {url}: {exc.reason}") from exc
    return body if binary else body.decode("utf-8", "replace")


def _clean_version_label(version: str) -> str:
    """Normalise a stigviewer version like 'V2R2' → 'V2R2' (strip spaces)."""
    m = re.search(r"V\s*(\d+)\s*R\s*(\d+)", version, re.IGNORECASE)
    return f"V{m.group(1)}R{m.group(2)}" if m else re.sub(r"\s+", "", version)


def _ssg_rules_to_xccdf(title: str, version: str, rules: list) -> str:
    """Render resolved SSG rules as XCCDF 1.1 for the existing extractor.

    Two things travel beyond what a STIG carries, both as attributes the
    extractor ignores but a later build step can read:

      cvm:dimension     which of the v2 dimensions the rule observes
      cvm:deterministic "true" when identifier and value came from the SSG
                        template rather than from an LLM reading prose

    Keeping them in the XML means the provenance of every rule survives the
    handoff to `plugin add`, instead of being reconstructed by guesswork.
    """
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<Benchmark xmlns="{_XCCDF_NS}" id="CVM_ssg_fetch">',
        f"  <title>{escape(title)}</title>",
    ]
    if version:
        parts.append(f"  <version>{escape(version)}</version>")

    q = {chr(34): "&quot;"}
    for r in rules:
        rid = f"{r.rule_name}" if r.rule_name else r.control_id
        parts.append(
            f'  <Rule id="{escape(rid, q)}" severity="{escape(r.severity)}" '
            f'cvm:dimension="{escape(r.dimension, q)}" '
            f'cvm:deterministic="{"true" if r.deterministic else "false"}">')
        ctitle = f"{r.control_id} {r.control_title}".strip()
        parts.append(f"    <title>{escape(ctitle)}</title>")
        parts.append(f"    <fixtext>{escape(r.fixtext)}</fixtext>")
        parts.append('    <check system="C-SSG">')
        # The rationale is what the LLM needs to justify CCSS metrics; the CCE
        # is ground truth for score validation, so both go in the check body.
        check = r.rationale or r.description
        if r.cce:
            check = f"{check}\n\nCCE: {r.cce}".strip()
        parts.append(f"      <check-content>{escape(check)}</check-content>")
        parts.append("    </check>")
        parts.append("  </Rule>")

    parts.append("</Benchmark>")
    xml = "\n".join(parts)

    # The cvm: attributes need a declared prefix or ElementTree rejects the
    # document; declare it on the root rather than per-rule.
    xml = xml.replace(
        f'<Benchmark xmlns="{_XCCDF_NS}"',
        f'<Benchmark xmlns="{_XCCDF_NS}" xmlns:cvm="https://github.com/AFilipe-IT/cvm"',
        1)
    ET.fromstring(xml)
    return xml


def _stig_json_to_xccdf(title: str, version: str, groups: list[dict]) -> str:
    """Convert stigviewer 'groups' into a minimal XCCDF 1.1 document.

    Emits exactly the elements XCCDFExtractor reads: a top-level <title>, and one
    <Rule severity=...> per group carrying <title>, <fixtext> and a nested
    <check>/<check-content>. Text is XML-escaped; the rest of the STIG metadata
    is intentionally omitted (the extractor does not use it).
    """
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<Benchmark xmlns="{_XCCDF_NS}" id="CASPAR_fetch">',
        f"  <title>{escape(title)}</title>",
    ]
    if version:
        parts.append(f"  <version>{escape(version)}</version>")

    for g in groups:
        rule_id = g.get("ruleId") or g.get("ruleVersion") or g.get("groupId") or ""
        severity = (g.get("ruleSeverity") or "medium").lower()
        rtitle = g.get("ruleTitle") or g.get("title") or ""
        fixtext = g.get("ruleFixText") or ""
        check = g.get("ruleCheckContent") or ""
        parts.append(
            f'  <Rule id="{escape(rule_id, {chr(34): "&quot;"})}" '
            f'severity="{escape(severity)}">')
        parts.append(f"    <title>{escape(rtitle)}</title>")
        parts.append(f"    <fixtext>{escape(fixtext)}</fixtext>")
        parts.append("    <check system=\"C-STIG\">")
        parts.append(f"      <check-content>{escape(check)}</check-content>")
        parts.append("    </check>")
        parts.append("  </Rule>")

    parts.append("</Benchmark>")
    xml = "\n".join(parts)

    # Fail loudly here rather than deep inside plugin_add if escaping missed a
    # control character; the extractor parses with ElementTree too.
    ET.fromstring(xml)
    return xml
