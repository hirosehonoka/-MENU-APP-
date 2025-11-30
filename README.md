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

Herokuのデータベースを見る方法
- `heroku pg:psql -a menuapp`

Herokuのアプリの停止
- `heroku ps:scale web=0 -a menuapp`

- Herokuのアプリの開始
- `heroku ps:scale web=1 -a menuapp`
