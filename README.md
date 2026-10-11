# HRL Books

HRL Books to platforma, a nie tylko wydawnictwo: prowadzi książkę od researchu przez pisanie,
redakcję i metadane po dystrybucję i tantiemy, dla wielu wydawców i autorów (na zaproszenie).
Wydawnictwo HRL Books jest jej pierwszym workspace'em. Adres: https://hrl-books.hardbanrecordslab.online Specyfikacja (v0.2):
https://claude.ai/artifact/6TjwyH9kzW2wTZLufju7GA

## Stan

Etap 1, pierwszy wycinek (moduł ACC + podstawy BOOK):

- rejestracja wyłącznie z jednorazowego zaproszenia (FR-ACC-01, -06), administrator platformy tworzy
  workspace'y i zaprasza właścicieli (FR-ACC-07);
- logowanie z hasłem Argon2id, blokada po 5 nieudanych próbach, krótki token dostępu + rotowany
  refresh token z unieważnianiem całej rodziny przy ponownym użyciu (FR-ACC-02, -03);
- role i macierz uprawnień ze specyfikacji 3.2 (role nie są drabiną);
- izolacja workspace'ów: zasób z cudzego workspace'u zwraca 404 (test `test_isolation.py`);
- przełącznik AI domyślnie wyłączony (FR-AI-07), log audytu, miękkie usuwanie tytułów.

## Uruchomienie

```bash
cp .env.example .env   # uzupełnij POSTGRES_PASSWORD, JWT_SECRET, SMTP_PASSWORD
docker compose up -d --build
docker compose exec api python -m app.cli create-admin kamil@... /ścieżka/do/pliku-z-hasłem
```

API: `http://127.0.0.1:8127/api/v1/health`, dokumentacja: `/api/v1/docs`.

## Testy

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
```

Lokalnie testy używają SQLite; CI uruchamia migracje i testy na prawdziwym Postgresie.
