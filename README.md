# NBA notte per notte
1. Crea un repository GitHub e carica questi file (mantieni .github/workflows/update.yml).
2. Tab Actions > "Aggiorna dati NBA" > Run workflow (prima esecuzione manuale).
3. Settings > Pages > Deploy from branch > main / root.
4. Il sito sarà su https://TUONOME.github.io/NOMEREPO e si aggiorna ogni 3 ore.
Test locale: pip install requests && python update.py && python -m http.server
