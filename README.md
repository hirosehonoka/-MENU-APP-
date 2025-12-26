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

`
CREATE TABLE generated_menu_test2_5
(
  LIKE public.generated_menu_solver INCLUDING ALL
);

CREATE SEQUENCE generated_menu_test2_5_id_seq
    INCREMENT BY 1
    MINVALUE 1
    START WITH 1
    NO CYCLE;

ALTER TABLE generated_menu_test2_5
    ALTER COLUMN id SET DEFAULT nextval('generated_menu_test2_id_seq'::regclass);
`

`python -m venv .venv`
`source .venv/bin/activate`
