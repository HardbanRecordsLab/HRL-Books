import io
import json
from datetime import datetime

from openpyxl import Workbook

from app.royalties import parse_number, parse_period
from tests.conftest import PASSWORD, auth, last_invite_token, make_workspace


def _setup(client):
    ws, owner = make_workspace(client, "wydawnictwo", "owner@example.com")
    h = auth(owner["access_token"])
    base = f"/api/v1/workspaces/{ws}"
    b1 = client.post(f"{base}/books", headers=h, json={"title": "Rodzic bez poczucia winy", "subtitle": "Poradnik"}).json()["id"]
    b2 = client.post(f"{base}/books", headers=h, json={"title": "Cisza po burzy"}).json()["id"]
    client.patch(f"{base}/books/{b2}", headers=h, json={"store_links": [{"url": "https://www.amazon.com/dp/B0CISZA123"}]})
    return ws, h, base, b1, b2


def _kdp_xlsx() -> bytes:
    wb = Workbook()
    s = wb.active
    s.append(["Sales Period", "September 2026"])  # title rows before the real header, like KDP exports
    s.append([])
    s.append(["Royalty Date", "Title", "Author Name", "ASIN/ISBN", "Marketplace", "Net Units Sold", "Royalty", "Currency"])
    s.append([datetime(2026, 9, 3), "Rodzic bez poczucia winy: Poradnik", "Kamil Skomra", "B0RODZIC01", "Amazon.com", 3, 8.97, "USD"])
    s.append([datetime(2026, 9, 3), "Rodzic bez poczucia winy: Poradnik", "Kamil Skomra", "B0RODZIC01", "Amazon.com", 3, 8.97, "USD"])
    s.append([datetime(2026, 9, 12), "Cisza po burzy (Polish Edition)", "Kamil Skomra", "B0CISZA123", "Amazon.de", 1, 2.10, "EUR"])
    s.append([datetime(2026, 10, 1), "Zupełnie inna książka", "X", "B0OTHER999", "Amazon.com", 2, 4.00, "USD"])
    s.append(["Total", "", "", "", "", 9, 23.04, ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parsers():
    assert parse_number("1 234,56 zł") == 1234.56 and parse_number("1,234.56") == 1234.56 and parse_number("12,5") == 12.5
    assert parse_number("1,234") == 1234 and parse_number("-3.20") == -3.2 and parse_number(None) == 0
    assert parse_period("2026-09-03") == "2026-09" and parse_period("15.09.2026") == "2026-09"
    assert parse_period("09/15/2026") == "2026-09" and parse_period("Sep 2026") == "2026-09" and parse_period("nic") is None


def test_kdp_xlsx_import_matching_duplicates_and_summary(client):
    ws, h, base, b1, b2 = _setup(client)
    r = client.post(f"{base}/royalties/import", headers=h, data={"channel": "kdp"},
                    files={"file": ("KDP_Royalties.xlsx", _kdp_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    assert r.json()["rows"] == 4 and r.json()["duplicates"] == 0  # identical rows are two real sales; "Total" skipped
    again = client.post(f"{base}/royalties/import", headers=h, data={"channel": "kdp"}, files={"file": ("k.xlsx", _kdp_xlsx())}).json()
    assert again == {"import_id": again["import_id"], "rows": 0, "duplicates": 4}

    s = client.get(f"{base}/royalties", headers=h).json()
    assert s["totals"]["units"] == 9 and s["totals"]["amounts"] == {"EUR": 2.1, "USD": 21.94}
    books = {x["title"]: x for x in s["by_book"]}
    assert books["Rodzic bez poczucia winy"]["amounts"] == {"USD": 17.94}  # title + subtitle match
    assert books["Cisza po burzy"]["units"] == 1  # matched by ASIN in the store link
    assert [u["raw_title"] for u in s["unmatched"]] == ["Zupełnie inna książka"]
    assert [x["period"] for x in s["by_month"]] == ["2026-09", "2026-10"] and s["years"] == ["2026"]

    client.post(f"{base}/royalties/assign", headers=h, json={"raw_title": "Zupełnie inna książka", "book_id": b2})
    s = client.get(f"{base}/royalties?book_id={b2}", headers=h).json()
    assert s["totals"]["units"] == 3 and s["unmatched"] == []


def test_polish_csv_needs_period_and_mapping(client):
    ws, h, base, b1, b2 = _setup(client)
    csv_text = "Tytuł;Sztuk;Kwota\nCisza po burzy;5;\"12,50\"\n".encode("cp1250")
    r = client.post(f"{base}/royalties/import", headers=h, data={"channel": "empik"}, files={"file": ("raport.csv", csv_text)})
    assert r.status_code == 422 and "miesiąc" in r.json()["detail"]["message"]
    r = client.post(f"{base}/royalties/import", headers=h, data={"channel": "empik", "period": "2026-08"}, files={"file": ("raport.csv", csv_text)})
    assert r.json()["rows"] == 1
    assert client.get(f"{base}/royalties", headers=h).json()["by_book"][0]["amounts"] == {"PLN": 12.5}

    odd = "Nazwa;Ile;Zarobek;Kiedy\nCisza po burzy;2;3.00;2026-07-01\n".encode()
    r = client.post(f"{base}/royalties/import", headers=h, data={"channel": "other"}, files={"file": ("x.csv", odd)})
    assert r.status_code == 422 and r.json()["detail"]["headers"] == ["Nazwa", "Ile", "Zarobek", "Kiedy"]
    r = client.post(f"{base}/royalties/import", headers=h, data={"channel": "other", "mapping": json.dumps({"title": 0, "units": 1, "amount": 2, "period": 3})},
                    files={"file": ("x.csv", odd)})
    assert r.json()["rows"] == 1
    imp = client.get(f"{base}/royalties", headers=h).json()["imports"][0]["id"]
    client.delete(f"{base}/royalties/imports/{imp}", headers=h)
    assert client.get(f"{base}/royalties?year=2026", headers=h).json()["totals"]["units"] == 5


def test_royalties_owner_only_and_isolated(client):
    ws, h, base, b1, b2 = _setup(client)
    client.post(f"{base}/invitations", headers=h, json={"email": "ed@example.com", "role": "editor"})
    ed = auth(client.post("/api/v1/auth/register", json={"token": last_invite_token(), "password": PASSWORD}).json()["access_token"])
    assert client.get(f"{base}/royalties", headers=ed).status_code == 403
    ws_b, owner_b = make_workspace(client, "inne", "b@example.com")
    hb = auth(owner_b["access_token"])
    assert client.post(f"/api/v1/workspaces/{ws_b}/royalties/assign", headers=hb, json={"raw_title": "x", "book_id": b1}).status_code == 404
