from flask import Flask,render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB
import os,json


app = Flask(__name__)

db = SQLAlchemy()
DB_INFO = {
    'user':'postgres',
    'password':'',
    'host':'localhost',
    'name':'postgres'
}
SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg://{user}:{password}:@{host}/{name}'.format(**DB_INFO)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

class Recipe(db.Model):
    __tablename__ = "nutritionalTargets"
    targetId = db.Column(db.Integer,primary_key=True,autoincrement=True)
    targets = db.Column(JSONB,nullable=False)
    nutritionals = db.Column(JSONB,nullable=False)

@app.cli.command("load_recipes")
def load_recipes():
    db.create_all()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir,"data","nutritionalTarget.json")

    db.session.query(Recipe).delete()

    with open(json_path,"r",encoding="utf-8") as f:
        recipes = json.load(f)

    recipe_objects = []
   
    for recipe in recipes:
        try:
            recipe_obj = Recipe(
                targets = {k: v for k, v in recipe.items() if k in ["年齢", "性別", "運動レベル"]},
                nutritionals = {k: v for k, v in recipe.items() if k not in ["年齢", "性別", "運動レベル"]}
            )
            recipe_objects.append(recipe_obj)
        except Exception as e:
            print(f"Error processing recipeId {recipe.get('recipeId')}: {e}")

    db.session.add_all(recipe_objects)
    db.session.commit()
    print(f"{len(recipes)}件のレシピをDBに保存しました")

    #flask --app jsondata.py load_recipes をターミナルで実行
