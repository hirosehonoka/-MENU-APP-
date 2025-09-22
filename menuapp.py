from flask import Flask,render_template,request,redirect,flash,url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.automap import automap_base
from sqlalchemy import  cast, BigInteger,literal,select,union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from flask_login import UserMixin,LoginManager,login_user,login_required,logout_user,current_user
from werkzeug.security import generate_password_hash,check_password_hash
import os
from collections import defaultdict

app = Flask(__name__)

app.jinja_env.globals['getattr'] = getattr

app.config["SECRET_KEY"] = os.urandom(24)

#ログイン管理システム
login_manager = LoginManager()
login_manager.init_app(app)

db = SQLAlchemy()
DB_INFO = {
    'user':'postgres',
    'password':'',
    'host':'localhost',
    'name':'postgres'
}
SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg://{user}:{password}:@{host}/{name}'.format(**DB_INFO)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
db.init_app(app)

Base = automap_base()
with app.app_context():
    Base.prepare(db.engine, reflect=True)
RecipeUrl = Base.classes.recipeUrls
Menu = Base.classes.menu
ItemEqual = Base.classes.itemEquals
RecipeItem = Base.classes.recipeItems
# RecipeNutrition = Base.classes.recipeNutritions
# Recipe = Base .classes.recipes
# ItemWeight = Base .classes .itemWeights
# NutritionalTarget = Base .classes.nutritionalTargets
User = Base.classes.user

with app.app_context():
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db.engine)
    session = SessionLocal()

#現在のユーザを識別する
@login_manager.user_loader
def load_user(user_id):
    user = db.session.query(User).get(int(user_id))
    if user:
        return UserWrapper(user)
    return None

class User(UserMixin,db.Model):
    userId = db.Column(db.Integer,primary_key=True)
    userName = db.Column(db.String(20),nullable=False,unique=True)
    password = db.Column(db.String(200),nullable=False)
    userInfo = db.Column(JSONB,nullable=False)

# class RecipeUrl(db.Model):
#     recipeId = db.Column(db.Integer,primary_key=True)
#     recipeTitle = db.Column(db.String,nullable=False)
#     recipeUrl = db.Column(db.String,nullable=True)
#     foodImageUrl= db.Column(db.String,nullable=False)

# class Menu(db.Model):
#     menuId = db.Column(db.Integer,primary_key=True)
#     menu1 = db.Column(JSONB,nullable=False)
#     menu2 = db.Column(JSONB,nullable=False)
#     menu3 = db.Column(JSONB,nullable=False)
#     menu4 = db.Column(JSONB,nullable=False)
#     menu5 = db.Column(JSONB,nullable=False)
#     menu6 = db.Column(JSONB,nullable=False)
#     menu7 = db.Column(JSONB,nullable=False)
#     userName = db.Column(db.String(20),nullable=False)
#     tokyo_timezone = pytz.timezone('Asia/Tokyo')
#     createdAt = db.Column(db.DateTime,nullable=False,default=datetime.now)

# class ItemEqual(db.Model):
#     itemName = db.Column(db.String,primary_key=True)
#     equals = db.Column(JSONB,nullable=False)

# class RecipeItem(db.Model):
#     recipeId = db.Column(db.Integer,primary_key=True)
#     items = db.Column(JSONB,nullable=False)

class UserWrapper(UserMixin):
    def __init__(self, user):
        self.user = user

    def __getattr__(self, name):
        return getattr(self.user, name)

    def get_id(self):
        # userIdカラムを文字列にして返す
        return str(self.user.userId)

    @property
    def is_active(self):
        return True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False
    
@app.route("/")
def home():
    return render_template("home.html", show_navbar=False)
    
@app.route("/menu")
@login_required
def show_menus():
    weekly_data = []
    menu = db.session.query(Menu).filter_by(userName=current_user.userName).first()

    if menu is None:
        return render_template("menu.html", weekly_data=[], show_navbar=True)

    queries = []
    idx = 0

    for menu_col in ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']:
        menu_json = getattr(menu, menu_col, {})
        for meal_type in ['staple', 'main', 'side', 'soup']:
            val = menu_json.get(meal_type)
            if val is None:  # nullはスキップ
                continue

            try:
                recipe_id = int(val) if not hasattr(val, 'astext') else int(val.astext)
            except (ValueError, TypeError):
                continue

            idx += 1

            query = (
                db.session.query(
                    RecipeUrl.recipeTitle.label('recipeTitle'),
                    RecipeUrl.recipeUrl.label('recipeUrl'),
                    RecipeUrl.foodImageUrl.label('foodImageUrl'),
                    literal(f'{menu_col}_{meal_type}').label('meal_type'),
                )
                .join(Menu, RecipeUrl.recipeId == cast(getattr(Menu, menu_col)[meal_type].astext, BigInteger))
                .filter(Menu.userName == current_user.userName)
                .filter(RecipeUrl.recipeId == recipe_id)
            )
            queries.append(query)

    if not queries:
        return render_template("menu.html", weekly_data=[], show_navbar=True)

    full_query = queries[0]
    for q in queries[1:]:
        full_query = full_query.union_all(q)

    core_queries = [q.statement for q in queries]
    full_union = union_all(*core_queries).alias('full_union')

    stmt = select(
        full_union.c.recipeTitle,
        full_union.c.recipeUrl,
        full_union.c.foodImageUrl,
        full_union.c.meal_type,
    )

    results = db.session.execute(stmt).fetchall()

    grouped = defaultdict(list)
    for r in results:
        menu_col = r.meal_type.split('_')[0] 
        grouped[menu_col].append(r)

    menu_order = ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']
    weekly_data = [grouped[m] for m in menu_order]

    return render_template("menu.html", weekly_data=weekly_data, current_page='menu', show_navbar=True)

@app.route("/item")
@login_required
def show_item():
    aggregated_ingredients = {}
    menu = db.session.query(Menu).filter_by(userName=current_user.userName).first()
    if menu is None:
        return render_template("item.html", ingredients=aggregated_ingredients, total_types=0, current_page='item', show_navbar=True)

    # menu1〜menu7のすべてのrecipeIdを取得（中身が例えば {staple:123, main:456} のような構造を想定）
    recipe_ids = []
    for menu_col in ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']:
        menu_json = getattr(menu, menu_col, {})
        for meal_type in ['staple', 'main', 'side', 'soup']:
            val = menu_json.get(meal_type)
            if val is None:
                continue
            try:
                recipe_id = int(val) if not hasattr(val, 'astext') else int(val.astext)
            except (ValueError, TypeError):
                continue
            recipe_ids.append(recipe_id)

    recipe_ids = list(set(recipe_ids))

    # ItemEqualの辞書作成: 等価食材名 -> 代表名
    item_equals = db.session.query(ItemEqual).all()
    item_equal_map = {}
    for eq in item_equals:
        for k, v in eq.equals.items():
            item_equal_map[k] = eq.itemName
            item_equal_map[v] = eq.itemName
        item_equal_map[eq.itemName] = eq.itemName

    # recipeIdごとにitemsを集計
    for rid in recipe_ids:
        recipe_item = db.session.query(RecipeItem).filter(RecipeItem.recipeId == rid).first()
        if not recipe_item:
            continue
        for ing_name, qty in recipe_item.items.items():
            # 代表名に変換
            rep_name = item_equal_map.get(ing_name, ing_name)

            # 加算
            aggregated_ingredients[rep_name] = aggregated_ingredients.get(rep_name, 0) + qty

    total_types = len(aggregated_ingredients)

    return render_template('item.html', ingredients=aggregated_ingredients, total_types=total_types, current_page='item', show_navbar=True)

# @app.route("/nutritional")
# @login_required
# def show_nutritional():
#     menu = db.session.query(Menu).filter_by(userName=current_user.userName).first()
#     if menu is None:
#         return render_template("nutritional.html",  current_page='nutritional', show_navbar=True)

#     # menu1〜menu7のすべてのrecipeIdを取得（中身が例えば {staple:123, main:456} のような構造を想定）
#     recipe_ids = []
#     for menu_col in ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']:
#         menu_json = getattr(menu, menu_col, {})
#         for meal_type in ['staple', 'main', 'side', 'soup']:
#             val = menu_json.get(meal_type)
#             if val is None:
#                 continue
#             try:
#                 recipe_id = int(val) if not hasattr(val, 'astext') else int(val.astext)
#             except (ValueError, TypeError):
#                 continue
#             recipe_ids.append(recipe_id)

#     recipe_ids = list(set(recipe_ids))

@app.route("/signup",methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        userName = request.form.get('userName')
        password = request.form.get('password')
        hashed_pass = generate_password_hash(password)
        userAge = request.form.get('userAge')
        userGender = request.form.get('userGender')
        userExerciseLevel = request.form.get('userExerciseLevel')
        userInfo ={"年齢":userAge,"性別":userGender,"運動レベル":userExerciseLevel}
        user = User(userName=userName,password=hashed_pass,userInfo=userInfo)
        db.session.add(user)
        db.session.commit()
        return redirect('/login')
    elif request.method == 'GET':
        return render_template('signup.html', show_navbar=False)
    
@app.route("/userupdate", methods=['GET', 'POST'])
@login_required
def userupdate():
    user = db.session.query(User).get(current_user.get_id())

    if request.method == 'POST':
        userAge = request.form.get('userAge')
        userExerciseLevel = request.form.get('userExerciseLevel')

        if user and user.userInfo:
            # userInfoは辞書と仮定
            user.userInfo['年齢'] = userAge
            user.userInfo['運動レベル'] = userExerciseLevel

            db.session.commit()
        return redirect('/menu')

    else:  # GET
        userAge_selected = user.userInfo.get('年齢') if user and user.userInfo else None
        userExerciseLevel_selected = user.userInfo.get('運動レベル') if user and user.userInfo else None

        return render_template(
            'userupdate.html',
            userAge_selected=userAge_selected,
            userExerciseLevel_selected=userExerciseLevel_selected,
            current_page='userupdate',
            show_navbar=True
        )

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method == 'POST':
        userName = request.form.get('userName')
        password = request.form.get('password')
        user = db.session.query(User).filter_by(userName=userName).first()
        print(user.userName)
        if check_password_hash(user.password,password=password):
            wrapped_user = UserWrapper(user)
            login_user(wrapped_user)
            return redirect('/menu')
        else:
            flash('ユーザ名かパスワードが違います。')
            return redirect(url_for('login'))
    elif request.method == 'GET':
        return render_template('login.html', show_navbar=False)
    
@app.route('/logout',methods=['GET','POST'])
@login_required
def logout():
    logout_user()
    return redirect('/login')


#Flask --app menuapp run --debug で実行