"""Screenshot every real page across a fixed set of device viewports.

Drives the app through Playwright exactly like a human would (real login form,
real PIN keypad clicks, real radio-button route selection), no session/cookie
shortcuts, so auth, redirects, and JS all behave as they would on the actual
device. Multi-step flows (guest scan-to-quantity, admin scan-to-quantity, the
trend chart modal) are completed by clicking through the real UI so the
screenshot shows real rendered content, not an error/fallback state.

Usage (from repo root, dev server already running):
    .venv/bin/python3 -m scripts.device_screenshots.capture

Output: scripts/device_screenshots/output/<device>/<page>.png, plus an
index.html gallery comparing every page across every device side by side.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

OUTPUT_DIR = Path(__file__).parent / "output"


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    label: str
    width: int
    height: int
    device_scale_factor: float
    is_mobile: bool
    has_touch: bool
    user_agent: str | None = None


IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"

DEVICES: dict[str, DeviceProfile] = {
    "laptop": DeviceProfile("Laptop (1440x900)", 1440, 900, 1, False, False),
    "large_tv": DeviceProfile("Large TV (1920x1080)", 1920, 1080, 1, False, False),
    "touchscreen_10in": DeviceProfile("10.1in Touchscreen (1280x800)", 1280, 800, 1, False, True),
    "iphone_portrait": DeviceProfile("iPhone (portrait, 393x852)", 393, 852, 3, True, True, IPHONE_UA),
    "iphone_landscape": DeviceProfile("iPhone (landscape, 852x393)", 852, 393, 3, True, True, IPHONE_UA),
}


@dataclass(frozen=True, slots=True)
class PageSpec:
    key: str
    path: str
    label: str
    admin: bool = False


def build_pages(agency_id: int, location_id: int, item_id: int, article_id: str) -> list[PageSpec]:
    """Every page reachable by a single GET: no form to fill, no route to pick first.

    Pages that require completing a real POST flow (guest/admin scan-to-quantity,
    the trend chart modal) are handled separately in capture_device, not listed here.
    """
    base = f"/inventory/{agency_id}"
    return [
        PageSpec("login", "/", "Auth: Login"),
        PageSpec("forgot_password", "/forgot-password", "Auth: Forgot Password"),
        PageSpec("reset_password", "/reset-password", "Auth: Reset Password"),
        PageSpec("guest_index", f"{base}/", "Guest: Search/Scan Home"),
        PageSpec("guest_admin_login", f"{base}/admin", "Guest: Admin PIN Unlock"),
        PageSpec("admin_panel", f"{base}/admin-panel", "Admin: Panel Home", admin=True),
        PageSpec("admin_data", f"{base}/admin-panel/data", "Admin: Data (Items/Tags/Notifications)", admin=True),
        PageSpec("admin_help", f"{base}/admin-panel/help", "Admin: Help", admin=True),
        PageSpec("admin_help_article", f"{base}/admin-panel/help/{article_id}", "Admin: Help Article", admin=True),
        PageSpec("admin_history", f"{base}/admin-panel/history", "Admin: History", admin=True),
        PageSpec(
            "admin_history_location",
            f"{base}/admin-panel/history/{location_id}",
            "Admin: History (by location)",
            admin=True,
        ),
        PageSpec("admin_history_print", f"{base}/admin-panel/history/print", "Admin: History (print)", admin=True),
        PageSpec(
            "admin_history_print_location",
            f"{base}/admin-panel/history/{location_id}/print",
            "Admin: History (print, by location)",
            admin=True,
        ),
        PageSpec("admin_scan_items", f"{base}/admin-panel/scan-items", "Admin: Scan Route Setup", admin=True),
        PageSpec("admin_scan_start", f"{base}/admin-panel/scan?item_id={item_id}", "Admin: Scan Start", admin=True),
        PageSpec("admin_bulk_actions", f"{base}/admin-panel/bulk-actions", "Admin: Bulk Actions", admin=True),
        PageSpec(
            "admin_bulk_actions_location",
            f"{base}/admin-panel/bulk-actions/{location_id}",
            "Admin: Bulk Actions (by location)",
            admin=True,
        ),
        PageSpec(
            "admin_bulk_select_items",
            f"{base}/admin-panel/bulk-actions/{location_id}/items",
            "Admin: Bulk Select Items",
            admin=True,
        ),
        PageSpec(
            "admin_bulk_edit",
            f"{base}/admin-panel/bulk-actions/{location_id}/edit",
            "Admin: Bulk Edit Grid (all items)",
            admin=True,
        ),
        PageSpec(
            "admin_inventory_counts",
            f"{base}/admin-panel/inventory-count-levels",
            "Admin: Inventory Count Levels",
            admin=True,
        ),
        PageSpec(
            "admin_inventory_counts_location",
            f"{base}/admin-panel/inventory-count-levels/{location_id}",
            "Admin: Inventory Count Levels (by location)",
            admin=True,
        ),
        PageSpec(
            "admin_inventory_counts_print",
            f"{base}/admin-panel/inventory-count-levels/print",
            "Admin: Inventory Count Levels (print)",
            admin=True,
        ),
        PageSpec(
            "admin_inventory_counts_print_location",
            f"{base}/admin-panel/inventory-count-levels/{location_id}/print",
            "Admin: Inventory Count Levels (print, by location)",
            admin=True,
        ),
        PageSpec("admin_pending_tasks", f"{base}/admin-panel/pending-tasks", "Admin: Pending Tasks", admin=True),
        PageSpec(
            "admin_pending_expiration",
            f"{base}/admin-panel/pending-tasks/expiration-dates",
            "Admin: Pending Expiration Dates",
            admin=True,
        ),
        PageSpec("admin_pending_upcs", f"{base}/admin-panel/pending-upcs", "Admin: Pending UPCs", admin=True),
        PageSpec("admin_print_labels", f"{base}/admin-panel/print-labels", "Admin: Print Labels Select", admin=True),
        PageSpec(
            "admin_print_label_preview",
            f"{base}/admin-panel/print-labels/preview",
            "Admin: Print Labels Preview (all items)",
            admin=True,
        ),
        PageSpec("admin_restock", f"{base}/admin-panel/restock", "Admin: Restock", admin=True),
        PageSpec(
            "admin_restock_location",
            f"{base}/admin-panel/restock/{location_id}",
            "Admin: Restock (by location)",
            admin=True,
        ),
        PageSpec("admin_restock_print", f"{base}/admin-panel/restock/print", "Admin: Restock (print)", admin=True),
        PageSpec(
            "admin_restock_print_location",
            f"{base}/admin-panel/restock/{location_id}/print",
            "Admin: Restock (print, by location)",
            admin=True,
        ),
        PageSpec("admin_settings", f"{base}/settings", "Admin: Settings", admin=True),
    ]


FLOW_PAGE_LABELS: dict[str, str] = {
    "guest_scan_location": "Guest: Choose Location",
    "guest_scan_storages": "Guest: Choose Route (real storages)",
    "guest_scan_item": "Guest: Enter Quantity",
    "admin_scan_storages": "Admin: Choose Route (real storages)",
    "admin_scan_item": "Admin: Enter Quantity",
    "admin_item_trend_modal": "Admin: Item Trend Chart (modal)",
}


def new_context(browser: Browser, profile: DeviceProfile) -> BrowserContext:
    return browser.new_context(
        viewport={"width": profile.width, "height": profile.height},
        device_scale_factor=profile.device_scale_factor,
        is_mobile=profile.is_mobile,
        has_touch=profile.has_touch,
        user_agent=profile.user_agent,
    )


def login(page: Page, base_url: str, email: str, password: str) -> None:
    page.goto(base_url + "/")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")


def unlock_admin(page: Page, base_url: str, agency_id: int, pin: str, attempts: int = 3) -> None:
    admin_panel_url = f"{base_url}/inventory/{agency_id}/admin-panel"
    for attempt in range(1, attempts + 1):
        page.goto(f"{base_url}/inventory/{agency_id}/admin")
        for digit in pin:
            page.click(f'button[data-digit="{digit}"]')
        page.click("button.login")
        page.wait_for_load_state("networkidle")
        if page.url.rstrip("/") == admin_panel_url.rstrip("/"):
            return
        print(f"  admin unlock attempt {attempt} landed on {page.url}, retrying")
    raise RuntimeError(f"Admin unlock never reached {admin_panel_url} after {attempts} attempts")


def choose_route_and_continue(page: Page) -> None:
    """Fill the FROM/TO storage-route form (scan_storages.html) as a real TAKE and submit."""
    page.locator('input[name="from_storage_id"]:not([value="-1"]):not([value="-2"])').first.check(force=True)
    page.locator('input[name="to_storage_id"][value="-3"]').check(force=True)
    page.click("#continue-button", force=True)
    page.wait_for_load_state("networkidle")


def read_flash(page: Page) -> tuple[str, str]:
    """Return (category, message) from #flash-container, empty strings if absent (e.g. print-only templates)."""
    element = page.query_selector("#flash-container")
    if element is None:
        return "", ""
    category, message = element.evaluate("el => [el.dataset.category || '', el.dataset.message || '']")
    return category, message


class DeviceCapture:
    """Screenshots one device's full page set into a shared results/flash_report."""

    def __init__(self, page: Page, device_key: str, flash_report: list[tuple[str, str, str, str]]) -> None:
        self.page = page
        self.device_key = device_key
        self.flash_report = flash_report
        self.device_dir = OUTPUT_DIR / device_key
        self.device_dir.mkdir(parents=True, exist_ok=True)
        self.results: dict[str, str] = {}

    def snapshot(self, key: str) -> None:
        out_path = self.device_dir / f"{key}.png"
        self.page.screenshot(path=str(out_path))
        self.results[key] = out_path.name

        category, message = read_flash(self.page)
        if category in ("error", "warning"):
            self.flash_report.append((self.device_key, key, category, message))
            print(f"  [{self.device_key}] {key}: FLASH [{category}] {message!r}")
        else:
            print(f"  [{self.device_key}] {key} -> {out_path.relative_to(OUTPUT_DIR)}")

    def visit(self, base_url: str, spec: PageSpec, agency_id: int, pin: str) -> None:
        try:
            self.page.goto(base_url + spec.path, wait_until="networkidle", timeout=15000)
            if spec.admin and not self.page.url.startswith(base_url + spec.path):
                print(f"  [{self.device_key}] {spec.key}: admin session dropped, re-unlocking")
                unlock_admin(self.page, base_url, agency_id, pin)
                self.page.goto(base_url + spec.path, wait_until="networkidle", timeout=15000)
        except Exception as exc:
            print(f"  [{self.device_key}] {spec.key}: navigation error ({exc})")
        self.snapshot(spec.key)

    def capture_guest_scan_flow(self, base_url: str, agency_id: int, item_id: int) -> None:
        base = f"{base_url}/inventory/{agency_id}"
        try:
            self.page.goto(f"{base}/scan/location?item_id={item_id}", wait_until="networkidle", timeout=15000)
            self.snapshot("guest_scan_location")

            self.page.locator('input[name="agency_location_id"]').first.check(force=True)
            self.page.click("form button[type=submit]", force=True)
            self.page.wait_for_load_state("networkidle")
            self.snapshot("guest_scan_storages")

            choose_route_and_continue(self.page)
            self.snapshot("guest_scan_item")
        except Exception as exc:
            print(f"  [{self.device_key}] guest scan flow: error ({exc})")

    def capture_admin_scan_flow(self, base_url: str, agency_id: int, item_id: int, pin: str) -> None:
        unlock_admin(self.page, base_url, agency_id, pin)
        base = f"{base_url}/inventory/{agency_id}/admin-panel"
        try:
            self.page.goto(f"{base}/scan/storages?item_id={item_id}", wait_until="networkidle", timeout=15000)
            self.snapshot("admin_scan_storages")

            choose_route_and_continue(self.page)
            self.snapshot("admin_scan_item")
        except Exception as exc:
            print(f"  [{self.device_key}] admin scan flow: error ({exc})")

    def capture_trend_modal(self, base_url: str, agency_id: int, location_id: int, pin: str) -> None:
        unlock_admin(self.page, base_url, agency_id, pin)
        try:
            self.page.goto(
                f"{base_url}/inventory/{agency_id}/admin-panel/restock/{location_id}",
                wait_until="networkidle",
                timeout=15000,
            )
            self.page.locator("[data-trend-url]").first.click(force=True)
            self.page.wait_for_timeout(600)
            self.snapshot("admin_item_trend_modal")
        except Exception as exc:
            print(f"  [{self.device_key}] trend modal: error ({exc})")


@dataclass(frozen=True, slots=True)
class RunContext:
    """Everything held fixed across one full capture run (all devices, all pages)."""

    browser: Browser
    base_url: str
    email: str
    password: str
    pin: str
    agency_id: int
    location_id: int
    item_id: int
    pages: list[PageSpec]
    flash_report: list[tuple[str, str, str, str]]


def capture_device(device_key: str, profile: DeviceProfile, run: RunContext) -> dict[str, str]:
    context = new_context(run.browser, profile)
    page = context.new_page()
    login(page, run.base_url, run.email, run.password)

    capture = DeviceCapture(page, device_key, run.flash_report)
    specs_by_key = {spec.key: spec for spec in run.pages}

    def visit(key: str) -> None:
        capture.visit(run.base_url, specs_by_key[key], run.agency_id, run.pin)

    # Guest section first: guest routes always clear any admin session (by design), so
    # this must run before the first admin unlock.
    visit("login")
    visit("forgot_password")
    visit("reset_password")
    visit("guest_index")
    capture.capture_guest_scan_flow(run.base_url, run.agency_id, run.item_id)
    visit("guest_admin_login")

    unlock_admin(page, run.base_url, run.agency_id, run.pin)
    for key in specs_by_key:
        if specs_by_key[key].admin:
            visit(key)
    capture.capture_admin_scan_flow(run.base_url, run.agency_id, run.item_id, run.pin)
    capture.capture_trend_modal(run.base_url, run.agency_id, run.location_id, run.pin)

    context.close()
    return capture.results


GALLERY_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Device Screenshot Gallery</title>
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f4f5f7; color: #1a1a1a; }}
  header {{ position: sticky; top: 0; background: #1a1a2e; color: #fff; padding: 14px 20px; z-index: 5; }}
  header h1 {{ margin: 0; font-size: 16px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; text-align: left; }}
  th {{ background: #eceef2; position: sticky; top: 52px; }}
  td.page-label {{ font-weight: 600; white-space: nowrap; background: #f8f9fb; position: sticky; left: 0; }}
  img {{ height: 200px; width: auto; display: block; object-fit: contain; background: #fff;
    border: 1px solid #ccc; border-radius: 4px; cursor: zoom-in; }}
  img:hover {{ outline: 2px solid #4a7dff; }}
</style>
</head>
<body>
<header><h1>Device Screenshot Gallery</h1></header>
<table>
<thead><tr><th>Page</th>{device_headers}</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""


def write_gallery(pages: list[PageSpec], device_keys: list[str], all_results: dict[str, dict[str, str]]) -> None:
    device_headers = "".join(f"<th>{DEVICES[key].label}</th>" for key in device_keys)
    labels = {spec.key: spec.label for spec in pages} | FLOW_PAGE_LABELS
    rows = []
    for page_key, label in labels.items():
        cells = []
        for device_key in device_keys:
            filename = all_results.get(device_key, {}).get(page_key)
            if filename:
                cells.append(f'<td><a href="{device_key}/{filename}" target="_blank"><img src="{device_key}/{filename}"></a></td>')
            else:
                cells.append("<td>&mdash;</td>")
        rows.append(f"<tr><td class='page-label'>{label}</td>{''.join(cells)}</tr>")

    html = GALLERY_TEMPLATE.format(device_headers=device_headers, rows="\n".join(rows))
    (OUTPUT_DIR / "index.html").write_text(html)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--agency-id", type=int, default=1)
    parser.add_argument("--location-id", type=int, default=1)
    parser.add_argument("--item-id", type=int, default=1, help="Real item id, needed for scan-flow pages")
    parser.add_argument("--article-id", default="account-security-and-access", help="Real help-article id")
    parser.add_argument("--email", default="mattmammano+squad35demo@gmail.com")
    parser.add_argument("--password", default="1234")
    parser.add_argument("--pin", default="1234")
    parser.add_argument("--devices", nargs="+", choices=list(DEVICES), default=list(DEVICES))
    args = parser.parse_args()

    pages = build_pages(args.agency_id, args.location_id, args.item_id, args.article_id)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, dict[str, str]] = {}
    flash_report: list[tuple[str, str, str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        run = RunContext(
            browser=browser,
            base_url=args.base_url,
            email=args.email,
            password=args.password,
            pin=args.pin,
            agency_id=args.agency_id,
            location_id=args.location_id,
            item_id=args.item_id,
            pages=pages,
            flash_report=flash_report,
        )
        for device_key in args.devices:
            profile = DEVICES[device_key]
            print(f"Capturing {profile.label}...")
            all_results[device_key] = capture_device(device_key, profile, run)
        browser.close()

    write_gallery(pages, args.devices, all_results)
    print(f"\nGallery: {(OUTPUT_DIR / 'index.html').resolve()}")

    if flash_report:
        print(f"\n{len(flash_report)} page(s) showed an error/warning flash:")
        for device_key, page_key, category, message in flash_report:
            print(f"  [{device_key}] {page_key}: [{category}] {message}")
    else:
        print("\nNo error/warning flashes on any page, any device.")


if __name__ == "__main__":
    main()
