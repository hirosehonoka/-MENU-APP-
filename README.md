# -MENU-APP-

githubコミットの仕方

github --> local
- `git pull origin main`

local --> github
 - `git add .`
 - `git commit -m "コメント"`
 - `git push origin main`

レコードのリセット
 - `SELECT setval('"menu_menuId_seq"', (SELECT MAX("menuId") FROM menu));`

Flaskコマンドが作動しなくなったら
- `source .venv/bin/activate`
