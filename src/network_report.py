import json
from datetime import datetime
from pathlib import Path

LOW_UPTIME_DAYS = 30
HIGH_PORT_UTIL_PCT = 80.0

def pct(used: int, total: int) -> float:
    return 0.0 if total == 0 else (used / total) * 100.0

def load_devices(data: dict):
    all_devices = []
    for loc in data.get("locations", []):
        site = loc.get("site")
        city = loc.get("city")
        contact = loc.get("contact")
        for dev in loc.get("devices", []):
            dev = dict(dev)  # copy
            dev["_site"] = site
            dev["_city"] = city
            dev["_contact"] = contact
            all_devices.append(dev)
    return all_devices

def format_line(cols, widths):
    return "  ".join(str(c).ljust(w) for c, w in zip(cols, widths))

def main():
    repo_root = Path(__file__).resolve().parents[1]
    data_path = repo_root / "data" / "network_devices.json"
    out_path = repo_root / "output" / "network_report.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(data_path.read_text(encoding="utf-8"))
    devices = load_devices(data)

    company = data.get("company", "Unknown")
    last_updated = data.get("last_updated", "")
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    offline = [d for d in devices if d.get("status") == "offline"]
    warning = [d for d in devices if d.get("status") == "warning"]
    low_uptime = [d for d in devices if int(d.get("uptime_days", 0)) < LOW_UPTIME_DAYS]

    # Per typ
    by_type = {}
    for d in devices:
        t = d.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    # VLANs
    vlan_set = set()
    for d in devices:
        for v in d.get("vlans", []) or []:
            vlan_set.add(int(v))

    # Switch-portar
    switch_devices = [d for d in devices if d.get("type") == "switch" and isinstance(d.get("ports"), dict)]
    total_used = sum(int(d["ports"].get("used", 0)) for d in switch_devices)
    total_ports = sum(int(d["ports"].get("total", 0)) for d in switch_devices)
    total_pct = pct(total_used, total_ports)

    # Per site: enheter + status
    site_stats = {}
    for d in devices:
        site = d["_site"]
        site_stats.setdefault(site, {"total": 0, "online": 0, "offline": 0, "warning": 0})
        site_stats[site]["total"] += 1
        site_stats[site][d.get("status", "online")] = site_stats[site].get(d.get("status", "online"), 0) + 1

    # Portanvändning per site
    site_port = {}
    for d in switch_devices:
        site = d["_site"]
        site_port.setdefault(site, {"switches": 0, "used": 0, "total": 0})
        site_port[site]["switches"] += 1
        site_port[site]["used"] += int(d["ports"].get("used", 0))
        site_port[site]["total"] += int(d["ports"].get("total", 0))

    high_port_switches = []
    for d in switch_devices:
        used = int(d["ports"].get("used", 0))
        tot = int(d["ports"].get("total", 0))
        p = pct(used, tot)
        if p > HIGH_PORT_UTIL_PCT:
            high_port_switches.append((d, p))

    # Executive Summary
    lines = []
    lines.append("=" * 80)
    lines.append(f"{'NÄTVERKSRAPPORT - ' + company:^80}")
    lines.append("=" * 80)
    lines.append(f"Rapportdatum: {report_date}")
    lines.append(f"Datauppdatering: {last_updated}")
    lines.append("")
    lines.append("EXECUTIVE SUMMARY")
    lines.append("-" * 80)
    lines.append(f"KRITISKT: {len(offline)} enheter offline")
    lines.append(f"VARNING:  {len(warning)} enheter med warning-status")
    lines.append(f"OBS:     {len(low_uptime)} enheter med låg uptime (<{LOW_UPTIME_DAYS} dagar)")
    lines.append(f"OBS:     {len(high_port_switches)} switchar över {HIGH_PORT_UTIL_PCT:.0f}% portanvändning")
    lines.append("")

    # Problem-enheter
    def add_device_list(title, devs):
        lines.append(title)
        lines.append("-" * 80)
        if not devs:
            lines.append("Inga.")
            lines.append("")
            return
        widths = [16, 15, 13, 18, 10]
        lines.append(format_line(["Hostname", "IP", "Typ", "Site", "Uptime"], widths))
        lines.append(format_line(["-"*16, "-"*15, "-"*13, "-"*18, "-"*10], widths))
        for d in devs:
            lines.append(format_line([
                d.get("hostname",""),
                d.get("ip_address",""),
                d.get("type",""),
                d["_site"],
                f"{int(d.get('uptime_days',0))} d"
            ], widths))
        lines.append("")

    add_device_list("ENHETER MED STATUS: OFFLINE", offline)
    add_device_list("ENHETER MED STATUS: WARNING", warning)

    # Låg uptime
    lines.append(f"ENHETER MED LÅG UPTIME (<{LOW_UPTIME_DAYS} dagar)")
    lines.append("-" * 80)
    if low_uptime:
        low_uptime_sorted = sorted(low_uptime, key=lambda d: int(d.get("uptime_days", 0)))
        for d in low_uptime_sorted:
            lines.append(f"{d.get('hostname',''):16} {int(d.get('uptime_days',0)):>4} dagar  {d.get('status',''):>7}  {d['_site']}")
    else:
        lines.append("Inga.")
    lines.append("")

    # Statistik per typ
    lines.append("STATISTIK PER ENHETSTYP")
    lines.append("-" * 80)
    total = len(devices)
    for t in sorted(by_type.keys()):
        lines.append(f"{t:15}: {by_type[t]:>3} st")
    lines.append("-" * 40)
    lines.append(f"{'TOTALT':15}: {total:>3} enheter")
    lines.append("")

    # Portanvändning
    lines.append("PORTANVÄNDNING – SWITCHAR")
    lines.append("-" * 80)
    lines.append(f"Totalt: {total_used}/{total_ports} portar används ({total_pct:.1f}%)")
    lines.append("")
    lines.append("Per site:")
    for site in sorted(site_port.keys()):
        v = site_port[site]
        p = pct(v["used"], v["total"])
        lines.append(f"  {site:18}  switchar: {v['switches']:>2}  {v['used']:>3}/{v['total']:<3}  {p:>5.1f}%")
    lines.append("")

    lines.append(f"SWITCHAR ÖVER {HIGH_PORT_UTIL_PCT:.0f}% PORTANVÄNDNING")
    lines.append("-" * 80)
    if high_port_switches:
        for d, p in sorted(high_port_switches, key=lambda x: x[1], reverse=True):
            used = int(d["ports"].get("used", 0))
            tot = int(d["ports"].get("total", 0))
            lines.append(f"{d.get('hostname',''):16} {used:>2}/{tot:<2}  {p:>5.1f}%  {d['_site']}")
    else:
        lines.append("Inga.")
    lines.append("")

    # VLAN-översikt
    lines.append("VLAN-ÖVERSIKT")
    lines.append("-" * 80)
    vlans_sorted = sorted(vlan_set)
    lines.append(f"Totalt antal unika VLAN: {len(vlans_sorted)}")
    lines.append("VLANs: " + ", ".join(str(v) for v in vlans_sorted))
    lines.append("")

    # Site-statistik
    lines.append("STATISTIK PER SITE")
    lines.append("-" * 80)
    for site in sorted(site_stats.keys()):
        v = site_stats[site]
        lines.append(f"{site}: {v['total']} (online: {v.get('online',0)}, offline: {v.get('offline',0)}, warning: {v.get('warning',0)})")
    lines.append("")
    lines.append("=" * 80)
    lines.append("RAPPORT SLUT")
    lines.append("=" * 80)

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK: Skapade {out_path}")

if __name__ == "__main__":
    main()
